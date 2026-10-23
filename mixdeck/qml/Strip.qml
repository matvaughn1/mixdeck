import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// One channel strip. Every row has a fixed height so strips line up across sections.
Rectangle {
    id: strip
    // model roles
    required property string sid
    required property string kind
    required property string kindLabel
    required property string accent
    required property string name
    required property string device
    required property real vol
    required property string db
    required property bool mute
    required property bool solo
    required property bool hasSolo
    required property real pan
    required property bool hasPan
    required property var routes
    required property bool isApp
    required property string target
    required property bool isOut
    required property string bus
    required property string xtTag
    required property bool missing
    required property bool isDefault
    required property bool mono
    required property bool hasMono
    required property string colorName
    required property int index
    property string section: ""
    property int count: 1
    readonly property real step: width + 8
    signal dragTo(int from, int to)   // to = -1 when the drag ends
    required property string channel
    required property string channelText
    required property var channelOptions

    width: 116
    height: col.implicitHeight + 20
    radius: 10
    color: "#181c24"
    border.color: "#252b37"
    opacity: dragger.active ? 0.85 : missing ? 0.55 : 1
    z: dragger.active ? 10 : 0
    transform: Translate { id: shift }

    function dropIndex() {
        return Math.max(0, Math.min(count - 1, index + Math.round(shift.x / step)))
    }
    function moveBy(n) {
        var to = Math.max(0, Math.min(count - 1, index + n))
        if (to !== index) backend.moveStrip(section, index, to)
    }

    readonly property var ticks: [0, -6, -12, -24, -48]

    ColumnLayout {
        id: col
        x: 10; y: 10
        width: parent.width - 20
        spacing: 10

        Rectangle { Layout.fillWidth: true; height: 4; radius: 2; color: strip.accent }

        // name block
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            Column {
                width: parent.width
                spacing: 3
                RowLayout {
                    width: parent.width
                    Text {
                        text: strip.kindLabel.toUpperCase()
                        color: "#a3acbb"; font.family: "Fira Sans"; font.pixelSize: 10
                        font.weight: Font.DemiBold; font.letterSpacing: 0.8
                        Layout.fillWidth: true; elide: Text.ElideRight
                    }
                    Text {
                        text: strip.xtTag ? "XT " + strip.xtTag : ""
                        color: "#c3cad6"; font.family: "Noto Sans Mono"; font.pixelSize: 10
                    }
                }
                Text {
                    width: parent.width
                    text: strip.name
                    color: "#e6e8ec"; font.family: "Fira Sans"; font.pixelSize: 14; font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: strip.isDefault ? "Default for apps" : strip.device
                    color: strip.missing ? "#fca5a5" : "#a3acbb"
                    font.family: "Fira Sans"; font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                onClicked: menu.popup()
            }
            HoverHandler { cursorShape: dragger.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor }
            DragHandler {
                id: dragger
                target: null
                yAxis.enabled: false
                acceptedButtons: Qt.LeftButton
                onTranslationChanged: {
                    shift.x = translation.x
                    strip.dragTo(strip.index, strip.dropIndex())
                }
                onActiveChanged: {
                    if (!active) {
                        var to = strip.dropIndex()
                        shift.x = 0
                        strip.dragTo(strip.index, -1)
                        if (to !== strip.index) backend.moveStrip(strip.section, strip.index, to)
                    }
                }
            }
        }

        // routing / target / bus row
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 50

            GridLayout {
                visible: strip.routes.length > 0
                anchors.bottom: parent.bottom
                width: parent.width
                columns: 3; columnSpacing: 4; rowSpacing: 4
                Repeater {
                    model: strip.routes
                    DButton {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: strip.routes.length > 3 ? 23 : 28
                        text: modelData.bus
                        on: modelData.on
                        Accessible.name: "Send " + strip.name + " to " + modelData.bus
                        onClicked: backend.toggleRoute(strip.sid, modelData.bus)
                    }
                }
            }

            Column {
                visible: strip.isApp
                anchors.bottom: parent.bottom
                width: parent.width
                spacing: 4
                Text { text: "SEND TO"; color: "#a3acbb"; font.family: "Fira Sans"; font.pixelSize: 10; font.letterSpacing: 0.6 }
                DButton {
                    id: targetBtn
                    width: parent.width
                    variant: "plain"
                    text: {
                        for (var i = 0; i < backend.targets.length; i++)
                            if (backend.targets[i].id === strip.target) return backend.targets[i].name + "  ▾"
                        return "Choose  ▾"
                    }
                    Accessible.name: "Send " + strip.name + " to"
                    onClicked: targetMenu.popup(targetBtn, 0, targetBtn.height)
                    Menu {
                        id: targetMenu
                        Repeater {
                            model: backend.targets
                            MenuItem {
                                required property var modelData
                                text: modelData.name
                                checkable: true
                                checked: modelData.id === strip.target
                                onTriggered: backend.setTarget(strip.sid, modelData.id)
                            }
                        }
                    }
                }
            }

            Rectangle {
                visible: strip.isOut
                anchors.bottom: parent.bottom
                width: parent.width; height: 28; radius: 6
                color: "transparent"
                border.color: "#2c3340"
                Text {
                    anchors.centerIn: parent
                    text: strip.bus
                    color: strip.accent; font.family: "Noto Sans Mono"; font.pixelSize: 12; font.weight: Font.DemiBold
                }
            }
        }

        // meter + fader
        Row {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredHeight: 210
            spacing: 6
            Item {
                width: 22; height: 210
                Repeater {
                    model: strip.ticks
                    Text {
                        required property var modelData
                        anchors.right: parent.right
                        y: 10 + (1 - Math.pow(10, modelData / 60)) * 190 - height / 2
                        text: modelData
                        color: "#8b94a5"; font.family: "Noto Sans Mono"; font.pixelSize: 9
                    }
                }
            }
            Meter {
                meterHeight: 210
                levels: backend.levels[strip.sid] || [0, 0]
            }
            Fader {
                value: Math.min(1, strip.vol)
                accent: strip.accent
                label: strip.name + " volume"
                onMoved: (v) => backend.setVolume(strip.sid, v)
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: 16
            horizontalAlignment: Text.AlignHCenter
            text: strip.db
            color: "#e6e8ec"; font.family: "Noto Sans Mono"; font.pixelSize: 12; font.weight: Font.DemiBold
        }

        // pan
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            Column {
                visible: strip.hasPan
                width: parent.width
                spacing: 2
                RowLayout {
                    width: parent.width
                    Text { text: "PAN"; color: "#a3acbb"; font.family: "Fira Sans"; font.pixelSize: 10; font.letterSpacing: 0.6; Layout.fillWidth: true }
                    Text {
                        text: Math.abs(strip.pan) < 0.01 ? "C" : (strip.pan < 0 ? "L" : "R") + Math.round(Math.abs(strip.pan) * 100)
                        color: "#a3acbb"; font.family: "Noto Sans Mono"; font.pixelSize: 10
                    }
                }
                Slider {
                    id: panSlider
                    width: parent.width
                    height: 22
                    from: -1; to: 1; stepSize: 0.05
                    value: strip.pan
                    Accessible.name: strip.name + " pan"
                    onMoved: backend.setPan(strip.sid, value)
                    background: Rectangle {
                        x: panSlider.leftPadding
                        y: panSlider.topPadding + panSlider.availableHeight / 2 - 2
                        width: panSlider.availableWidth; height: 4; radius: 2
                        color: "#0a0c10"; border.color: "#2a303c"
                        Rectangle { x: parent.width / 2 - 1; y: -2; width: 2; height: 8; color: "#4a5366" }
                    }
                    handle: Rectangle {
                        x: panSlider.leftPadding + panSlider.visualPosition * (panSlider.availableWidth - width)
                        y: panSlider.topPadding + panSlider.availableHeight / 2 - height / 2
                        width: 12; height: 16; radius: 3
                        color: panSlider.pressed ? "#7dd3fc" : "#c3cad6"
                        border.width: panSlider.visualFocus ? 2 : 0
                        border.color: "#7dd3fc"
                    }
                    TapHandler { onDoubleTapped: backend.setPan(strip.sid, 0) }
                }
            }
        }

        // buttons: fixed height so every strip lines up
        GridLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            columns: 2
            columnSpacing: 4; rowSpacing: 4
            DButton {
                Layout.fillWidth: true
                Layout.columnSpan: strip.hasSolo ? 1 : 2
                variant: "mute"; text: "M"; on: strip.mute
                Accessible.name: "Mute " + strip.name
                onClicked: backend.toggleMute(strip.sid)
            }
            DButton {
                visible: strip.hasSolo
                Layout.fillWidth: true
                variant: "solo"; text: "S"; on: strip.solo
                Accessible.name: "Solo " + strip.name
                onClicked: backend.toggleSolo(strip.sid)
            }
            DButton {
                id: chanBtn
                visible: strip.hasMono
                Layout.fillWidth: true
                Layout.columnSpan: 2
                variant: "route"
                text: strip.channelText + "  ▾"
                on: strip.mono
                Accessible.name: strip.name + " channels: " + strip.channelText
                onClicked: chanMenu.popup(chanBtn, 0, chanBtn.height)
                Menu {
                    id: chanMenu
                    Repeater {
                        model: strip.channelOptions
                        MenuItem {
                            required property var modelData
                            text: modelData.label
                            checkable: true
                            checked: modelData.id === strip.channel
                            onTriggered: backend.setChannel(strip.sid, modelData.id)
                        }
                    }
                }
            }
            Item { visible: !strip.hasMono; Layout.columnSpan: 2; Layout.preferredHeight: 28 }
        }
    }

    Menu {
        id: menu
        Menu {
            title: "Colour"
            Repeater {
                model: backend.colors
                MenuItem {
                    required property var modelData
                    text: modelData.name.charAt(0).toUpperCase() + modelData.name.slice(1)
                    checkable: true
                    checked: modelData.name === strip.colorName
                    onTriggered: backend.setColor(strip.sid, modelData.name)
                    indicator: Rectangle {
                        x: 8; anchors.verticalCenter: parent.verticalCenter
                        width: 14; height: 14; radius: 3
                        color: modelData.hex
                        border.width: parent.checked ? 2 : 0
                        border.color: "#e6e8ec"
                    }
                    leftPadding: 30
                }
            }
        }
        MenuItem {
            text: "Move left"
            enabled: strip.index > 0
            onTriggered: strip.moveBy(-1)
        }
        MenuItem {
            text: "Move right"
            enabled: strip.index < strip.count - 1
            onTriggered: strip.moveBy(1)
        }
        MenuSeparator {}
        MenuItem {
            text: "Rename…"
            visible: !strip.isApp
            height: visible ? implicitHeight : 0
            onTriggered: renamePopup.open()
        }
        MenuItem {
            text: "New apps play here"
            visible: strip.kind === "vi"
            height: visible ? implicitHeight : 0
            checkable: true
            checked: strip.isDefault
            onTriggered: backend.setDefault(strip.sid)
        }
        MenuSeparator { visible: !strip.isApp; height: visible ? implicitHeight : 0 }
        MenuItem {
            text: "Remove strip"
            visible: !strip.isApp
            height: visible ? implicitHeight : 0
            onTriggered: confirmRemove.open()
        }
    }

    Popup {
        id: renamePopup
        x: 0; y: 60
        width: 200
        modal: true
        focus: true
        background: Rectangle { color: "#1f242e"; radius: 8; border.color: "#2c3340" }
        onOpened: { nameField.text = strip.name; nameField.selectAll(); nameField.forceActiveFocus() }
        Column {
            spacing: 8
            width: parent.width
            Text { text: "Name"; color: "#a3acbb"; font.family: "Fira Sans"; font.pixelSize: 11 }
            TextField {
                id: nameField
                width: parent.width
                color: "#e6e8ec"
                background: Rectangle { color: "#0b0d11"; radius: 6; border.color: nameField.activeFocus ? "#7dd3fc" : "#2c3340" }
                onAccepted: { backend.renameStrip(strip.sid, text); renamePopup.close() }
            }
        }
    }

    Popup {
        id: confirmRemove
        x: 0; y: 60
        width: 220
        modal: true
        background: Rectangle { color: "#1f242e"; radius: 8; border.color: "#2c3340" }
        Column {
            spacing: 10
            width: parent.width
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Remove " + strip.name + "?" + (strip.kind === "vi" || strip.kind === "ovi" ? " Its virtual device is deleted too." : "")
                color: "#e6e8ec"; font.family: "Fira Sans"; font.pixelSize: 12
            }
            Row {
                spacing: 6
                DButton { variant: "plain"; text: "Cancel"; implicitWidth: 70; onClicked: confirmRemove.close() }
                DButton { variant: "mute"; on: true; text: "Remove"; implicitWidth: 70; onClicked: { confirmRemove.close(); backend.removeStrip(strip.sid) } }
            }
        }
    }
}
