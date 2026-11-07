# wisp

A Cluely-style AI meeting assistant built natively for Hyprland on Linux.

wisp is a translucent overlay that sits at the top of the screen. It listens to
the meeting (your mic and system audio), transcribes both sides live, and
answers on demand from what was said and what is on screen.

It is a ground-up rewrite of the idea behind
[Freely](https://github.com/lambdaflows/freely) / Pluely, aimed at Wayland:

- **Quickshell UI** instead of a Tauri webview: no WebKit process, instant
  show/hide, colours taken from the wallpaper's Material You palette.
- **Real Hyprland integration**: global shortcuts through the compositor, a
  layer surface that never steals focus, and layer rules for screen-share
  hiding.
- **Local streaming speech-to-text** (sherpa-onnx, NVIDIA Nemotron streaming
  0.6B) on the CPU.
- **Claude Code login by default**, with an Anthropic API key as an option.

Status: work in progress.
