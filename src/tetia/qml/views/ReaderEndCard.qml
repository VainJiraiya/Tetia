// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// What follows the last page: the book is finished, and what to read next.
Rectangle {
    id: root

    property string title: ""
    property string nextName: ""
    property bool hasNext: nextName !== ""

    signal openNext()
    signal back()

    implicitWidth: Kirigami.Units.gridUnit * 22
    implicitHeight: column.implicitHeight + Kirigami.Units.gridUnit * 2
    radius: 8
    color: Kirigami.Theme.backgroundColor
    border.width: 1
    border.color: Qt.alpha(Kirigami.Theme.textColor, 0.2)

    // clicks on the card are the card's, not the page's underneath
    MouseArea { anchors.fill: parent }

    ColumnLayout {
        id: column
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 2
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Icon {
            Layout.alignment: Qt.AlignHCenter
            source: "checkmark"
            Layout.preferredWidth: Kirigami.Units.iconSizes.large
            Layout.preferredHeight: Kirigami.Units.iconSizes.large
        }
        Kirigami.Heading {
            level: 3
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Finished " + root.title
        }
        Label {
            visible: root.hasNext
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideMiddle
            opacity: 0.7
            text: "Next: " + root.nextName
        }
        Button {
            visible: root.hasNext
            Layout.alignment: Qt.AlignHCenter
            text: "Open next chapter"
            icon.name: "go-next"
            highlighted: true
            onClicked: root.openNext()
        }
        Button {
            Layout.alignment: Qt.AlignHCenter
            text: "Back to the library"
            icon.name: "go-previous"
            onClicked: root.back()
        }
    }
}
