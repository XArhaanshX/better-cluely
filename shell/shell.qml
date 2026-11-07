//@ pragma Env QS_NO_RELOAD_POPUP=1
//@ pragma Env QT_QUICK_FLICKABLE_WHEEL_DECELERATION=10000

import QtQuick
import Quickshell
import Quickshell.Hyprland
import qs.services
import qs.modules

// wisp: a meeting assistant overlay. Run with `qs -c wisp`.
// The daemon (wispd) does the listening, transcription and answering;
// this is only the UI. Shortcuts are bound in hypr/wisp.lua.
ShellRoot {
    Overlay {}

    component Shortcut: GlobalShortcut {
        appid: "wisp"
    }

    Shortcut {
        name: "toggle"
        description: "Show or hide wisp"
        onPressed: Actions.toggle()
    }
    // Deterministic forms for the `wisp` command line, which cannot know
    // the current state and so cannot use toggle.
    Shortcut {
        name: "show"
        description: "Show wisp"
        onPressed: Ui.shown = true
    }
    Shortcut {
        name: "hide"
        description: "Hide wisp"
        onPressed: {
            Ui.typing = false;
            Ui.shown = false;
        }
    }
    Shortcut {
        name: "assist"
        description: "Ask about the screen and the conversation"
        onPressed: Actions.assist()
    }
    Shortcut {
        name: "listen"
        description: "Start or stop listening"
        onPressed: Daemon.toggleListen()
    }
    Shortcut {
        name: "type"
        description: "Type a question"
        onPressed: Actions.type()
    }
    Shortcut {
        name: "dismiss"
        description: "Close the question box, then the answer, then the overlay"
        onPressed: Actions.dismiss()
    }
    Shortcut {
        name: "reset"
        description: "Start a new session"
        onPressed: Daemon.reset()
    }
    Shortcut {
        name: "prev"
        description: "Previous answer"
        onPressed: Daemon.step(-1)
    }
    Shortcut {
        name: "next"
        description: "Next answer"
        onPressed: Daemon.step(1)
    }
    Shortcut {
        name: "moveLeft"
        onPressed: Ui.move(-1, 0)
    }
    Shortcut {
        name: "moveRight"
        onPressed: Ui.move(1, 0)
    }
    Shortcut {
        name: "moveUp"
        onPressed: Ui.move(0, -1)
    }
    Shortcut {
        name: "moveDown"
        onPressed: Ui.move(0, 1)
    }
}
