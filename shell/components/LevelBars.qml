import QtQuick
import qs.services

// Three-bar audio meter. `level` is RMS (0..~0.3); shown on a log scale.
Row {
    id: root
    property real level: 0
    property color color: Theme.text
    readonly property real norm: Math.max(0, Math.min(1, (20 * Math.log(Math.max(level, 1e-5)) / Math.LN10 + 60) / 45))
    spacing: 2

    Repeater {
        model: [0.55, 1.0, 0.75]
        Rectangle {
            required property real modelData
            width: 3
            radius: 1.5
            anchors.verticalCenter: parent.verticalCenter
            height: 4 + 10 * Math.min(1, root.norm * modelData * 1.3)
            color: root.color
            opacity: 0.45 + 0.55 * root.norm
            Behavior on height {
                NumberAnimation { duration: 80 }
            }
        }
    }
}
