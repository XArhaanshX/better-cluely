import QtQuick
import Quickshell
import qs.services
import qs.components

// The answer panel: streaming markdown answer, latency, history, quick
// actions and a question box.
Rectangle {
    id: root
    property string monitor: ""
    readonly property var answer: {
        // Touch the fields that change while streaming so this re-evaluates.
        const i = Daemon.currentIndex;
        if (i < 0)
            return null;
        const a = Daemon.answers.get(i);
        return a ? { id: a.id, kind: a.kind, title: a.title, auto: a.auto, text: a.text, done: a.done,
            cancelled: a.cancelled, error: a.error, first_ms: a.first_ms, waiting: a.waiting,
            viewed: a.viewed, path: a.path } : null;
    }
    readonly property bool thinking: answer !== null && !answer.done && answer.text.length === 0

    function scroll(pages) {
        const target = flick.contentY + pages * flick.height * 0.8;
        flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, target));
    }

    implicitHeight: col.implicitHeight + 24
    radius: Theme.radius
    color: Theme.glass
    border.width: 1
    border.color: Theme.glassBorder

    Connections {
        target: Daemon
        function onAnswerStarted() {
            flick.contentY = 0;
        }
        function onAnswerFocused() {
            flick.contentY = 0;
        }
    }

    Column {
        id: col
        anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            margins: 14
            topMargin: 12
        }
        spacing: 10

        // Header
        Item {
            visible: root.answer !== null
            width: parent.width
            height: 24
            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Icon {
                    name: root.answer?.auto ? "hearing" : (root.answer?.kind === "ask" ? "chat_bubble" : "bolt")
                    fill: 1
                    size: 16
                    color: Theme.accent
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: root.answer?.title ?? ""
                    color: Theme.text
                    font.family: Theme.fontUi
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, 360)
                    anchors.verticalCenter: parent.verticalCenter
                }
                Rectangle {
                    visible: root.answer?.auto ?? false
                    radius: 4
                    color: Theme.alpha(Theme.them, 0.14)
                    implicitWidth: autoLabel.implicitWidth + 10
                    implicitHeight: 17
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        id: autoLabel
                        anchors.centerIn: parent
                        text: "heard"
                        color: Theme.them
                        font.family: Theme.fontMono
                        font.pixelSize: 10
                    }
                }
                Row {
                    visible: (root.answer?.viewed ?? false) && !(root.answer?.waiting ?? false)
                    spacing: 3
                    anchors.verticalCenter: parent.verticalCenter
                    Icon {
                        name: "visibility"
                        size: 13
                        color: Theme.faint
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "Viewed screen"
                        color: Theme.faint
                        font.family: Theme.fontUi
                        font.pixelSize: 11
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                Text {
                    visible: (root.answer?.first_ms ?? -1) > 0
                    text: ((root.answer?.first_ms ?? 0) / 1000).toFixed(2) + " s"
                    color: Theme.faint
                    font.family: Theme.fontMono
                    font.pixelSize: 10
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 0
                PillButton {
                    visible: Daemon.answers.count > 1
                    icon: "chevron_left"
                    iconColor: Daemon.currentIndex > 0 ? Theme.muted : Theme.line
                    implicitHeight: 24
                    onClicked: Daemon.step(-1)
                }
                Text {
                    visible: Daemon.answers.count > 1
                    text: (Daemon.currentIndex + 1) + "/" + Daemon.answers.count
                    color: Theme.faint
                    font.family: Theme.fontMono
                    font.pixelSize: 10
                    anchors.verticalCenter: parent.verticalCenter
                }
                PillButton {
                    visible: Daemon.answers.count > 1
                    icon: "chevron_right"
                    iconColor: Daemon.currentIndex < Daemon.answers.count - 1 ? Theme.muted : Theme.line
                    implicitHeight: 24
                    onClicked: Daemon.step(1)
                }
                PillButton {
                    visible: (root.answer?.path ?? "") !== ""
                    icon: "open_in_new"
                    label: "Open notes"
                    labelColor: Theme.muted
                    iconColor: Theme.muted
                    implicitHeight: 24
                    onClicked: Quickshell.execDetached(["xdg-open", root.answer.path])
                }
                PillButton {
                    icon: copied.running ? "check" : "content_copy"
                    iconColor: Theme.muted
                    implicitHeight: 24
                    onClicked: {
                        Quickshell.execDetached(["wl-copy", "--", root.answer?.text ?? ""]);
                        copied.restart();
                    }
                    Timer {
                        id: copied
                        interval: 1200
                    }
                }
                PillButton {
                    visible: !(root.answer?.done ?? true)
                    icon: "stop"
                    iconColor: Theme.muted
                    implicitHeight: 24
                    onClicked: Daemon.cancel()
                }
                PillButton {
                    icon: "close"
                    iconColor: Theme.muted
                    implicitHeight: 24
                    onClicked: {
                        Ui.cardOpen = false;
                        Ui.typing = false;
                    }
                }
            }
        }

        // Body
        Flickable {
            id: flick
            visible: root.answer !== null
            width: parent.width
            height: Math.min(contentHeight, 380)
            contentHeight: body.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Text {
                id: body
                width: flick.width
                visible: !root.thinking && !(root.answer?.error)
                text: root.answer?.text ?? ""
                textFormat: Text.MarkdownText
                wrapMode: Text.Wrap
                color: Theme.text
                linkColor: Theme.accent
                font.family: Theme.fontReading
                font.pixelSize: 14
                lineHeight: 1.18
                onLinkActivated: link => Qt.openUrlExternally(link)
            }
            Row {
                visible: root.thinking
                spacing: 8
                Repeater {
                    model: 3
                    Rectangle {
                        required property int index
                        width: 6
                        height: 6
                        radius: 3
                        color: Theme.accent
                        anchors.verticalCenter: parent.verticalCenter
                        SequentialAnimation on opacity {
                            running: root.thinking
                            loops: Animation.Infinite
                            PauseAnimation { duration: index * 140 }
                            NumberAnimation { from: 0.25; to: 1; duration: 320 }
                            NumberAnimation { from: 1; to: 0.25; duration: 320 }
                            PauseAnimation { duration: (2 - index) * 140 }
                        }
                    }
                }
                Text {
                    text: root.answer?.waiting ? "Reading your screen" : "Thinking"
                    color: Theme.faint
                    font.family: Theme.fontUi
                    font.pixelSize: 12
                }
            }
            Text {
                visible: !!(root.answer?.error)
                width: flick.width
                text: root.answer?.error ?? ""
                color: Theme.live
                wrapMode: Text.Wrap
                font.family: Theme.fontUi
                font.pixelSize: 13
            }
        }

        // Quick actions
        Flow {
            width: parent.width
            spacing: 6
            Repeater {
                model: [
                    { key: "assist", icon: "bolt" },
                    { key: "say", icon: "record_voice_over" },
                    { key: "followup", icon: "help" },
                    { key: "recap", icon: "summarize" },
                    { key: "factcheck", icon: "fact_check" },
                    { key: "explain", icon: "lightbulb" },
                    { key: "notes", icon: "description" }
                ]
                Chip {
                    required property var modelData
                    label: Daemon.actions[modelData.key] ?? modelData.key
                    icon: modelData.icon
                    onClicked: {
                        if (modelData.key === "notes")
                            Actions.runBlind("notes");
                        else
                            Actions.run(modelData.key, "", root.monitor);
                    }
                }
            }
        }

        // Question box
        Rectangle {
            width: parent.width
            height: 38
            radius: Theme.radiusSmall
            color: Theme.alpha(Theme.text, input.activeFocus ? 0.08 : 0.04)
            border.width: 1
            border.color: input.activeFocus ? Theme.alpha(Theme.accent, 0.6) : Theme.alpha(Theme.text, 0.08)

            TextInput {
                id: input
                anchors {
                    left: parent.left
                    right: sendHint.left
                    verticalCenter: parent.verticalCenter
                    leftMargin: 12
                    rightMargin: 8
                }
                color: Theme.text
                selectionColor: Theme.alpha(Theme.accent, 0.4)
                font.family: Theme.fontReading
                font.pixelSize: 13
                clip: true
                Text {
                    visible: input.text.length === 0
                    text: "Ask about your screen or conversation, or ❖ Alt ↵ for Assist"
                    color: Theme.faint
                    font: input.font
                    anchors.verticalCenter: parent.verticalCenter
                }
                Keys.onReturnPressed: {
                    const q = text.trim();
                    text = "";
                    Ui.typing = false;
                    if (q.length > 0)
                        Actions.run("", q, root.monitor);
                }
                Keys.onEscapePressed: {
                    text = "";
                    Ui.typing = false;
                }
                onActiveFocusChanged: if (activeFocus) Ui.typing = true
            }
            Keycap {
                id: sendHint
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                keys: Ui.typing ? ["↵"] : ["❖", "Alt", "/"]
            }
            Connections {
                target: Ui
                function onTypingChanged() {
                    if (Ui.typing)
                        input.forceActiveFocus();
                    else
                        input.focus = false;
                }
            }
        }
    }
}
