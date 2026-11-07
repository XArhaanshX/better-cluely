import QtQuick
import qs.services

// Live captions under the bar while listening: the last couple of finished
// lines plus whatever is being said right now, newest at the bottom.
Rectangle {
    id: root

    readonly property var rows: {
        const out = [];
        const n = Daemon.lines.count;
        for (let i = Math.max(0, n - 2); i < n; i++) {
            const l = Daemon.lines.get(i);
            out.push({ source: l.source, text: l.text, live: false });
        }
        if (Daemon.partialThem)
            out.push({ source: "them", text: Daemon.partialThem, live: true });
        if (Daemon.partialYou)
            out.push({ source: "you", text: Daemon.partialYou, live: true });
        return out.slice(-3);
    }

    implicitHeight: col.implicitHeight + 20
    radius: Theme.radius
    color: Theme.glass
    border.width: 1
    border.color: Theme.glassBorder

    Column {
        id: col
        anchors {
            left: parent.left
            right: parent.right
            verticalCenter: parent.verticalCenter
            leftMargin: 14
            rightMargin: 14
        }
        spacing: 4

        Text {
            visible: root.rows.length === 0
            text: Daemon.sttReady ? "Listening…" : "Loading speech model…"
            color: Theme.faint
            font.family: Theme.fontUi
            font.pixelSize: 12
        }

        Repeater {
            model: root.rows
            Row {
                id: captionRow
                required property var modelData
                width: col.width
                spacing: 8
                Text {
                    id: who
                    width: 38
                    text: captionRow.modelData.source === "you" ? "YOU" : "THEM"
                    color: captionRow.modelData.source === "you" ? Theme.accent : Theme.them
                    font.family: Theme.fontMono
                    font.pixelSize: 10
                    font.weight: Font.Bold
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    width: captionRow.width - who.width - captionRow.spacing
                    text: captionRow.modelData.text
                    color: captionRow.modelData.live ? Theme.text : Theme.muted
                    font.family: Theme.fontReading
                    font.pixelSize: 13
                    elide: Text.ElideLeft
                    maximumLineCount: 1
                }
            }
        }
    }
}
