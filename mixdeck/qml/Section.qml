import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A titled group of strips (Inputs / Apps / Outputs).
Rectangle {
    id: sec
    property string title
    property var stripModel
    property string addLabel: ""
    property string emptyText: ""
    property string section: ""
    property int dragFrom: -1
    property int dragTarget: -1
    signal addClicked(Item anchor)

    implicitWidth: Math.max(lay.implicitWidth + 24, 180)
    implicitHeight: lay.implicitHeight + 24
    radius: 12
    color: "#12151b"
    border.color: "#1f2430"

    ColumnLayout {
        id: lay
        x: 12; y: 12
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            Layout.leftMargin: 4
            Layout.rightMargin: 4
            Text {
                text: sec.title.toUpperCase()
                color: "#a3acbb"; font.family: "Fira Sans"; font.pixelSize: 11
                font.weight: Font.Bold; font.letterSpacing: 1.5
                Layout.fillWidth: true
                Accessible.role: Accessible.Heading
            }
            DButton {
                id: addBtn
                visible: sec.addLabel !== ""
                variant: "plain"; text: "+ Add"; implicitWidth: 56
                Accessible.name: sec.addLabel
                onClicked: sec.addClicked(addBtn)
            }
        }
        Row {
            id: stripRow
            spacing: 8
            Repeater {
                id: rep
                model: sec.stripModel
                Strip {
                    section: sec.section
                    count: rep.count
                    onDragTo: (from, to) => { sec.dragFrom = from; sec.dragTarget = to }
                }
            }
            Text {
                visible: rep.count === 0 && sec.emptyText !== ""
                width: 150
                wrapMode: Text.WordWrap
                text: sec.emptyText
                color: "#a3acbb"; font.family: "Fira Sans"; font.pixelSize: 12
                topPadding: 20
            }
        }
    }

    // where a dragged strip will land
    Rectangle {
        visible: sec.dragTarget >= 0 && sec.dragTarget !== sec.dragFrom
        width: 3; radius: 2
        color: "#7dd3fc"
        y: lay.y + stripRow.y
        height: stripRow.height
        x: lay.x + stripRow.x + (sec.dragTarget > sec.dragFrom ? sec.dragTarget + 1 : sec.dragTarget) * 124 - 6
    }
}
