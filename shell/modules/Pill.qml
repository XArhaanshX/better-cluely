import QtQuick
import qs.services
import qs.components

// The always-visible bar: listen, ask, hide, mode and model controls.
Rectangle {
    id: root
    signal askRequested
    signal typeRequested

    implicitWidth: row.implicitWidth + 16
    implicitHeight: 46
    radius: height / 2
    color: Theme.glass
    border.width: 1
    border.color: Theme.glassBorder

    property real now: Date.now() / 1000
    Timer {
        interval: 1000
        repeat: true
        running: Daemon.listening
        triggeredOnStart: true
        onTriggered: root.now = Date.now() / 1000
    }
    function elapsed() {
        const s = Math.max(0, Math.floor(root.now - Daemon.listenStarted));
        const m = Math.floor(s / 60);
        return (m < 10 ? "0" : "") + m + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
    }

    // Drag the bar to move the overlay. The window moves under the pointer,
    // so the offset from the press point is the distance moved each time.
    MouseArea {
        anchors.fill: parent
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        property real pressX
        property real pressY
        onPressed: m => {
            pressX = m.x;
            pressY = m.y;
        }
        onPositionChanged: m => {
            if (pressed)
                Ui.drag(m.x - pressX, m.y - pressY);
        }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 2

        // Mark: a ring that breathes while listening.
        Item {
            width: 30
            height: 32
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                id: ring
                anchors.centerIn: parent
                width: 14
                height: 14
                radius: 7
                color: "transparent"
                border.width: 2.5
                border.color: Daemon.listening ? Theme.liveStrong : Theme.accent
                SequentialAnimation on scale {
                    running: Daemon.listening
                    loops: Animation.Infinite
                    onRunningChanged: if (!running) ring.scale = 1
                    NumberAnimation { to: 1.18; duration: 700; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
                }
            }
            Rectangle {
                anchors.centerIn: parent
                width: 4
                height: 4
                radius: 2
                color: ring.border.color
            }
        }

        PillButton {
            id: listenButton
            anchors.verticalCenter: parent.verticalCenter
            icon: Daemon.listening ? (hovered ? "stop_circle" : "radio_button_checked") : "mic"
            iconFill: Daemon.listening ? 1 : 0
            iconColor: Daemon.listening ? Theme.liveStrong : Theme.text
            label: Daemon.listening ? (hovered ? "Stop" : "Recording " + root.elapsed()) : "Listen"
            keys: hovered || !Daemon.listening ? ["❖", "Alt", "L"] : []
            onClicked: Daemon.toggleListen()
            LevelBars {
                visible: Daemon.listening
                anchors.verticalCenter: parent.verticalCenter
                level: Math.max(Daemon.levelThem, Daemon.levelYou)
                color: Daemon.levelThem >= Daemon.levelYou ? Theme.them : Theme.accent
            }
        }

        Rectangle {
            width: 1
            height: 18
            color: Theme.line
            anchors.verticalCenter: parent.verticalCenter
        }

        PillButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "bolt"
            iconFill: 1
            iconColor: Theme.accent
            label: "Assist"
            keys: ["❖", "Alt", "↵"]
            onClicked: root.askRequested()
        }

        PillButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "edit"
            keys: hovered ? ["❖", "Alt", "/"] : []
            onClicked: root.typeRequested()
        }

        PillButton {
            anchors.verticalCenter: parent.verticalCenter
            label: "Hide"
            labelColor: Theme.muted
            keys: ["❖", "\\"]
            onClicked: Ui.shown = false
        }

        Rectangle {
            width: 1
            height: 18
            color: Theme.line
            anchors.verticalCenter: parent.verticalCenter
        }

        PillButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "tune"
            label: Daemon.modes[Daemon.mode] ?? "General"
            labelColor: Theme.muted
            onClicked: m => Daemon.cycleMode(m.button === Qt.RightButton ? -1 : 1)
        }

        PillButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: Daemon.preset === "fast" ? "speed" : "psychology"
            iconColor: Theme.muted
            label: Daemon.preset === "fast" ? "Fast" : "Smart"
            labelColor: Theme.muted
            onClicked: Daemon.togglePreset()
        }

        // Problems only: daemon down, speech model loading or broken.
        PillButton {
            visible: !Daemon.connected || !Daemon.sttReady
            anchors.verticalCenter: parent.verticalCenter
            icon: !Daemon.connected ? "cloud_off" : (Daemon.sttError ? "error" : "hourglass_top")
            iconColor: !Daemon.connected || Daemon.sttError ? Theme.live : Theme.faint
            label: !Daemon.connected ? "Offline" : (Daemon.sttError ? "No speech" : "Loading")
            labelColor: iconColor
        }

        PillButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "restart_alt"
            iconColor: Theme.faint
            onClicked: Daemon.reset()
        }
    }
}
