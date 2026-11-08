// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import org.kde.kirigami 2.20 as Kirigami

// An image or a video in its own shape (the page gives the tile the picture's shape, so filling it shows the
// whole picture). Nothing on it at rest but what a video needs: its length (its one badge), a thin bar while
// partway and a check once watched. On hover: the name, and a star to favorite it.
Item {
    id: tile

    property string source: ""            // an image:// address
    property int thumbSize: 256
    property string fileName: ""
    property bool isVideo: false
    property bool isFavorite: false
    property real duration: 0
    property real watchFraction: 0
    property bool watched: false
    property bool selected: false
    property bool selecting: false         // select or tag mode: no name and star on hover

    readonly property alias hovered: hover.hovered
    // the badges' distance from the sides
    readonly property real side: 6

    signal clicked(var mouse)
    signal favoriteToggled()

    // A video's length as 0:42, 12:30 or 1:04:09
    function lengthText(seconds) {
        var s = Math.round(seconds)
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60
        var two = function(n) { return (n < 10 ? "0" : "") + n }
        return h > 0 ? h + ":" + two(m) + ":" + two(r) : m + ":" + two(r)
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }
    ToolTip.visible: hover.hovered && nameOnHover.truncated
    ToolTip.delay: 700
    ToolTip.text: fileName

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function(mouse) { tile.clicked(mouse) }
    }

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: Qt.tint(palette.window, Qt.alpha(palette.text, 0.08))
    }

    Kirigami.ShadowedImage {
        anchors.fill: parent
        radius: 6
        source: tile.source
        sourceSize: Qt.size(tile.thumbSize, tile.thumbSize)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
    }

    // on hover: the name and a star over a shade at the bottom
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Math.min(parent.height, 44)
        radius: 6
        visible: hover.hovered && !tile.selecting
        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.72) }
        }
        Text {
            id: nameOnHover
            anchors.left: parent.left
            anchors.right: star.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: Math.max(8, tile.side)
            anchors.bottomMargin: 7
            text: tile.fileName
            color: "white"
            font.pixelSize: 12
            elide: Text.ElideMiddle
        }
        Kirigami.Icon {
            id: star
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: tile.side
            anchors.bottomMargin: 5
            width: 18
            height: 18
            source: tile.isFavorite ? "starred-symbolic" : "non-starred-symbolic"
            color: "white"
            HoverHandler { id: starHover }
            TapHandler { onTapped: tile.favoriteToggled() }
            ToolTip.visible: starHover.hovered
            ToolTip.delay: 500
            ToolTip.text: tile.isFavorite ? "Remove from favorites" : "Add to favorites"
        }
    }

    // a video's length, bottom right
    Rectangle {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: tile.side
        anchors.bottomMargin: 6 + (bar.visible ? 4 : 0)
        visible: tile.isVideo && tile.duration > 0 && !(hover.hovered && !tile.selecting)
        width: lengthLabel.implicitWidth + 10
        height: 18
        radius: 4
        color: Qt.rgba(0, 0, 0, 0.6)
        Text {
            id: lengthLabel
            anchors.centerIn: parent
            text: tile.lengthText(tile.duration)
            color: "white"
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }
    }

    // how far a long video was watched
    Rectangle {
        id: bar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 4
        visible: tile.isVideo && tile.watchFraction > 0 && !tile.watched
        color: Qt.rgba(0, 0, 0, 0.5)
        Rectangle {
            width: parent.width * tile.watchFraction
            height: parent.height
            color: palette.highlight
        }
    }

    // a long video watched to the end
    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.topMargin: 6
        anchors.leftMargin: tile.side
        width: 20
        height: 20
        radius: 10
        color: Qt.rgba(0, 0, 0, 0.6)
        visible: tile.isVideo && tile.watched
        Text {
            anchors.centerIn: parent
            text: "✓"
            color: "white"
            font.pixelSize: 11
            font.bold: true
        }
    }

    // hover and selection
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
        anchors.topMargin: 6
        anchors.rightMargin: tile.side
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
