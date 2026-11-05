// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// What comes before the first page: the chapter that came before this one.
Rectangle {
    id: root

    property string previousName: ""

    signal openPrevious()

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

        Label {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            opacity: 0.7
            text: "Previous chapter"
        }
        Kirigami.Heading {
            level: 3
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideMiddle
            text: root.previousName
        }
        Button {
            Layout.alignment: Qt.AlignHCenter
            text: "Open previous chapter"
            icon.name: "go-previous"
            highlighted: true
            onClicked: root.openPrevious()
        }
    }
}
