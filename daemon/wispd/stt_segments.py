"""Speech-to-text by utterance, for models that don't stream (Hindi).

Meta's Omnilingual ASR decodes a whole utterance at once. A Silero voice
activity detector per source cuts the audio into utterances. While someone
is speaking, the utterance so far is re-decoded every PARTIAL_EVERY_S for
live captions; when it ends (0.5 s of silence) it is decoded once more and
sent as a finished line. At ~0.05x real time on 4 threads that keeps
captions about a second behind speech.

Same interface as stt.Transcriber, so the session can use either.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio import SAMPLE_RATE
from .stt import Utterance

log = logging.getLogger(__name__)

WINDOW = 512                 # Silero VAD frame at 16 kHz
PARTIAL_EVERY_S = 0.8
PARTIAL_MAX_S = 12.0         # captions re-decode at most this much of the utterance
MAX_UTTERANCE_S = 15.0       # long monologues are cut into pieces of this size
MIN_SILENCE_S = 0.5
MAX_ITEMS_PER_PASS = 32


@dataclass
class _Source:
    vad: object
    pending: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    speaking: bool = False
    started: float = 0.0
    since_partial: int = 0
    last_text: str = ""


class SegmentTranscriber:
    def __init__(self, model_dir: str | Path, vad_model: str | Path, threads: int,
                 emit: Callable[[Utterance], None], loop: asyncio.AbstractEventLoop):
        self.model_dir = Path(model_dir).expanduser()
        self.vad_model = Path(vad_model).expanduser()
        self.threads = threads
        self._emit = emit
        self._loop = loop
        self._rec = None
        self._vad_config = None
        self._q: queue.Queue = queue.Queue()
        self._sources: dict[str, _Source] = {}
        self._thread: threading.Thread | None = None
        self._running = False

    # -- setup -------------------------------------------------------------

    def load(self) -> None:
        """Blocking model load. Run it in an executor."""
        import sherpa_onnx

        for path in (self.model_dir / "model.int8.onnx", self.vad_model):
            if not path.exists():
                raise FileNotFoundError(f"{path} is missing; run `wisp lang hi` to download it")
        t = time.perf_counter()
        self._rec = sherpa_onnx.OfflineRecognizer.from_omnilingual_asr_ctc(
            model=str(self.model_dir / "model.int8.onnx"),
            tokens=str(self.model_dir / "tokens.txt"),
            num_threads=self.threads,
        )
        self._vad_config = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=str(self.vad_model), threshold=0.5,
                min_silence_duration=MIN_SILENCE_S, min_speech_duration=0.25,
                window_size=WINDOW, max_speech_duration=MAX_UTTERANCE_S),
            sample_rate=SAMPLE_RATE, num_threads=1)
        log.info("STT model loaded in %.1fs from %s", time.perf_counter() - t, self.model_dir.name)

    @property
    def loaded(self) -> bool:
        return self._rec is not None

    def add_source(self, name: str, gate: float) -> None:
        # The VAD decides what is speech, so the level gate is not used.
        self._q.put(("add", name))

    def start(self) -> None:
        assert self._rec is not None, "call load() first"
        self._running = True
        self._thread = threading.Thread(target=self._run, name="wisp-stt-hi", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    # -- input (called from the asyncio thread) ----------------------------

    def push(self, source: str, samples: np.ndarray, rms: float) -> None:
        # The session marks speaker echo with rms 0; treat it as silence.
        if rms <= 0.0:
            samples = np.zeros_like(samples)
        self._q.put(("audio", source, samples))

    def flush(self, source: str) -> None:
        self._q.put(("flush", source))

    # -- worker ------------------------------------------------------------

    def _run(self) -> None:
        import sherpa_onnx

        while self._running:
            try:
                items = [self._q.get(timeout=0.05)]
            except queue.Empty:
                continue
            while len(items) < MAX_ITEMS_PER_PASS:
                try:
                    items.append(self._q.get_nowait())
                except queue.Empty:
                    break
            touched: set[str] = set()
            for item in items:
                kind, name = item[0], item[1]
                if kind == "add":
                    if name not in self._sources:
                        self._sources[name] = _Source(sherpa_onnx.VoiceActivityDetector(
                            self._vad_config, buffer_size_in_seconds=MAX_UTTERANCE_S * 2))
                    continue
                st = self._sources.get(name)
                if st is None:
                    continue
                if kind == "audio":
                    self._feed(st, item[2])
                    touched.add(name)
                elif kind == "flush":
                    if len(st.pending):
                        st.vad.accept_waveform(np.pad(st.pending, (0, WINDOW - len(st.pending))))
                        st.pending = np.zeros(0, np.float32)
                    st.vad.flush()
                    touched.add(name)
            for name in touched:
                self._update(name, self._sources[name])

    def _feed(self, st: _Source, samples: np.ndarray) -> None:
        buf = np.concatenate([st.pending, samples]) if len(st.pending) else samples
        n = len(buf) // WINDOW * WINDOW
        for i in range(0, n, WINDOW):
            st.vad.accept_waveform(buf[i:i + WINDOW])
        st.pending = buf[n:].copy()
        st.since_partial += n

    def _update(self, name: str, st: _Source) -> None:
        speaking = st.vad.is_speech_detected()
        if speaking and not st.speaking:
            cur = st.vad.current_segment
            st.started = time.time() - (len(cur.samples) / SAMPLE_RATE if cur is not None else 0.0)
            st.since_partial = 0
        st.speaking = speaking

        while not st.vad.empty():
            seg = st.vad.front
            samples = np.asarray(seg.samples, dtype=np.float32)
            st.vad.pop()
            text = self._decode(samples)
            ended = time.time()
            started = st.started or ended - len(samples) / SAMPLE_RATE - MIN_SILENCE_S
            if text:
                self._send(Utterance(name, text, started, ended, final=True))
            st.last_text = ""
            # A cut at MAX_UTTERANCE_S: the speaker is still going.
            st.started = ended if st.vad.is_speech_detected() else 0.0
            st.since_partial = 0

        if speaking and st.since_partial >= PARTIAL_EVERY_S * SAMPLE_RATE:
            st.since_partial = 0
            cur = st.vad.current_segment
            samples = np.asarray(cur.samples, dtype=np.float32)[-int(PARTIAL_MAX_S * SAMPLE_RATE):] \
                if cur is not None else np.zeros(0, np.float32)
            if len(samples) >= 0.3 * SAMPLE_RATE:
                text = self._decode(samples)
                if text and text != st.last_text:
                    st.last_text = text
                    self._send(Utterance(name, text, st.started, time.time(), final=False))

    def _decode(self, samples: np.ndarray) -> str:
        s = self._rec.create_stream()
        s.accept_waveform(SAMPLE_RATE, samples)
        self._rec.decode_stream(s)
        return s.result.text.strip()

    def _send(self, u: Utterance) -> None:
        self._loop.call_soon_threadsafe(self._emit, u)
