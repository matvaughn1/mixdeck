import QtQuick

// Motor-fader style volume control. value: 0..1 (PipeWire volume, 1 = 0 dB).
// Drag the cap, click the track to jump, wheel or arrow keys to nudge, double-click for 0 dB.
FocusScope {
    id: root
    property real value: 0
    property color accent: "#7dd3fc"
    property string label: "Volume"
    signal moved(real v)

    width: 40
    height: 210
    activeFocusOnTab: true
    readonly property real pad: 10
    readonly property real travel: height - 2 * pad

    Accessible.role: Accessible.Slider
    Accessible.name: label

    function clamp(v) { return Math.max(0, Math.min(1, v)) }

    Keys.onUpPressed: moved(clamp(value + 0.02))
    Keys.onDownPressed: moved(clamp(value - 0.02))
    Keys.onPressed: (e) => {
        if (e.key === Qt.Key_PageUp) { moved(clamp(value + 0.1)); e.accepted = true }
        else if (e.key === Qt.Key_PageDown) { moved(clamp(value - 0.1)); e.accepted = true }
        else if (e.key === Qt.Key_Home) { moved(1); e.accepted = true }
        else if (e.key === Qt.Key_End) { moved(0); e.accepted = true }
    }

    Rectangle {  // slot
        x: 18; y: root.pad; width: 4; height: root.travel; radius: 2
        color: "#0a0c10"; border.color: "#2a303c"
    }
    Rectangle {  // fill
        x: 19; width: 3; radius: 2
        height: root.value * root.travel
        y: root.pad + root.travel - height
        color: root.accent; opacity: 0.55
    }
    Rectangle {  // cap
        id: cap
        x: 2; width: 36; height: 20; radius: 4
        y: root.pad + root.travel - root.value * root.travel - height / 2
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus ? "#7dd3fc" : "#4a5366"
        gradient: Gradient {
            GradientStop { position: 0; color: mouse.pressed ? "#4a5366" : "#3a4252" }
            GradientStop { position: 1; color: "#262c38" }
        }
        Rectangle { anchors.centerIn: parent; width: 24; height: 2; radius: 1; color: "#e6e8ec" }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        preventStealing: true
        property real startY: 0
        property real startV: 0
        onPressed: (m) => {
            root.forceActiveFocus()
            if (m.y < cap.y - 2 || m.y > cap.y + cap.height + 2) {
                var v = root.clamp((root.pad + root.travel - m.y) / root.travel)
                root.moved(v)
                startV = v
            } else {
                startV = root.value
            }
            startY = m.y
        }
        onPositionChanged: (m) => {
            if (pressed)
                root.moved(root.clamp(startV - (m.y - startY) / root.travel))
        }
        onDoubleClicked: root.moved(1)
        onWheel: (w) => root.moved(root.clamp(root.value + (w.angleDelta.y > 0 ? 0.02 : -0.02)))
    }
}
