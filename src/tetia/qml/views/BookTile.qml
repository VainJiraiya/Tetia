// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import org.kde.kirigami 2.20 as Kirigami

// A comic, a PDF or an EPUB: its cover, and its title under it (up to two lines), like a book on a shelf.
Item {
    id: tile

    property string source: ""            // an image:// address
    property int thumbSize: 256
    property real coverHeight: height - 44
    property string title: ""
    property real progress: 0             // 0..1; shown only while partway
    property bool finished: false
    property bool selected: false

    readonly property alias hovered: hover.hovered

    signal clicked(var mouse)

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }

    Rectangle {
        id: cover
        width: parent.width
        height: tile.coverHeight
        radius: 6
        color: Qt.tint(palette.window, Qt.alpha(palette.text, 0.08))
        opacity: tile.finished ? 0.55 : 1

        Kirigami.ShadowedImage {
            color: "transparent"            // (its own background is white: the tile's shows instead)
            anchors.fill: parent
            radius: 6
            source: tile.source
            sourceSize: Qt.size(tile.thumbSize, tile.thumbSize)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
        }
        Rectangle {
            visible: tile.progress > 0 && tile.progress < 1 && !tile.finished
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 4
            color: Qt.rgba(0, 0, 0, 0.45)
            Rectangle {
                width: parent.width * tile.progress
                height: parent.height
                color: palette.highlight
            }
        }
        Rectangle {
            anchors.fill: parent
            radius: 6
            color: tile.selected ? Qt.alpha(palette.highlight, 0.25) : "transparent"
            border.width: tile.selected ? 3 : (hover.hovered ? 2 : 0)
            border.color: palette.highlight
        }
        Rectangle {
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: 6
            width: 20
            height: 20
            radius: 10
            color: palette.highlight
            visible: tile.selected
            Text {
                anchors.centerIn: parent
                text: "✓"
                color: palette.highlightedText
                font.pixelSize: 11
                font.bold: true
            }
        }
    }

    Text {
        anchors.top: cover.bottom
        anchors.topMargin: 6
        width: parent.width
        text: tile.title
        color: palette.text
        font.pixelSize: 13
        font.weight: Font.DemiBold
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function(mouse) { tile.clicked(mouse) }
    }
}
