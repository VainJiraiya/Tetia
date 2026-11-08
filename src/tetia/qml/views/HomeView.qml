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
    property var libraryItems: []
    property var pinnedItems: []
    property var favoriteCovers: []
    property var favoriteFiles: []
    property var recentFiles: []

    // what to open: the host knows how
    signal continueOpened(var item)
    signal libraryOpened(string tab)
    signal pinnedOpened(var item)
    signal coverOpened(var item)
    signal pictureOpened(var files, int index)
    signal unpinRequested(string kind, string ref)
    signal favoriteRemoved(string kind, var ref)     // "file" (a media id or a book's path) or "folder" (a path)
    signal favoriteSet(int mediaId, bool favorite)   // the star on a picture
    signal trashRequested(var ids)
    property var actions: null                      // MediaActions: show in the file manager, copy the path

    color: Kirigami.Theme.backgroundColor

    function refresh() {
        if (!backend) return
        continueItems = backend.continueItems()
        libraryItems = backend.library()
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

    function thumb(path) { return ThumbUri.source(path) }

    // Pictures in rows of one height filling the width (their own shape, as on the tabs), at most `rows` rows
    function justify(files, width, height, rows, gap) {
        var out = [], row = [], sum = 0
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

    // Home's pictures: about as big as the covers beside them and as far apart, so the two sides read as one page
    readonly property real pictureHeight: 230
    readonly property real pictureGap: 16

    component PictureRows: Column {
        id: pictureRows
        property var files: []
        property int rows: 1
        spacing: home.pictureGap
        Repeater {
            model: home.justify(pictureRows.files, pictureRows.width, home.pictureHeight, pictureRows.rows, home.pictureGap)
            delegate: Row {
                required property var modelData
                spacing: home.pictureGap
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
                        isFavorite: modelData.file.favorite === true
                        onFavoriteToggled: home.favoriteSet(modelData.file.id, !isFavorite)
                        onClicked: function(mouse) {
                            if (mouse.button === Qt.RightButton)
                                home.showMenu("picture", modelData.file, function() { home.pictureOpened(pictureRows.files, modelData.index) },
                                              pictureRows.files === home.favoriteFiles)
                            else home.pictureOpened(pictureRows.files, modelData.index)
                        }
                    }
                }
            }
        }
    }

    // A wide window has two columns: the covers and cards on the left, a wall of pictures (favorite pictures, then
    // what was added lately) on the right, as tall as the left side or the window, so Home has no empty half
    readonly property bool wide: flick.width >= 1200
    readonly property real leftWidth: wide ? Math.min(720, (flick.width - 48) * 0.5) : flick.width - 48

    Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: Math.max(column.implicitHeight, wall.visible ? wall.implicitHeight : 0) + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: wall
            visible: home.wide && (home.favoriteFiles.length > 0 || home.recentFiles.length > 0)
            x: 24 + home.leftWidth + 40
            y: 20
            width: flick.width - x - 24
            spacing: 26
            Section {
                title: "Favorite pictures"
                visible: home.favoriteFiles.length > 0
                PictureRows {
                    Layout.fillWidth: true
                    files: home.favoriteFiles
                    rows: 2
                }
            }
            Section {
                id: wallRecent
                title: "Recently added"
                visible: home.recentFiles.length > 0
                PictureRows {
                    Layout.fillWidth: true
                    files: home.recentFiles
                    // down to the end of the left column, or of the window
                    rows: Math.max(2, Math.ceil((Math.max(column.implicitHeight, flick.height - 40) - wallRecent.y - 30)
                                                / (home.pictureHeight + home.pictureGap)))
                }
            }
        }

        ColumnLayout {
            id: column
            x: 24
            y: 20
            width: home.leftWidth
            spacing: 26

            Label {
                Layout.fillWidth: true
                visible: home.libraryItems.length === 0 && home.recentFiles.length === 0
                wrapMode: Text.WordWrap
                opacity: 0.7
                text: "Home fills up as you use Tetia: what you are reading or watching, the boards you pin (“Pin to Home” in a board's menu), your favorites and what was added lately."
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
                            TapHandler {
                                acceptedButtons: Qt.RightButton
                                onTapped: home.showMenu("continue", modelData, function() { home.continueOpened(modelData) }, false)
                            }
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

            // What each tab holds: one card per tab with library folders, a click goes there
            Section {
                title: "Library"
                visible: home.libraryItems.length > 0
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 22
                    Repeater {
                        model: home.libraryItems
                        delegate: CollectionTile {
                            required property var modelData
                            width: 150
                            height: 225 + 44
                            coverHeight: 225
                            kind: "library"
                            name: modelData.name
                            subtitle: modelData.sub
                            collageSources: modelData.collage.map(function(p) { return home.thumb(p) })
                            thumbSize: ThumbUri.tierFor(Math.ceil(225 * Screen.devicePixelRatio))
                            onClicked: function(mouse) { if (mouse.button === Qt.LeftButton) home.libraryOpened(modelData.tab) }
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
                                    home.showMenu("pinned", modelData, function() { home.pinnedOpened(modelData) }, false)
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
                visible: home.favoriteCovers.length > 0 || (!home.wide && home.favoriteFiles.length > 0)
                Flow {
                    Layout.fillWidth: true
                    spacing: 22
                    visible: home.favoriteCovers.length > 0
                    Repeater {
                        model: home.favoriteCovers
                        delegate: CollectionTile {
                            required property var modelData
                            width: 150
                            height: 225 + 44
                            coverHeight: 225
                            kind: modelData.kind === "book" ? "single" : modelData.kind
                            name: modelData.name
                            coverSource: home.thumb(modelData.cover)
                            thumbSize: ThumbUri.tierFor(Math.ceil(225 * Screen.devicePixelRatio))
                            onClicked: function(mouse) {
                                if (mouse.button === Qt.RightButton)
                                    home.showMenu("cover", modelData, function() { home.coverOpened(modelData) }, true)
                                else home.coverOpened(modelData)
                            }
                        }
                    }
                }
                PictureRows {
                    Layout.fillWidth: true
                    visible: !home.wide                 // (on a wide window they are in the wall on the right)
                    files: home.favoriteFiles
                    rows: 1
                }
            }

            // The newest files fill whatever room is left under the other rows, so Home never ends in an empty area
            Section {
                id: recentSection
                title: "Recently added"
                visible: !home.wide && home.recentFiles.length > 0
                PictureRows {
                    Layout.fillWidth: true
                    files: home.recentFiles
                    rows: Math.max(2, Math.floor((flick.height - recentSection.y - 30 - 20) / (home.pictureHeight + home.pictureGap)))
                }
            }
        }
    }

    // One right-click menu for everything on Home, showing what applies: open it, take it off Home or out of the
    // favorites, find it on disk, and for a file, send it to the Trash
    property var menuItem: null
    property string menuKind: ""            // picture, continue, pinned, cover
    property var menuOpen: null
    property bool menuFavorite: false
    readonly property string menuPath: !menuItem ? "" : (menuKind === "pinned"
        ? (menuItem.kind === "folder" || menuItem.kind === "series" ? menuItem.ref : "") : (menuItem.path || ""))
    function showMenu(kind, item, open, favorite) {
        menuKind = kind
        menuItem = item
        menuOpen = open
        menuFavorite = favorite === true
        itemMenu.popup()
    }

    Menu {
        id: itemMenu
        MenuItem {
            text: "Open"
            icon.name: "document-open"
            font.bold: true
            onTriggered: if (home.menuOpen) home.menuOpen()
        }
        MenuItem {
            text: "Open in system default"
            icon.name: "document-open"
            visible: home.menuKind === "picture" || (home.menuKind === "cover" && home.menuItem !== null && home.menuItem.kind === "book")
            height: visible ? implicitHeight : 0
            onTriggered: Qt.openUrlExternally(ThumbUri.fromPath(home.menuItem.path))
        }
        MenuSeparator {}
        MenuItem {
            text: "Unpin from Home"
            icon.name: "window-unpin"
            visible: home.menuKind === "pinned"
            height: visible ? implicitHeight : 0
            onTriggered: home.unpinRequested(home.menuItem.kind === "series" ? "folder" : home.menuItem.kind, home.menuItem.ref)
        }
        MenuItem {
            text: "Remove from favorites"
            icon.name: "non-starred-symbolic"
            visible: home.menuFavorite
            height: visible ? implicitHeight : 0
            onTriggered: {
                if (home.menuKind === "picture") home.favoriteRemoved("file", home.menuItem.id)
                else if (home.menuItem.kind === "book") home.favoriteRemoved("book", home.menuItem.path)
                else home.favoriteRemoved("folder", home.menuItem.path)
            }
        }
        MenuSeparator { visible: home.menuPath !== "" }
        MenuItem {
            text: "Show in file manager"
            icon.name: "system-file-manager"
            visible: home.menuPath !== "" && home.actions !== null
            height: visible ? implicitHeight : 0
            onTriggered: home.actions.showInFileManager([home.menuPath])
        }
        MenuItem {
            text: "Copy path"
            icon.name: "edit-copy-path"
            visible: home.menuPath !== "" && home.actions !== null
            height: visible ? implicitHeight : 0
            onTriggered: home.actions.copyPaths([home.menuPath])
        }
        MenuSeparator { visible: home.menuKind === "picture" }
        MenuItem {
            text: "Move to Trash"
            icon.name: "user-trash"
            visible: home.menuKind === "picture"
            height: visible ? implicitHeight : 0
            onTriggered: home.trashRequested([home.menuItem.id])
        }
    }
}
