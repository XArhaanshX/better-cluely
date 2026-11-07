import QtQuick
import qs.services

// Shortcut hint: a row of small key caps, e.g. keys: ["❖", "Alt", "↵"].
Row {
    id: root
    property var keys: []
    property color tint: Theme.muted
    spacing: 2

    Repeater {
        model: root.keys
        Rectangle {
            required property string modelData
            implicitWidth: Math.max(16, label.implicitWidth + 8)
            implicitHeight: 17
            radius: 4
            color: Theme.alpha(Theme.text, 0.07)
            border.width: 1
            border.color: Theme.alpha(Theme.text, 0.10)
            Text {
                id: label
                anchors.centerIn: parent
                text: parent.modelData
                color: root.tint
                font.family: Theme.fontMono
                font.pixelSize: 10
            }
        }
    }
}
