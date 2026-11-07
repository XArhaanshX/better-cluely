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
    visible: Ui.shown && !Ui.capturing
    color: "transparent"
    exclusiveZone: 0
    anchors {
        top: true
        left: true
    }
    implicitWidth: 760
    implicitHeight: content.implicitHeight + 24
    margins {
        top: 6 + Ui.offsetY
        left: Math.max(0, Math.min(screen.width - implicitWidth, Math.round((screen.width - implicitWidth) / 2) + Ui.offsetX))
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

        Pill {
            id: pill
            anchors.horizontalCenter: parent.horizontalCenter
            onAskRequested: Actions.assist(win.monitorName)
            onTypeRequested: Actions.type()
        }

        Captions {
            id: captions
            width: parent.width
            visible: Daemon.listening && Ui.captionsOpen
        }

        AnswerCard {
            id: card
            width: parent.width
            monitor: win.monitorName
            visible: Ui.cardOpen && (Daemon.currentIndex >= 0 || Ui.typing)
        }
    }
}
