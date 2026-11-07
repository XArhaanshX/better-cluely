"""Settings for wispd, read from ~/.config/wisp/config.toml.

Every field has a default, so the file is optional. Unknown keys are
reported and ignored rather than crashing the daemon.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "wisp"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "wisp"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
SOCKET_PATH = RUNTIME_DIR / "wisp.sock"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_STT_MODEL = DATA_DIR / "models" / "sherpa-onnx-nemotron-speech-streaming-en-0.6b-160ms-int8-2026-04-25"

# Model presets the UI can switch between. Through Claude Code, Haiku answers
# in ~0.85 s and Opus in ~2.1 s (measured, bench/cc_latency.py), so the
# Claude Code backend defaults to "fast". The API backend defaults to "smart".
CLAUDE_CODE_MODELS = {"smart": "opus", "fast": "haiku"}
API_MODELS = {"smart": "claude-opus-5-5", "fast": "claude-haiku-5-5"}
DEFAULT_PRESET = {"claude-code": "fast", "api": "smart"}


@dataclass
class Config:
    # "claude-code" uses the logged-in `claude` CLI; "api" uses the Anthropic API.
    backend: str = "claude-code"
    # "smart" or "fast"; empty picks the backend's default. An explicit model wins.
    preset: str = ""
    model: str = ""
    # API backend only. Empty means the SDK's normal credential lookup
    # (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile).
    api_key_file: str = ""
    effort: str = "low"
    # Claude Code backend: how many idle processes to keep ready.
    pool_size: int = 2

    stt_model_dir: str = str(DEFAULT_STT_MODEL)
    stt_threads: int = 2
    capture_mic: bool = True
    capture_system: bool = True
    # RMS level below which mic audio is treated as silence and not decoded.
    mic_gate: float = 0.006
    # "auto": on loudspeakers, record the mic through PipeWire's WebRTC echo
    # canceller so the other side is not transcribed as you. "off": never.
    echo_cancel: str = "auto"

    # Generate an answer as soon as the other side finishes a question.
    auto_answer: bool = True
    screenshot_scale: float = 0.6
    screenshot_quality: int = 70

    # Write meeting notes when listening stops (needs a few lines of transcript).
    auto_notes: bool = True
    # Where notes are saved as Markdown; empty means ~/Documents/wisp.
    notes_dir: str = ""

    mode: str = "general"
    # Optional notes, a resume, an agenda: included with every request.
    context_file: str = ""
    transcript_window_s: int = 900

    extra: dict = field(default_factory=dict, repr=False)

    def resolved_model(self) -> str:
        if self.model:
            return self.model
        table = CLAUDE_CODE_MODELS if self.backend == "claude-code" else API_MODELS
        return table.get(self.resolved_preset(), table["smart"])

    def resolved_preset(self) -> str:
        return self.preset or DEFAULT_PRESET.get(self.backend, "smart")

    def api_key(self) -> str | None:
        if not self.api_key_file:
            return None
        path = Path(self.api_key_file).expanduser()
        try:
            return path.read_text().strip() or None
        except OSError as e:
            log.warning("cannot read api_key_file %s: %s", path, e)
            return None

    def notes_path(self) -> Path:
        if self.notes_dir:
            return Path(self.notes_dir).expanduser()
        return Path.home() / "Documents" / "wisp"

    def context_text(self) -> str:
        if not self.context_file:
            return ""
        try:
            return Path(self.context_file).expanduser().read_text()[:40_000]
        except OSError as e:
            log.warning("cannot read context_file: %s", e)
            return ""

    def public(self) -> dict:
        """Settings safe to send to the UI (no secrets)."""
        d = dataclasses.asdict(self)
        d.pop("extra", None)
        d["resolved_model"] = self.resolved_model()
        d["resolved_preset"] = self.resolved_preset()
        return d


def load(path: Path = CONFIG_FILE) -> Config:
    cfg = Config()
    if not path.exists():
        return cfg
    with path.open("rb") as f:
        raw = tomllib.load(f)
    known = {f.name for f in dataclasses.fields(Config)} - {"extra"}
    for key, value in raw.items():
        if key in known:
            setattr(cfg, key, value)
        else:
            log.warning("unknown config key %r ignored", key)
            cfg.extra[key] = value
    return cfg
