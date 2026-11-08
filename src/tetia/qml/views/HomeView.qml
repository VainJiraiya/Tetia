// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import "thumbUri.js" as ThumbUri

// Home: what you are in the middle of, what you pinned, your favorites and what came in lately. Nothing here is
// picked for you, and there is no banner. Each row is only as long as one screen width; the tabs hold the rest.
Rectangle {
    id: home

    property var backend: null                 // HomeModel
    property int coverRevision: 0

    property var continueItems: []
    property var pinnedItems: []
    property var favoriteCovers: []
    property var favoriteFiles: []
    property var recentFiles: []

    // what to open: the host knows how
    signal continueOpened(var item)
    signal pinnedOpened(var item)
    signal coverOpened(var item)
    signal pictureOpened(var files, int index)
    signal unpinRequested(string kind, string ref)

    color: Kirigami.Theme.backgroundColor

    function refresh() {
        if (!backend) return
        continueItems = backend.continueItems()
        pinnedItems = backend.pinned()
        favoriteCovers = backend.favoriteCovers()
        favoriteFiles = backend.favorites()
        recentFiles = backend.recent()
    }
    onVisibleChanged: if (visible) refresh()
    Connections {
        target: home.backend
        function onPinsChanged() { home.refresh() }
    }

    function thumb(path) { return path ? "image://thumbnail/" + ThumbUri.fromPath(path) : "" }

    // Pictures in rows of one height filling the width (their own shape, as on the tabs), at most `rows` rows
    function justify(files, width, height, rows) {
        var out = [], row = [], sum = 0, gap = 6
        for (var i = 0; i < files.length && out.length < rows; i++) {
            var aspect = Math.min(16 / 9, Math.max(0.75, files[i].aspect))
            row.push({ file: files[i], index: i, aspect: aspect })
            sum += aspect
            if (sum * height + (row.length - 1) * gap >= width) {
                var h = (width - (row.length - 1) * gap) / sum
                out.push(row.map(function(t) { return Object.assign(t, { w: t.aspect * h, h: h }) }))
                row = []
                sum = 0
            }
        }
        if (row.length > 0 && out.length < rows)
            out.push(row.map(function(t) { return Object.assign(t, { w: t.aspect * height, h: height }) }))
        return out
    }

    component Section: ColumnLayout {
        property string title
        Layout.fillWidth: true
        spacing: 10
        Label {
            text: parent.title
            font.weight: Font.DemiBold
        }
    }

    component PictureRows: Column {
        id: pictureRows
        property var files: []
        property int rows: 1
        spacing: 6
        Repeater {
            model: home.justify(pictureRows.files, pictureRows.width, 170, pictureRows.rows)
            delegate: Row {
                required property var modelData
                spacing: 6
                Repeater {
                    model: modelData
                    delegate: PictureTile {
                        required property var modelData
                        width: modelData.w
                        height: modelData.h
                        source: home.thumb(modelData.file.path)
                        thumbSize: ThumbUri.tierFor(Math.ceil(Math.max(width, height) * Screen.devicePixelRatio))
                        fileName: modelData.file.name
                        isVideo: modelData.file.kind === "video"
                        onClicked: function(mouse) {
                            if (mouse.button === Qt.LeftButton) home.pictureOpened(pictureRows.files, modelData.index)
                        }
                    }
                }
            }
        }
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: column.implicitHeight + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: column
            x: 24
            y: 20
            width: flick.width - 48
            spacing: 26

            Label {
                Layout.fillWidth: true
                visible: home.continueItems.length === 0 && home.pinnedItems.length === 0 && home.favoriteCovers.length === 0
                         && home.favoriteFiles.length === 0 && home.recentFiles.length === 0
                wrapMode: Text.WordWrap
                opacity: 0.7
                text: "Home fills up as you use Tetia: what you are reading or watching, what you pin (“Pin to Home” on a board, a folder or a tag), your favorites and what was added lately."
            }

            Section {
                title: "Continue"
                visible: home.continueItems.length > 0
                Row {
                    id: continueRow
                    Layout.fillWidth: true
                    spacing: 16
                    readonly property int fits: Math.max(1, Math.floor((width + spacing) / (320 + spacing)))
                    Repeater {
                        model: home.continueItems.slice(0, continueRow.fits)
                        delegate: Rectangle {
                            required property var modelData
                            readonly property bool wide: modelData.kind === "video" || modelData.kind === "show"
                            width: 320
                            height: 100
                            radius: 8
                            color: cardHover.hovered ? Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(Kirigami.Theme.highlightColor, 0.12))
                                                     : Kirigami.Theme.backgroundColor
                            border.width: 1
                            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.15)
                            HoverHandler { id: cardHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: home.continueOpened(modelData) }
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 12
                                Kirigami.ShadowedImage {
                                    Layout.preferredWidth: parent.parent.wide ? 136 : 56
                                    Layout.preferredHeight: parent.parent.wide ? 77 : 84
                                    radius: 4
                                    source: home.thumb(modelData.cover)
                                    sourceSize: Qt.size(256, 256)
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData.name
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData.where
                                        opacity: 0.7
                                        font: Kirigami.Theme.smallFont
                                        elide: Text.ElideRight
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.topMargin: 6
                                        height: 4
                                        radius: 2
                                        color: Qt.alpha(Kirigami.Theme.textColor, 0.15)
                                        Rectangle {
                                            width: parent.width * Math.min(1, modelData.fraction)
                                            height: parent.height
                                            radius: 2
                                            color: Kirigami.Theme.highlightColor
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Section {
                title: "Pinned"
                visible: home.pinnedItems.length > 0
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 22
                    Repeater {
                        model: home.pinnedItems
                        delegate: CollectionTile {
                            required property var modelData
                            width: 150
                            height: 225 + 44
                            coverHeight: 225
                            kind: modelData.kind === "series" ? "series" : modelData.kind
                            name: modelData.name
                            subtitle: modelData.sub
                            coverSource: home.thumb(modelData.cover)
                            collageSources: modelData.collage.map(function(p) { return home.thumb(p) })
                            thumbSize: ThumbUri.tierFor(Math.ceil(225 * Screen.devicePixelRatio))
                            badge: modelData.badge
                            progress: modelData.fraction
                            finished: modelData.finished
                            onClicked: function(mouse) {
                                if (mouse.button === Qt.RightButton) {
                                    pinMenu.item = modelData
                                    pinMenu.popup()
                                } else {
                                    home.pinnedOpened(modelData)
                                }
                            }
                        }
                    }
                }
            }

            Section {
                title: "Favorites"
                visible: home.favoriteCovers.length > 0 || home.favoriteFiles.length > 0
                Flow {
                    Layout.fillWidth: true
                    spacing: 22
                    visible: home.favoriteCovers.length > 0
                    Repeater {
                        model: home.favoriteCovers
                        delegate: CollectionTile {
                            required property var modelData
                            width: 132
                            height: 198 + 44
                            coverHeight: 198
                            kind: modelData.kind === "book" ? "single" : modelData.kind
                            name: modelData.name
                            coverSource: home.thumb(modelData.cover)
                            thumbSize: ThumbUri.tierFor(Math.ceil(198 * Screen.devicePixelRatio))
                            onClicked: function(mouse) { if (mouse.button === Qt.LeftButton) home.coverOpened(modelData) }
                        }
                    }
                }
                PictureRows {
                    Layout.fillWidth: true
                    files: home.favoriteFiles
                    rows: 1
                }
            }

            Section {
                title: "Recently added"
                visible: home.recentFiles.length > 0
                PictureRows {
                    Layout.fillWidth: true
                    files: home.recentFiles
                    rows: 2
                }
            }
        }
    }

    Menu {
        id: pinMenu
        property var item: null
        MenuItem {
            text: "Open"
            font.bold: true
            onTriggered: home.pinnedOpened(pinMenu.item)
        }
        MenuSeparator {}
        MenuItem {
            text: "Unpin from Home"
            icon.name: "window-unpin"
            onTriggered: home.unpinRequested(pinMenu.item.kind === "series" ? "folder" : pinMenu.item.kind, pinMenu.item.ref)
        }
    }
}
