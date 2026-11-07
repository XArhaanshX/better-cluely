pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// Client for wispd over its Unix socket (newline-delimited JSON).
// Holds the live state the overlay draws: status, transcript, answers.
Singleton {
    id: root

    readonly property string socketPath: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/wisp.sock"
    readonly property bool connected: connectedNow

    property var status: ({})
    readonly property bool listening: status.listening ?? false
    readonly property real listenStarted: status.listen_started ?? 0
    readonly property bool sttReady: status.stt_ready ?? false
    readonly property string sttError: status.stt_error ?? ""
    readonly property var config: status.config ?? ({})
    readonly property var backend: status.backend ?? ({})
    readonly property var modes: status.modes ?? ({})
    readonly property var actions: status.actions ?? ({})
    readonly property string mode: config.mode ?? "general"
    readonly property string preset: config.resolved_preset ?? "fast"
    readonly property bool autoAnswer: config.auto_answer ?? true

    property real levelYou: 0
    property real levelThem: 0
    property string partialYou: ""
    property string partialThem: ""
    property real t0: 0

    // {source, text, t}
    property ListModel lines: ListModel {}
    // {id, kind, title, auto, text, done, cancelled, error, first_ms, total_ms, capture_ms, viewed, waiting, path}
    property ListModel answers: ListModel {}
    property string currentId: ""
    readonly property int currentIndex: {
        answers.count; // re-evaluate when the model changes
        return indexOf(currentId);
    }

    property real lastPong: Date.now()

    signal answerStarted(string id, bool auto)
    signal answerFocused(string id)
    signal screenCaptured(string id)
    signal failed(string message)

    function send(obj) {
        if (!sock || !sock.connected)
            return false;
        sock.write(JSON.stringify(obj) + "\n");
        sock.flush();
        return true;
    }

    function ask(action, monitor) {
        return send({ cmd: "ask", action: action || "assist", screenshot: true, monitor: monitor || null });
    }
    function askText(text, monitor) {
        return send({ cmd: "ask", text: text, screenshot: true, monitor: monitor || null });
    }
    function toggleListen() {
        return send({ cmd: "listen", on: !listening });
    }
    function cancel() {
        return send({ cmd: "cancel" });
    }
    function reset() {
        return send({ cmd: "reset" });
    }
    function setOption(key, value) {
        return send({ cmd: "set", key: key, value: value });
    }
    function cycleMode(step) {
        const keys = Object.keys(modes);
        if (keys.length === 0)
            return;
        const i = keys.indexOf(mode);
        setOption("mode", keys[(i + (step || 1) + keys.length) % keys.length]);
    }
    function togglePreset() {
        setOption("preset", preset === "fast" ? "smart" : "fast");
    }

    function indexOf(id) {
        for (let i = 0; i < answers.count; i++) {
            if (answers.get(i).id === id)
                return i;
        }
        return -1;
    }
    function current() {
        const i = currentIndex;
        return i >= 0 ? answers.get(i) : null;
    }
    function step(delta) {
        const i = currentIndex;
        const j = Math.max(0, Math.min(answers.count - 1, i + delta));
        if (j >= 0 && j < answers.count)
            currentId = answers.get(j).id;
    }

    function normalize(a) {
        return {
            id: a.id,
            kind: a.kind ?? "",
            title: a.title ?? "",
            auto: a.auto ?? false,
            text: a.text ?? "",
            done: a.done ?? false,
            cancelled: a.cancelled ?? false,
            error: a.error ?? "",
            first_ms: a.first_ms ?? -1,
            total_ms: a.total_ms ?? -1,
            capture_ms: a.capture_ms ?? -1,
            viewed: a.screenshot ?? false,
            waiting: (a.screenshot ?? false) && !(a.done ?? false),
            path: a.path ?? ""
        };
    }

    function handle(ev) {
        switch (ev.ev) {
        case "snapshot":
            root.status = ev.status;
            root.t0 = ev.t0;
            lines.clear();
            for (const l of ev.lines)
                lines.append(l);
            partialYou = ev.partial?.you ?? "";
            partialThem = ev.partial?.them ?? "";
            answers.clear();
            for (const a of ev.answers)
                answers.append(normalize(a));
            currentId = answers.count > 0 ? answers.get(answers.count - 1).id : "";
            break;
        case "status":
            delete ev.ev;
            root.status = ev;
            break;
        case "level":
            levelYou = ev.you;
            levelThem = ev.them;
            break;
        case "partial":
            if (ev.source === "you")
                partialYou = ev.text;
            else
                partialThem = ev.text;
            break;
        case "line":
            lines.append({ source: ev.source, text: ev.text, t: ev.t });
            if (lines.count > 400)
                lines.remove(0, lines.count - 400);
            if (ev.source === "you")
                partialYou = "";
            else
                partialThem = "";
            break;
        case "answer.start":
            answers.append(normalize(ev));
            if (answers.count > 50)
                answers.remove(0, answers.count - 50);
            currentId = ev.id;
            answerStarted(ev.id, ev.auto ?? false);
            break;
        case "answer.captured":
            {
                const i = indexOf(ev.id);
                if (i >= 0) {
                    answers.setProperty(i, "waiting", false);
                    answers.setProperty(i, "capture_ms", ev.capture_ms ?? -1);
                }
                screenCaptured(ev.id);
                break;
            }
        case "answer.delta":
            {
                const i = indexOf(ev.id);
                if (i >= 0)
                    answers.setProperty(i, "text", answers.get(i).text + ev.text);
                break;
            }
        case "answer.done":
            {
                const i = indexOf(ev.id);
                if (i < 0)
                    break;
                const a = answers.get(i);
                if (ev.cancelled && a.auto && a.text.length === 0) {
                    // An auto answer replaced by a merged question: drop it.
                    answers.remove(i);
                    break;
                }
                answers.setProperty(i, "done", true);
                answers.setProperty(i, "waiting", false);
                answers.setProperty(i, "cancelled", ev.cancelled ?? false);
                answers.setProperty(i, "error", ev.error ?? "");
                answers.setProperty(i, "first_ms", ev.first_ms ?? -1);
                answers.setProperty(i, "total_ms", ev.total_ms ?? -1);
                answers.setProperty(i, "path", ev.path ?? "");
                break;
            }
        case "answer.focus":
            currentId = ev.id;
            answerFocused(ev.id);
            break;
        case "pong":
            root.lastPong = Date.now();
            break;
        case "error":
            console.warn("wisp:", ev.message);
            failed(ev.message);
            break;
        }
    }

    // A fresh Socket per connection attempt. Toggling `connected` on one
    // Socket did not reconnect after the daemon restarted (the target state
    // stayed "connected" while nothing was), so asks silently went nowhere.
    property var sock: null
    readonly property bool connectedNow: sock?.connected ?? false

    function reconnect() {
        if (sock)
            sock.destroy();
        lastPong = Date.now();
        sock = socketComponent.createObject(root);
    }

    Component.onCompleted: reconnect()

    Component {
        id: socketComponent
        Socket {
            path: root.socketPath
            connected: true
            onConnectedChanged: {
                if (connected) {
                    root.lastPong = Date.now();
                    root.send({ cmd: "hello" });
                }
            }
            onError: e => retry.restart()
            parser: SplitParser {
                onRead: data => {
                    try {
                        root.handle(JSON.parse(data));
                    } catch (e) {
                        console.warn("wisp: bad event:", e, data.slice(0, 200));
                    }
                }
            }
        }
    }

    // Daemon down or restarting: try again every second.
    Timer {
        id: retry
        interval: 1000
        onTriggered: root.reconnect()
    }

    // Catch a dead connection the socket did not report: ping, and start
    // over when the pongs stop.
    Timer {
        interval: 4000
        repeat: true
        running: true
        onTriggered: {
            if (!root.connectedNow) {
                if (!retry.running)
                    root.reconnect();
                return;
            }
            if (Date.now() - root.lastPong > 9000) {
                console.warn("wisp: daemon stopped answering, reconnecting");
                root.reconnect();
                return;
            }
            root.send({ cmd: "ping" });
        }
    }
}
