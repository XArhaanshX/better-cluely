import QtQuick
import qs.services

// A Material Symbols glyph by name, e.g. "mic", "graphic_eq".
Text {
    id: root
    property string name
    property real size: 18
    property real fill: 0
    property int weight: 500

    text: name
    color: Theme.text
    font.family: Theme.fontIcon
    font.pixelSize: size
    font.variableAxes: ({ "FILL": root.fill, "wght": root.weight, "opsz": 24 })
    horizontalAlignment: Text.AlignHCenter
    verticalAlignment: Text.AlignVCenter
    Behavior on fill {
        NumberAnimation { duration: 160 }
    }
}
