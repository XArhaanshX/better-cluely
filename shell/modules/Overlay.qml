import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.services

// The overlay window: a layer surface on the Overlay layer, so it floats
// above every window, never appears in the taskbar, dock or alt-tab, and
// takes no keyboard focus unless you are typing a question. Clicks outside
// the visible panels go straight through to the window underneath.
PanelWindow {
    id: win

    readonly property string monitorName: Hyprland.focusedMonitor?.name ?? ""
    property alias pill: pill

    screen: Quickshell.screens.find(s => s.name === monitorName) ?? Quickshell.screens[0]

    // 0 hidden .. 1 shown. Showing eases in over 220 ms (fade, slight drop
    // and scale); hiding takes 130 ms. Hiding for a screenshot
    // (Ui.capturing) is deliberately instant: any fade there would delay
    // Assist.
    //
    // Two things make a naive fade pop in instead:
    // - hiding unmaps the layer surface, and mapping it again takes the
    //   compositor a few frames, so a fade started on the show command is
    //   half over before anything is on screen; it waits for the first
    //   presented frame (frameSwapped) instead;
    // - Qt's animation clock advances in fixed per-frame steps and jumps
    //   ahead on the first frames after a map. This fade is computed from
    //   wall-clock time, so its first visible frame is near 0.
    property real reveal: 0
    property bool revealPending: Ui.shown
    visible: (Ui.shown || reveal > 0) && !Ui.capturing

    property real fadeFrom: 0
    property real fadeTo: 0
    property real fadeStart: 0
    property int fadeMs: 220

    function fade(to, ms) {
        fadeFrom = reveal;
        fadeTo = to;
        fadeMs = ms;
        fadeStart = Date.now();
        fadeTick.restart();
    }
    function startReveal() {
        revealPending = false;
        revealFailsafe.stop();
        fade(1, 220);
    }
    Timer {
        id: fadeTick
        interval: 8
        repeat: true
        onTriggered: {
            const t = Math.min(1, (Date.now() - win.fadeStart) / win.fadeMs);
            // Ease out when appearing, ease in when leaving.
            const e = win.fadeTo > win.fadeFrom ? 1 - Math.pow(1 - t, 3) : t * t * t;
            win.reveal = win.fadeFrom + (win.fadeTo - win.fadeFrom) * e;
            if (t >= 1)
                stop();
        }
    }
    Connections {
        target: Ui
        function onShownChanged() {
            if (Ui.shown) {
                if (win.reveal > 0) {
                    win.startReveal(); // still on screen: turn around from here
                } else {
                    win.revealPending = true;
                    revealFailsafe.restart();
                }
            } else {
                win.revealPending = false;
                win.fade(0, 130);
            }
        }
    }
    Connections {
        target: content.Window.window
        function onFrameSwapped() {
            if (win.revealPending)
                win.startReveal();
        }
    }
    // In case no frame is reported, never leave it invisible.
    Timer {
        id: revealFailsafe
        interval: 400
        running: win.revealPending
        onTriggered: if (win.revealPending) win.startReveal()
    }

    // Keyboard moves glide; dragging follows the pointer exactly.
    property real offX: Ui.offsetX
    property real offY: Ui.offsetY
    Behavior on offX {
        enabled: !Ui.dragging
        NumberAnimation { duration: 200; easing.type: Easing.OutCubic }
    }
    Behavior on offY {
        enabled: !Ui.dragging
        NumberAnimation { duration: 200; easing.type: Easing.OutCubic }
    }
    color: "transparent"
    exclusiveZone: 0
    anchors {
        top: true
        left: true
    }
    implicitWidth: 760
    implicitHeight: content.implicitHeight + 24
    margins {
        top: 6 + Math.round(offY)
        left: Math.max(0, Math.min(screen.width - implicitWidth, Math.round((screen.width - implicitWidth) / 2 + offX)))
    }

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "wisp"
    WlrLayershell.keyboardFocus: Ui.typing ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    mask: Region {
        item: pill
        Region {
            item: captions.visible ? captions : null
        }
        Region {
            item: card.visible ? card : null
        }
    }

    Column {
        id: content
        anchors.horizontalCenter: parent.horizontalCenter
        width: 680
        spacing: 8
        opacity: win.reveal
        transform: [
            Scale {
                origin.x: content.width / 2
                origin.y: 0
                xScale: 0.97 + 0.03 * win.reveal
                yScale: 0.97 + 0.03 * win.reveal
            },
            Translate {
                y: -8 * (1 - win.reveal)
            }
        ]

        Pill {
            id: pill
            anchors.horizontalCenter: parent.horizontalCenter
            onAskRequested: Actions.assist(win.monitorName)
            onTypeRequested: Actions.type()
        }

        Captions {
            id: captions
            width: parent.width
            open: Daemon.listening && Ui.captionsOpen
        }

        AnswerCard {
            id: card
            width: parent.width
            monitor: win.monitorName
            open: Ui.cardOpen && (Daemon.currentIndex >= 0 || Ui.typing)
        }
    }
}
