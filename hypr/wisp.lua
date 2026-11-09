-- wisp: shortcuts and layer rules for Hyprland.
-- install.sh links this to ~/.config/hypr/custom/wisp.lua and loads it from
-- custom/keybinds.lua. All shortcuts are Super+Alt+key except show/hide,
-- so none of them steal a key that apps use (Ctrl+Enter, Ctrl+\ ...).

local function wisp(key, action, description)
    hl.bind(key, hl.dsp.global("wisp:" .. action), { description = description and ("wisp: " .. description) or nil })
end

wisp("SUPER + Backslash",       "toggle",  "Show or hide")
wisp("SUPER + ALT + Return",    "assist",  "Ask about the screen and the conversation")
wisp("SUPER + ALT + L",         "listen",  "Start or stop listening")
wisp("SUPER + ALT + Slash",     "type",    "Type a question")
wisp("SUPER + ALT + Escape",    "dismiss", "Close the answer or the overlay")
wisp("SUPER + ALT + BackSpace", "reset",   "New session")
wisp("SUPER + ALT + Comma",     "prev",    "Previous answer")
wisp("SUPER + ALT + Period",    "next",    "Next answer")
for _, dir in ipairs({ "Left", "Right", "Up", "Down" }) do
    wisp("SUPER + ALT + " .. dir, "move" .. dir)
end

-- The overlay is exactly one layer surface, namespace "wisp" (set in
-- shell/modules/Overlay.qml; the two must match). There are no popups,
-- tooltips or child windows, so this one match covers every pixel wisp
-- draws. `hyprctl layers` shows it as namespace "wisp" on the Overlay level.
--
-- blur/xray/ignore_alpha: glass look over the window behind it, not the
-- wallpaper (ii turns xray on for all layers, so it is turned back off).
-- no_anim: appear and vanish in one frame.
-- no_screen_share: in a full-screen share or recording the compositor
-- paints this region solid black. Viewers see a black bar, not the
-- overlay. Share a single window or tab instead and it is absent entirely.
local WISP = { namespace = "^wisp$" }
hl.layer_rule({ match = WISP, blur = true })
hl.layer_rule({ match = WISP, xray = false })
hl.layer_rule({ match = WISP, ignore_alpha = 0.3 })
hl.layer_rule({ match = WISP, no_anim = true })
hl.layer_rule({ match = WISP, no_screen_share = true })

-- Nothing starts at login. The `wisp` command starts the daemon and the
-- overlay when you ask for them; until then these shortcuts do nothing.
