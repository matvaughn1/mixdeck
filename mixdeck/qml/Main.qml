import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1440
    height: 900
    minimumWidth: 640
    minimumHeight: 560
    title: "Mixdeck"
    color: "#0b0d11"
    font.family: "Fira Sans"

    palette.window: "#1f242e"
    palette.base: "#0b0d11"
    palette.text: "#e6e8ec"
    palette.windowText: "#e6e8ec"
    palette.button: "#1f242e"
    palette.buttonText: "#e6e8ec"
    palette.highlight: "#0e3a4a"
    palette.highlightedText: "#e0f2fe"
    palette.light: "#2c3340"
    palette.mid: "#2c3340"
    palette.dark: "#0b0d11"

    onVisibleChanged: backend.setWindowVisible(visible)
    Component.onCompleted: backend.setWindowVisible(visible)

    header: Rectangle {
        height: hdr.implicitHeight + 24
        color: "#0f1217"
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#1d222b" }
        RowLayout {
            id: hdr
            anchors.fill: parent
            anchors.leftMargin: 20; anchors.rightMargin: 20
            spacing: 12
            Canvas {
                width: 28; height: 28
                Accessible.ignored: true
                onPaint: {
                    var c = getContext("2d")
                    c.strokeStyle = "#7dd3fc"; c.lineWidth = 2; c.lineCap = "round"
                    var xs = [7, 14, 21], ys = [16, 9, 19]
                    for (var i = 0; i < 3; i++) {
                        c.beginPath(); c.moveTo(xs[i], 4); c.lineTo(xs[i], 24); c.stroke()
                        c.fillStyle = "#0f1217"; c.fillRect(xs[i] - 3, ys[i] - 2, 6, 4)
                        c.strokeRect(xs[i] - 3, ys[i] - 2, 6, 4)
                    }
                }
            }
            Column {
                spacing: 2
                Text { text: "Mixdeck"; color: "#e6e8ec"; font.pixelSize: 16; font.weight: Font.Bold }
                Text { text: "PipeWire mixer"; color: "#a3acbb"; font.pixelSize: 11 }
            }
            Item { Layout.fillWidth: true }

            Rectangle {
                implicitWidth: xtRow.implicitWidth + 16
                implicitHeight: 40
                radius: 10
                color: "#13171e"
                border.color: "#2c3340"
                RowLayout {
                    id: xtRow
                    anchors.verticalCenter: parent.verticalCenter
                    x: 12
                    spacing: 10
                    Rectangle {
                        width: 8; height: 8; radius: 4
                        color: !backend.xtPresent ? "#6b7280" : backend.xtActive ? "#34d399" : "#a3acbb"
                    }
                    Text { text: "X-Touch"; color: "#e6e8ec"; font.weight: Font.DemiBold; font.pixelSize: 13 }
                    Text {
                        visible: !backend.xtPresent
                        text: "not plugged in"
                        color: "#a3acbb"; font.pixelSize: 12
                    }
                    Rectangle {
                        visible: backend.xtPresent
                        radius: 8; color: "#0b0d11"
                        implicitWidth: seg.implicitWidth + 4; implicitHeight: 34
                        Row {
                            id: seg
                            x: 2; y: 2; spacing: 2
                            Repeater {
                                model: [{ label: "This PC", pc: true }, { label: "Mac", pc: false }]
                                Button {
                                    required property var modelData
                                    readonly property bool on: backend.xtActive === modelData.pc
                                    height: 30
                                    padding: 14
                                    topPadding: 0; bottomPadding: 0
                                    text: modelData.label
                                    Accessible.checkable: true
                                    Accessible.checked: on
                                    onClicked: backend.setXtMode(modelData.pc)
                                    contentItem: Text {
                                        text: parent.text; font.pixelSize: 12; font.weight: Font.DemiBold
                                        color: parent.on ? "#f1f5f9" : "#a3acbb"
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    background: Rectangle {
                                        radius: 6
                                        color: parent.on ? "#2a3140" : parent.hovered ? "#161a21" : "transparent"
                                        border.width: parent.visualFocus ? 2 : 0
                                        border.color: "#7dd3fc"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    ScrollView {
        id: scroller
        anchors.fill: parent
        contentWidth: Math.max(availableWidth, body.implicitWidth + 40)
        contentHeight: body.implicitHeight + 40

        ColumnLayout {
            id: body
            x: 20; y: 20
            width: scroller.contentWidth - 40
            spacing: 20

            RowLayout {
                spacing: 16
                Layout.alignment: Qt.AlignLeft
                Section {
                    Layout.fillHeight: true
                    title: "Inputs"
                    section: "inputs"
                    stripModel: backend.inputsModel
                    addLabel: "Add input"
                    onAddClicked: (a) => addPopup.openFor("in", a)
                }
                Section {
                    Layout.fillHeight: true
                    title: "Apps"
                    section: "apps"
                    stripModel: backend.appsModel
                    emptyText: "Apps that are playing sound show up here."
                }
                Section {
                    Layout.fillHeight: true
                    title: "Outputs"
                    section: "outputs"
                    stripModel: backend.outputsModel
                    addLabel: "Add output"
                    onAddClicked: (a) => addPopup.openFor("out", a)
                }
            }

            // X-Touch fader map
            Rectangle {
                visible: backend.xtPresent
                Layout.fillWidth: true
                implicitHeight: xtLay.implicitHeight + 28
                radius: 12
                color: "#12151b"
                border.color: "#1f2430"
                ColumnLayout {
                    id: xtLay
                    x: 14; y: 14
                    width: parent.width - 28
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        Column {
                            spacing: 3
                            Layout.fillWidth: true
                            Text {
                                text: "X-TOUCH FADERS"; color: "#a3acbb"; font.pixelSize: 11
                                font.weight: Font.Bold; font.letterSpacing: 1.5
                            }
                            Text {
                                text: backend.xtActive
                                      ? "Controlling this PC. Press USER on the X-Touch to hand it to the Mac."
                                      : "Linked to the Mac. Press USER on the X-Touch to bring it back here."
                                color: "#c3cad6"; font.pixelSize: 12
                            }
                        }
                        DButton { variant: "plain"; text: "◀"; implicitWidth: 36; implicitHeight: 36; Accessible.name: "Previous bank"; onClicked: backend.bankBy(-8) }
                        Text {
                            text: "Bank " + backend.xtBank
                            color: "#c3cad6"; font.family: "Noto Sans Mono"; font.pixelSize: 12
                            Layout.preferredWidth: 64; horizontalAlignment: Text.AlignHCenter
                        }
                        DButton { variant: "plain"; text: "▶"; implicitWidth: 36; implicitHeight: 36; Accessible.name: "Next bank"; onClicked: backend.bankBy(8) }
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 9
                        columnSpacing: 6
                        opacity: backend.xtActive ? 1 : 0.4
                        Repeater {
                            model: backend.xtCells
                            Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.minimumWidth: 80
                                implicitHeight: cellCol.implicitHeight + 16
                                radius: 8
                                color: "#0b0d11"
                                border.color: "#252b37"
                                Column {
                                    id: cellCol
                                    x: 8; y: 8
                                    width: parent.width - 16
                                    spacing: 6
                                    RowLayout {
                                        width: parent.width
                                        Text { text: modelData.num; color: "#a3acbb"; font.family: "Noto Sans Mono"; font.pixelSize: 10; Layout.fillWidth: true }
                                        Text { text: modelData.db; color: "#a3acbb"; font.family: "Noto Sans Mono"; font.pixelSize: 10 }
                                    }
                                    Rectangle {
                                        width: parent.width; height: 26; radius: 4
                                        color: modelData.color
                                        Text {
                                            anchors.centerIn: parent
                                            text: modelData.name
                                            color: "#0b0d11"; font.family: "Noto Sans Mono"; font.pixelSize: 12; font.weight: Font.Bold
                                        }
                                    }
                                    Rectangle {
                                        width: parent.width; height: 4; radius: 2; color: "#252b37"
                                        Rectangle { width: parent.width * Math.min(1, modelData.vol); height: 4; radius: 2; color: "#c3cad6" }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Add an input or output
    Popup {
        id: addPopup
        property string side: "in"
        property var choices: []
        width: 300
        modal: true
        focus: true
        padding: 14
        background: Rectangle { color: "#1f242e"; radius: 10; border.color: "#2c3340" }

        function openFor(which, anchor) {
            side = which
            choices = backend.hardwareChoices(which === "in" ? "hw" : "ohw")
            virtName.text = ""
            var p = anchor.mapToItem(Overlay.overlay, 0, anchor.height + 6)
            x = Math.max(8, Math.min(p.x - width + anchor.width, win.width - width - 8))
            y = p.y
            open()
        }

        Column {
            width: parent.width
            spacing: 10
            Text {
                text: addPopup.side === "in" ? "Add an input" : "Add an output"
                color: "#e6e8ec"; font.pixelSize: 14; font.weight: Font.DemiBold
            }
            Text {
                text: addPopup.side === "in" ? "VIRTUAL INPUT (apps can play into it)" : "VIRTUAL OUTPUT (a mic other apps can record)"
                color: "#a3acbb"; font.pixelSize: 10; font.letterSpacing: 0.6
            }
            RowLayout {
                width: parent.width
                TextField {
                    id: virtName
                    Layout.fillWidth: true
                    placeholderText: "Name, e.g. Music"
                    color: "#e6e8ec"
                    placeholderTextColor: "#8b94a5"
                    background: Rectangle { color: "#0b0d11"; radius: 6; border.color: virtName.activeFocus ? "#7dd3fc" : "#2c3340" }
                    onAccepted: addVirt.clicked()
                }
                DButton {
                    id: addVirt
                    variant: "route"; on: true; text: "Add"; implicitWidth: 56; implicitHeight: 34
                    enabled: virtName.text.trim() !== ""
                    onClicked: {
                        backend.addStrip(addPopup.side === "in" ? "vi" : "ovi", "", virtName.text, "")
                        addPopup.close()
                    }
                }
            }
            Text {
                text: addPopup.side === "in" ? "HARDWARE INPUT" : "HARDWARE OUTPUT"
                color: "#a3acbb"; font.pixelSize: 10; font.letterSpacing: 0.6
            }
            Text {
                visible: addPopup.choices.length === 0
                width: parent.width; wrapMode: Text.WordWrap
                text: "No devices to add."
                color: "#a3acbb"; font.pixelSize: 12
            }
            Repeater {
                model: addPopup.choices
                DButton {
                    required property var modelData
                    width: parent.width
                    implicitHeight: 34
                    variant: "plain"
                    readonly property string short: modelData.name.replace(/ (Analog|Digital|Pro)( Stereo| Mono)?.*$/, "").replace(/High Definition Audio Controller/, "HDMI")
                    text: modelData.label ? short + "  ·  " + modelData.label : short
                    onClicked: {
                        var isChan = modelData.channel && modelData.channel !== "stereo"
                        var nm = isChan ? modelData.label.replace("Input ", "In ") : short.substring(0, 18)
                        backend.addStrip(addPopup.side === "in" ? "hw" : "ohw", modelData.device, nm, modelData.channel)
                        addPopup.close()
                    }
                }
            }
        }
    }
}
