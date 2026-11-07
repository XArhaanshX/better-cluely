pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Hyprland

// What the shortcuts and the bar buttons do.
Singleton {
    id: root

    // Hide the overlay long enough for the compositor to draw a frame
    // without it, so the screenshot shows what is underneath.
    readonly property int hideFrames: 40
    property string pendingMonitor: ""

    function assist(monitor) {
        Ui.shown = true;
        Ui.cardOpen = true;
        Ui.typing = false;
        root.pendingMonitor = monitor || (Hyprland.focusedMonitor?.name ?? "");
        Ui.capturing = true;
        captureDelay.restart();
        failsafe.restart();
    }

    function type() {
        Ui.shown = true;
        Ui.cardOpen = true;
        Ui.typing = true;
    }

    function toggle() {
        Ui.shown = !Ui.shown;
        if (!Ui.shown)
            Ui.typing = false;
    }

    function dismiss() {
        if (Ui.typing)
            Ui.typing = false;
        else if (Ui.cardOpen)
            Ui.cardOpen = false;
        else
            Ui.shown = false;
    }

    Timer {
        id: captureDelay
        interval: root.hideFrames
        onTriggered: {
            if (!Daemon.ask("assist", root.pendingMonitor))
                Ui.capturing = false;
        }
    }

    // Show the overlay again as soon as the daemon has its picture, or right
    // away if no picture was needed (an answer that was already waiting).
    Timer {
        id: failsafe
        interval: 700
        onTriggered: Ui.capturing = false
    }
    Connections {
        target: Daemon
        function onScreenCaptured() {
            Ui.capturing = false;
        }
        function onAnswerFocused() {
            Ui.capturing = false;
            Ui.cardOpen = true;
        }
        function onAnswerStarted(id, auto) {
            if (!auto)
                return;
            // Answers to questions heard in the call open the card by
            // themselves: the fastest answer is one you don't have to ask for.
            Ui.cardOpen = true;
        }
        function onFailed() {
            Ui.capturing = false;
        }
    }
}
