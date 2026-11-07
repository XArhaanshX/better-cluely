pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// Overlay state that only the UI cares about. Position is saved to disk.
Singleton {
    id: root

    property bool shown: true
    // Hidden for a moment while the daemon takes a screenshot, so the
    // overlay is not in the picture.
    property bool capturing: false
    property bool cardOpen: false
    property bool typing: false
    property bool captionsOpen: true

    readonly property int moveStep: 48
    property alias offsetX: saved.offsetX
    property alias offsetY: saved.offsetY

    function move(dx, dy) {
        saved.offsetX += dx * moveStep;
        saved.offsetY = Math.max(0, saved.offsetY + dy * moveStep);
    }

    FileView {
        id: uiFile
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/wisp/ui.json"
        onAdapterUpdated: writeTimer.restart()
        onLoadFailed: error => {
            if (error == FileViewError.FileNotFound)
                writeTimer.restart();
        }
        adapter: JsonAdapter {
            id: saved
            property int offsetX: 0
            property int offsetY: 0
        }
    }

    Timer {
        id: writeTimer
        interval: 400
        onTriggered: uiFile.writeAdapter()
    }
}
