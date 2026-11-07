import QtQuick
import qs.services

// Quick action chip under an answer ("What should I say?", "Recap", ...).
Rectangle {
    id: root
    property string label
    property string icon: ""
    signal clicked

    implicitWidth: row.implicitWidth + 20
    implicitHeight: 28
    radius: 14
    color: mouse.pressed ? Theme.press : (mouse.containsMouse ? Theme.hover : Theme.alpha(Theme.text, 0.04))
    border.width: 1
    border.color: mouse.containsMouse ? Theme.alpha(Theme.accent, 0.55) : Theme.alpha(Theme.text, 0.10)
    Behavior on border.color {
        ColorAnimation { duration: 120 }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 5
        Icon {
            visible: root.icon !== ""
            name: root.icon
            size: 15
            color: Theme.accent
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: root.label
            color: Theme.muted
            font.family: Theme.fontUi
            font.pixelSize: 12
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
