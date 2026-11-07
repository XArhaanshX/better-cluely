-- wisp: shortcuts, layer rules and autostart for Hyprland.
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

-- The overlay is one layer surface with the namespace "wisp".
-- Blur what is behind it (not the wallpaper: ii turns on xray for all
-- layers), keep it out of screen sharing and recordings, and don't
-- animate it in and out.
hl.layer_rule({ match = { namespace = "^wisp$" }, blur = true })
hl.layer_rule({ match = { namespace = "^wisp$" }, xray = false })
hl.layer_rule({ match = { namespace = "^wisp$" }, ignore_alpha = 0.3 })
hl.layer_rule({ match = { namespace = "^wisp$" }, no_anim = true })
hl.layer_rule({ match = { namespace = "^wisp$" }, no_screen_share = true })

-- Start at login. The daemon restarts here rather than at user-session
-- start so it picks up this login's WAYLAND_DISPLAY and Hyprland socket.
hl.on("hyprland.start", function ()
    hl.exec_cmd("systemctl --user restart wispd.service")
    hl.exec_cmd("qs -c wisp")
end)
