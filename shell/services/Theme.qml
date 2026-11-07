pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// Colours follow the wallpaper: illogical-impulse writes the Material You
// palette to colors.json and this file reloads whenever it changes.
// Only the primary and secondary roles are used for accents (the tertiary
// role is often violet), and "live" uses the error role, i.e. red.
Singleton {
    id: root

    property var palette: ({})
    function pick(key, fallback) {
        const v = root.palette[key];
        return v ? v : fallback;
    }
    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a);
    }

    readonly property color base: pick("surface_container_lowest", pick("surface", "#101214"))
    readonly property color raised: pick("surface_container_high", "#26282b")
    readonly property color text: pick("on_surface", "#e3e2e4")
    readonly property color muted: pick("on_surface_variant", "#c2c7cc")
    readonly property color faint: pick("outline", "#8c9196")
    readonly property color line: pick("outline_variant", "#42474c")
    readonly property color accent: pick("primary", "#e0a46b")
    readonly property color onAccent: pick("on_primary", "#2b1600")
    readonly property color accentSoft: pick("primary_container", "#4a2f12")
    readonly property color onAccentSoft: pick("on_primary_container", "#ffdcbd")
    readonly property color them: pick("secondary", "#bcc8d2")
    readonly property color live: pick("error", "#ffb4ab")
    readonly property color liveStrong: "#ff5a4f"

    // The glass: dark enough to read over any window, light enough that
    // the blurred content behind shows through.
    readonly property color glass: alpha(base, 0.80)
    readonly property color glassBorder: alpha(line, 0.85)
    readonly property color hover: alpha(text, 0.08)
    readonly property color press: alpha(text, 0.14)

    readonly property string fontUi: "Space Grotesk"
    readonly property string fontReading: "Readex Pro"
    readonly property string fontMono: "JetBrains Mono NF"
    readonly property string fontIcon: "Material Symbols Rounded"

    readonly property int radius: 16
    readonly property int radiusSmall: 10

    FileView {
        path: Quickshell.env("HOME") + "/.local/state/quickshell/user/generated/colors.json"
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                root.palette = JSON.parse(text());
            } catch (e) {
                console.warn("wisp: could not parse colors.json:", e);
            }
        }
    }
}
