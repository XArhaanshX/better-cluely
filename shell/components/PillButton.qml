import QtQuick
import qs.services

// Flat button used in the top bar: optional icon, label and shortcut caps.
Item {
    id: root
    property string icon: ""
    property real iconFill: 0
    property color iconColor: Theme.text
    property string label: ""
    property color labelColor: Theme.text
    property var keys: []
    property bool active: false
    property string tooltip: ""
    property alias hovered: mouse.containsMouse
    default property alias extra: row.data
    signal clicked(var mouse)

    implicitWidth: row.implicitWidth + 18
    implicitHeight: 32
    // Hover hints slide open instead of popping in.
    clip: true
    Behavior on implicitWidth {
        NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: mouse.pressed ? Theme.press : (mouse.containsMouse || root.active ? Theme.hover : "transparent")
        Behavior on color {
            ColorAnimation { duration: 120 }
        }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Icon {
            visible: root.icon !== ""
            name: root.icon
            fill: root.iconFill
            color: root.iconColor
            size: 18
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: root.label !== ""
            text: root.label
            color: root.labelColor
            font.family: Theme.fontUi
            font.pixelSize: 13
            font.weight: Font.Medium
            anchors.verticalCenter: parent.verticalCenter
        }
        Keycap {
            visible: root.keys.length > 0
            keys: root.keys
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: m => root.clicked(m)
    }
}
