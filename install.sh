#!/usr/bin/env bash
# Install wisp for the current user on Hyprland + Quickshell.
#
#   ./install.sh            set everything up and start it
#   ./install.sh --no-start set up only
#
# What it does:
#   1. creates the daemon's virtualenv (uv)
#   2. downloads the speech model (~460 MB) if it is missing
#   3. links shell/ to ~/.config/quickshell/wisp
#   4. links hypr/wisp.lua into ~/.config/hypr/custom and loads it
#   5. installs the wispd systemd user unit
#   6. starts the daemon and the overlay
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/wisp"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/wisp"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
MODEL="sherpa-onnx-nemotron-speech-streaming-en-0.6b-160ms-int8-2026-04-25"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$MODEL.tar.bz2"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "missing: $1 ($2)" >&2; exit 1; }; }

need uv "https://docs.astral.sh/uv/"
need qs "quickshell"
need parec "pipewire-pulse / libpulse"
need grim "grim"
need hyprctl "Hyprland"
command -v claude >/dev/null || echo "note: 'claude' not found; the Claude Code backend needs it (or use backend = \"api\")"

say "Daemon environment"
(cd "$REPO/daemon" && uv sync --python 3.13 --quiet)

if [[ ! -f "$DATA/models/$MODEL/encoder.int8.onnx" ]]; then
    say "Downloading speech model (~460 MB)"
    mkdir -p "$DATA/models"
    curl -4 -fL --progress-bar "$MODEL_URL" | tar xj -C "$DATA/models"
fi

say "Quickshell config -> $CONF/quickshell/wisp"
mkdir -p "$CONF/quickshell" "$STATE"
ln -sfn "$REPO/shell" "$CONF/quickshell/wisp"

say "Hyprland shortcuts and layer rules"
mkdir -p "$CONF/hypr/custom"
ln -sf "$REPO/hypr/wisp.lua" "$CONF/hypr/custom/wisp.lua"
LOADER='if is_file_exists(HOME .. "/.config/hypr/custom/wisp.lua") then require("custom.wisp") end'
KEYBINDS="$CONF/hypr/custom/keybinds.lua"
touch "$KEYBINDS"
grep -qF 'require("custom.wisp")' "$KEYBINDS" || printf '\n-- wisp overlay\n%s\n' "$LOADER" >> "$KEYBINDS"

say "wisp command -> ~/.local/bin/wisp"
mkdir -p "$HOME/.local/bin"
chmod +x "$REPO/bin/wisp"
ln -sf "$REPO/bin/wisp" "$HOME/.local/bin/wisp"

say "systemd user unit"
mkdir -p "$CONF/systemd/user"
sed "s|@REPO@|$REPO|g" "$REPO/systemd/wispd.service.in" > "$CONF/systemd/user/wispd.service"
systemctl --user daemon-reload

if [[ "${1:-}" != "--no-start" ]]; then
    say "Starting"
    hyprctl reload >/dev/null
    systemctl --user restart wispd.service
    pkill -f "qs -c [w]isp" || true
    setsid -f qs -c wisp >/dev/null 2>&1
    echo "wisp is running. Super+Backslash shows or hides it; Super+Alt+L listens; Super+Alt+Enter asks."
fi
