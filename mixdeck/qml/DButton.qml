import QtQuick
import QtQuick.Controls.Basic

// Small hardware-style toggle/button. variant: "route" | "mute" | "solo" | "plain"
Button {
    id: b
    property bool on: false
    property string variant: "route"
    implicitHeight: 28
    implicitWidth: 32
    padding: 0
    checkable: false
    focusPolicy: Qt.StrongFocus
    Accessible.checkable: variant !== "plain"
    Accessible.checked: on

    readonly property var colors: ({
        route: ["#0e3a4a", "#38bdf8", "#e0f2fe"],
        mute: ["#4a1416", "#f87171", "#fee2e2"],
        solo: ["#45320b", "#fbbf24", "#fef3c7"],
        plain: ["#1f242e", "#2c3340", "#c3cad6"]
    })

    contentItem: Text {
        text: b.text
        font.family: "Fira Sans"
        font.pixelSize: 11
        font.weight: Font.DemiBold
        font.letterSpacing: 0.4
        color: b.on ? b.colors[b.variant][2] : "#c3cad6"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 6
        color: b.on ? b.colors[b.variant][0] : (b.down ? "#2c3340" : b.hovered ? "#262c38" : "#1f242e")
        border.width: b.visualFocus ? 2 : 1
        border.color: b.visualFocus ? "#7dd3fc" : (b.on ? b.colors[b.variant][1] : "#2c3340")
    }
}
