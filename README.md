# wisp

A Cluely-style AI meeting assistant built natively for Hyprland on Linux.

wisp is a translucent bar at the top of the screen. It listens to both sides
of a call (your mic and whatever the call app plays), transcribes them live
on your own CPU, and answers from what was said and what is on screen. When
the other person finishes a question, the answer starts before you ask.

It is a ground-up rewrite of the idea behind
[Freely](https://github.com/lambdaflows/freely) / Pluely for Wayland: no
Electron or WebKit, real compositor shortcuts, and colours taken from your
wallpaper.

## What it does

- **Assist** (`Super+Alt+Enter`): reads the screen and the end of the
  conversation and gives the most useful help right now: the answer to the
  question just asked, a fix for the code on screen, or what to say next.
- **Live transcript** of both sides, labelled You and Them.
- **Echo cancellation on loudspeakers**: without headphones the mic hears
  the other side, so wisp records you through PipeWire's WebRTC echo
  canceller (on by itself when the output is speakers, off for headphones
  and Bluetooth). Your call app's audio is not rerouted and no default
  device changes.
- **Auto-answers**: questions from Them start an answer immediately. Assist
  then shows it at once; pressing Assist again asks fresh with a screenshot.
  Questions are recognised by word order ("what did you…" is a question,
  "what we did was…" is not) and by indirect prompts ("give me an
  example…", "I'm curious about…").
- **Quick actions**: What should I say?, Follow-up questions, Recap,
  Fact-check, Explain, Meeting notes.
- **Meeting notes** when you stop listening: summary, key points, decisions,
  a next-steps checklist and a follow-up email, saved as Markdown in
  `~/Documents/wisp` with the transcript.
- **Modes**: General, Interview, Meeting, Lecture. Add your own notes, resume
  or agenda with `context_file`.
- **Fast / Smart** toggle: Haiku or Opus.
- **Stays out of the way**: a layer surface above all windows that never
  takes focus unless you type, never shows in the taskbar, dock or alt-tab,
  lets clicks through outside its panels, and is blacked out in screen
  shares and recordings by Hyprland's `no_screen_share` rule.

## Shortcuts

| Keys | Action |
|---|---|
| `Super+\` | Show / hide |
| `Super+Alt+Enter` | Assist |
| `Super+Alt+L` | Start / stop listening |
| `Super+Alt+/` | Type a question |
| `Super+Alt+Esc` | Close the question box, then the answer, then the bar |
| `Super+Alt+,` / `.` | Previous / next answer |
| `Super+Alt+Arrows` | Move the overlay (or drag the bar) |
| `Super+Alt+Backspace` | New session |

Everything except show/hide sits on `Super+Alt`, so no app loses a shortcut.

## The `wisp` command

One word gets you meeting-ready: it starts the daemon and the overlay if
they are not running, shows the overlay and starts listening.
Nothing starts at login: wisp only runs after you type `wisp`, and
`wisp stop` shuts it down completely.

```sh
wisp                # start everything, show, listen
wisp off            # stop listening, hide (notes are written), daemon stays up
wisp ask            # Assist from the terminal; streams the answer and its timing
wisp ask "text"     # ask a typed question
wisp notes          # write meeting notes for the current session
wisp show | hide | listen [on|off] | status | stop | restart
```

It drives the overlay through its global shortcuts, so it works even
before the Hyprland keybinds have loaded.

## Speed

Measured on a Dell Pro Max 16 (Core Ultra, Arrow Lake), Nov 2026:

| Step | Time |
|---|---|
| Show / hide | one frame |
| Speech to caption | under 1 s behind speech |
| End of speech to finished line | ~0.6 s |
| Screenshot (grim + Pillow, 0.6x JPEG) | ~70–90 ms |
| First token, Claude Code + Haiku, text | 0.75–1.1 s |
| First token, Claude Code + Haiku, with screenshot | 1.0–3.5 s (depends on how much text is on screen) |
| First token, cold `claude -p` (what a naive integration pays) | ~1.7 s + |
| Auto-answer, seen when you press Assist | 0 s: it is already there |

The fixed cost is the model's own time to first token, so wisp hides it
instead: Claude Code processes are started ahead of time and kept warm,
the API backend keeps its connection open, and questions are answered as
soon as they are heard.

## Install

Needs Hyprland 0.55+ (Lua config), Quickshell, PipeWire, `grim`, `uv`, and
either the `claude` CLI (logged in) or an Anthropic API key.

```sh
git clone https://github.com/XArhaanshX/better-cluely ~/Projects/better-cluely
~/Projects/better-cluely/install.sh
```

The installer creates the daemon's environment, downloads the speech model
(~460 MB, NVIDIA Nemotron streaming 0.6B via sherpa-onnx), links `shell/` to
`~/.config/quickshell/wisp`, adds `hypr/wisp.lua` to your Hyprland custom
config, installs the `wispd` user service and starts everything.

Settings: copy `config.example.toml` to `~/.config/wisp/config.toml`.

## How it is built

```
Hyprland ── global shortcuts ──► Quickshell overlay (shell/, QML)
                                     │  newline JSON over $XDG_RUNTIME_DIR/wisp.sock
                                     ▼
                                  wispd (daemon/, Python asyncio)
   parec (mic, sink monitor) ──► sherpa-onnx streaming STT ──► transcript
   grim + Pillow ─────────────► screenshot                    │
                                  Claude Code pool / Anthropic API ◄─┘
```

- `daemon/wispd/audio.py`: PipeWire capture, default-device following,
  speaker detection.
- `daemon/wispd/aec.py`: the echo canceller, a private PipeWire client
  running the `echo-cancel` module in monitor mode.
- `daemon/wispd/stt.py`: one recognizer, both speakers decoded in a batch,
  silence skipped.
- `daemon/wispd/llm/`: Claude Code process pool and Anthropic SDK backend.
- `daemon/wispd/session.py`: transcript, auto-answers, notes, settings.
- `shell/`: the overlay. `services/Daemon.qml` is the socket client.

Tests: `cd daemon && uv run pytest`. Benchmarks are in `daemon/bench/`.

## Limits

- Speech recognition is English only.
- Echo cancellation measures 65–67 dB on a virtual room
  (`daemon/bench/aec_check.py`); real speakers through room air give less,
  typically 20–30 dB. Headphones avoid echo entirely.
- Question detection is rule-based. It covers common interview and meeting
  phrasings, not every way of asking something.
- Answer speed is the model's own time to first token: 0.75–1.1 s for text
  and 1–3.5 s with a screenshot through Claude Code. Auto-answers hide it
  when the other side asks the question.
- In a screen share or recording of the whole screen, the overlay shows as
  a black rectangle: that is how Hyprland's `no_screen_share` works.
