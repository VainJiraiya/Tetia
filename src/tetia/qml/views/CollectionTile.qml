// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import org.kde.kirigami 2.20 as Kirigami

// A collection: a portrait cover, its name and what it holds under it. A collection is a curated piece, like a
// book or an album, so it is always a portrait cover; what kind of collection it is shows in how the cover is
// drawn, never in an extra badge:
//   "folder"   a folder on disk: the edges of the covers behind it show above it
//   "virtual"  a virtual folder (it tidies files away, like a folder): the same edges, and a link mark
//   "series"   a manga or a show: one cover, like a book
//   "single"   a folder holding one file: drawn as that file
//   "board"    a board (it gathers from many places): a collage of three pictures
//   "tag"      a tag pinned to Home: a collage, with the tag on it
//   "library"  a tab's library on Home: a collage of what it holds
// At most one badge (what is left to read or watch), a thin bar while partway, dimmed once finished.
Item {
    id: tile

    property string kind: "folder"
    property string name: ""
    property string subtitle: ""
    property string coverSource: ""          // an image:// address (or "")
    property var collageSources: []           // a board's or tag's three pictures
    property int thumbSize: 256
    property real coverHeight: height - 44
    property string badge: ""
    property real progress: 0                 // 0..1; shown only while partway
    property bool finished: false
    property bool picked: false               // selected
    property color tagColor: Kirigami.Theme.positiveTextColor

    readonly property bool stacked: kind === "folder" || kind === "virtual"
    readonly property bool collage: kind === "board" || kind === "tag" || kind === "library"
    readonly property alias hovered: hover.hovered

    signal clicked(var mouse)

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }

    Repeater {
        model: tile.stacked ? 2 : 0
        Rectangle {
            required property int index
            x: index === 0 ? 16 : 8
            y: index === 0 ? -9 : -4
            width: tile.width - 2 * x
            height: 24
            radius: 6
            color: Qt.alpha(palette.text, index === 0 ? 0.16 : 0.24)
        }
    }

    Rectangle {
        id: cover
        width: parent.width
        height: tile.coverHeight
        radius: 6
        color: Qt.tint(palette.window, Qt.alpha(palette.text, 0.08))
        opacity: tile.finished ? 0.55 : 1

        Kirigami.ShadowedImage {
            id: picture
            anchors.fill: parent
            radius: 6
            visible: !tile.collage
            source: tile.collage ? "" : tile.coverSource
            sourceSize: Qt.size(tile.thumbSize, tile.thumbSize)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
        }

        // a collage: one big picture over two small ones
        Item {
            anchors.fill: parent
            visible: tile.collage
            Kirigami.ShadowedImage {
                width: parent.width
                height: Math.round(parent.height * 0.64) - 1
                corners.topLeftRadius: 6
                corners.topRightRadius: 6
                source: tile.collage && tile.collageSources.length > 0 ? tile.collageSources[0] : ""
                sourceSize: Qt.size(tile.thumbSize, tile.thumbSize)
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
            }
            Repeater {
                model: 2
                Kirigami.ShadowedImage {
                    required property int index
                    x: index === 0 ? 0 : parent.width / 2 + 1
                    y: Math.round(parent.height * 0.64) + 1
                    width: parent.width / 2 - 1
                    height: parent.height - y
                    corners.bottomLeftRadius: index === 0 ? 6 : 0
                    corners.bottomRightRadius: index === 1 ? 6 : 0
                    source: tile.collage && tile.collageSources.length > index + 1 ? tile.collageSources[index + 1] : ""
                    sourceSize: Qt.size(tile.thumbSize / 2, tile.thumbSize / 2)
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                }
            }
        }

        Kirigami.Icon {
            anchors.centerIn: parent
            width: parent.width * 0.4
            height: width
            source: "folder"
            opacity: 0.5
            visible: tile.stacked && picture.status !== Image.Ready
        }

        // a pinned tag carries its name on the collage, in its category's colour
        Rectangle {
            visible: tile.kind === "tag"
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.margins: 8
            height: 24
            width: tagText.implicitWidth + 18
            radius: 12
            color: palette.base
            Text {
                id: tagText
                anchors.centerIn: parent
                text: tile.name
                color: tile.tagColor
                font.pixelSize: 13
                font.weight: Font.Bold
            }
        }

        // the one badge: what is left (chapters, episodes)
        Rectangle {
            visible: tile.badge !== "" && !tile.picked
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.margins: 6
            height: 22
            width: Math.max(height, badgeText.implicitWidth + 14)
            radius: 4
            color: palette.highlight
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: tile.badge
                color: palette.highlightedText
                font.pixelSize: 12
                font.weight: Font.Bold
            }
        }

        // partway: a thin bar along the bottom
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

        // hover and selection
        Rectangle {
            anchors.fill: parent
            radius: 6
            color: tile.picked ? Qt.alpha(palette.highlight, 0.25) : "transparent"
            border.width: tile.picked ? 3 : (hover.hovered ? 2 : 0)
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
            visible: tile.picked
            Text {
                anchors.centerIn: parent
                text: "✓"
                color: palette.highlightedText
                font.pixelSize: 11
                font.bold: true
            }
        }
    }

    Column {
        anchors.top: cover.bottom
        anchors.topMargin: 6
        width: parent.width
        spacing: 1

        Row {
            width: parent.width
            spacing: 4
            Kirigami.Icon {
                id: virtualMark
                visible: tile.kind === "virtual"
                width: visible ? 14 : 0
                height: 14
                anchors.verticalCenter: parent.verticalCenter
                source: "link"
                color: palette.highlight
            }
            Text {
                width: parent.width - virtualMark.width - (virtualMark.visible ? parent.spacing : 0)
                text: tile.name
                color: palette.text
                font.pixelSize: 13
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
        }
        Text {
            width: parent.width
            text: tile.subtitle
            visible: text !== ""
            color: palette.text
            opacity: 0.7
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function(mouse) { tile.clicked(mouse) }
    }
}
