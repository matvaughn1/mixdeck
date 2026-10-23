import QtQuick

// Stereo peak meter. levels: [left, right], each 0..1 over -60..0 dB.
Row {
    id: root
    property var levels: [0, 0]
    property real meterHeight: 210
    spacing: 2

    Repeater {
        model: 2
        Rectangle {
            width: 5
            height: root.meterHeight
            radius: 2
            clip: true
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#ef4444" }
                GradientStop { position: 0.1; color: "#eab308" }
                GradientStop { position: 0.3; color: "#22c55e" }
                GradientStop { position: 1.0; color: "#16a34a" }
            }
            Rectangle {
                width: parent.width
                height: parent.height * (1 - Math.max(0, Math.min(1, (root.levels && root.levels[index]) || 0)))
                color: "#0d1015"
            }
        }
    }
}
