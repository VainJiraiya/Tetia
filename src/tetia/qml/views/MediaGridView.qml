// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0
import "thumbUri.js" as ThumbUri

// The media page's tiles. It is only the tiles: the tag panel lives next to it
// in main.qml, so it never ends up inside this Flickable's scrolling content.
//
// The tiles are laid out by TileRows (tileLayout.py): folders, series, comics and books as portrait covers in
// even rows, with their names under them; images and videos in their own shape, in rows that fill the width.
// The content height is exact and only the rows near the window exist, so a big folder costs no more than a
// small one. (Not a GridView: its cells are all one size. Not a ListView: it only estimates the height of rows
// it has not made yet, and these differ.)
Flickable {
    id: grid

    // Emitted when a tile is tapped, routed by the tapped item's own type
    // so callers don't have to re-check model roles themselves.
    signal imageClicked(int index)
    signal videoClicked(int index)
    signal comicClicked(int index)
    signal bookClicked(int index)
    signal openExternallyRequested(int index)   // "Open in system default" from the right-click menu
    // "Play from beginning" on a video that was stopped partway
    signal playFromStartRequested(int index)
    signal selectionChanged()

    // A subfolder tile was tapped; folderPath is a file:// URI.
    signal subfolderClicked(string subfolderPath)
    // A series tile was opened: which chapter is "resume", "first", "next" or "previous"
    signal subfolderSeriesRequested(string subfolderPath, string which)
    // A show (a series of videos) was opened: it has a page of its own
    signal showRequested(string subfolderPath)
    // A one-file subfolder was opened: it shows as that file, so open the file
    signal subfolderSingleFileRequested(string subfolderPath)

    // The context menu's "Edit tags" asks the host to enter tag mode with this
    // item selected (the host owns the tag-mode flag).
    signal editTagsRequested(int mediaId)

    // The context menu's "Metadata" asks the host to show this item's metadata panel.
    signal metadataRequested(int mediaId)

    // "Choose cover page..." on a comic or book (by id) or on a one-file subfolder (by the file's path)
    signal coverPickerRequested(int mediaId)
    signal subfolderCoverPickerRequested(string filePath)

    // Virtual folders. The grid only asks; the host (main.qml) does the work and reloads.
    // A virtual folder tile was opened
    signal virtualFolderClicked(int virtualId, string name)
    // Menu actions on a selection (ids: files, tiles: folder tiles as "virtual:<id>" or a file:// address):
    // "add" (pick a virtual folder), "addNew" (make one), "remove" (out of the virtual folder it is in)
    signal virtualActionRequested(string action, var ids, var tiles)
    // "Select" in a menu: enter select mode with this selected
    signal selectRequested(var ids, var tiles)
    signal newVirtualFolderRequested()
    // The T key: open or close the tag browser
    signal browseTagsRequested()
    signal virtualRenameRequested(int virtualId, string name)
    signal virtualDeleteRequested(int virtualId, string name)
    signal virtualCoverResetRequested(int virtualId)
    // Boards (the host does the work): open one, change its search, rename or delete it, make one
    signal boardClicked(int boardId, string name)
    signal boardEditRequested(int boardId)
    signal boardRenameRequested(int boardId, string name)
    signal boardDeleteRequested(int boardId, string name)
    signal newBoardRequested(var ids)
    // A file's menu: the file on disk
    signal renameRequested(string uri, string name)
    signal trashRequested(var ids)

    // A cover changed by hand: this number is added to the pictures' URLs so they reload
    property int coverRevision: 0
    readonly property string revisionSuffix: coverRevision > 0 ? "?v=" + coverRevision : ""

    // The rows (the grid model's tiles: folder tiles first, then files)
    property var model: null
    readonly property int count: tileRows.itemCount

    // Tile size: -2 .. +2. Pictures: the height their rows aim for. Covers: the narrowest a cover may be (a full
    // shelf stretches its covers a little to meet both edges). The thumbnail asked for is worked out per tile
    // from its size on screen (ThumbUri.tierFor), so a picture is never stretched.
    property int tileLevel: 0
    readonly property real pictureHeight: [130, 160, 190, 235, 290][tileLevel + 2]
    readonly property real coverWidth: [118, 136, 158, 190, 232][tileLevel + 2]
    // under a cover: its name (two lines for a file; a folder's name and what it holds)
    readonly property real coverLabel: 44
    readonly property bool showLabels: true

    // Tiles are `edge` from the left and right walls and `topPad` from the header
    readonly property real edge: 24
    readonly property real topPad: 20
    // Badges sit on the picture, in its corners, one at most per corner
    readonly property int badgeFont: 11
    readonly property color badgeColor: Qt.rgba(0, 0, 0, 0.6)
    readonly property int badgeHeight: 20
    readonly property int badgeMargin: 6
    property bool tagMode: false
    // Select mode: the same click and drag selection as tag mode, for moving things into virtual
    // folders. Folder tiles can be selected in it, and in tag mode (only a folder shown as a series takes tags).
    property bool selectMode: false
    readonly property bool selecting: tagMode || selectMode
    // The host says what the page allows: virtual folder actions at all (not in a search from the top level),
    // being inside a virtual folder (so "Remove from virtual folder" makes sense), making one on empty space
    property bool virtualAllowed: false
    property bool virtualPage: false
    property bool canCreateHere: false
    property var selectedTiles: []
    property var tagBackend: null
    property var mediaBackend: null
    // The SubfolderModel behind the folder tiles (favorites and covers). The
    // tiles themselves arrive through this grid's own model, ahead of the files.
    property var subfolderBackend: null
    // BoardService, the tab whose boards "Add to board" offers, and the board this page shows (-1: none)
    property var boardBackend: null
    // HomeModel: "Pin to Home" on boards (folders, series and files go on Home through the favorites)
    property var homeBackend: null
    // MediaActions: show in the file manager, copy the path
    property var actionsBackend: null
    property string boardTab: ""
    property int boardId: -1
    // how pictures are laid out: rows (their own shape), columns or grid
    property string layoutMode: "rows"
    property var boardChoices: []
    property var selectedIds: []

    // Qt.UserRole + 1 in MediaModel: the `mediaId` role (also exposed to
    // delegates as model.mediaId). Keep in sync with the Python model.
    readonly property int mediaIdRole: 257

    property var contextMenuData: ({})

    onSelectingChanged: {
        if (!selecting) {
            selectedIds = []
            selectedTiles = []
        }
    }
    onSelectModeChanged: selectedTiles = []
    onTagModeChanged: if (!tagMode) selectedTiles = []

    // Folder tiles in the grid's rows: Qt.UserRole + 100 (isFolder) and + 101 (the tile's path or "virtual:<id>")
    readonly property int isFolderRole: 356
    readonly property int tilePathRole: 357
    readonly property int tileSeriesRole: 362
    readonly property int tileSingleIdRole: 366
    readonly property int tileBoardRole: 373

    function tileKeyAt(row) {
        var index = grid.model.index(row, 0)
        if (grid.model.data(index, grid.isFolderRole) !== true) return ""
        if (grid.model.data(index, grid.tileBoardRole) === true) return ""      // a board is not moved anywhere
        var key = String(grid.model.data(index, grid.tilePathRole))
        // only a folder shown as a series takes tags
        return grid.tagMode && grid.model.data(index, grid.tileSeriesRole) !== true ? "" : key
    }

    function setTiles(keys) {
        grid.selectedTiles = keys
        selectionChanged()
    }

    function toggleTile(key) {
        var keys = grid.selectedTiles.slice()
        var at = keys.indexOf(key)
        if (at >= 0) keys.splice(at, 1)
        else keys.push(key)
        setTiles(keys)
    }

    function clearSelection() {
        grid.selectedIds = []
        grid.selectedTiles = []
        selectionChanged()
    }

    // What a menu action applies to: the whole selection if the clicked thing is part of it, else just the thing
    function targetOf(mediaId, tileKey) {
        if (grid.selecting) {
            var inFiles = mediaId >= 0 && grid.selectedIds.indexOf(mediaId) >= 0
            var inTiles = tileKey !== "" && grid.selectedTiles.indexOf(tileKey) >= 0
            if (inFiles || inTiles) return { ids: grid.selectedIds.slice(), tiles: grid.selectedTiles.slice() }
        }
        return { ids: mediaId >= 0 ? [mediaId] : [], tiles: tileKey !== "" ? [tileKey] : [] }
    }

    // ---- Selection helpers ----------------------------------------------
    // Always assign a new array: mutating selectedIds in place doesn't notify
    // the bindings (tile highlights, the tag panel) that depend on it.

    function mediaIdAt(row) {
        var index = grid.model.index(row, 0)
        var id = grid.model.data(index, grid.mediaIdRole)
        if (grid.tagMode && (id === null || id === undefined)) {
            // a folder tile drawn as its one file is that file for tags
            var single = grid.model.data(index, grid.tileSingleIdRole)
            if (single !== null && single !== undefined && single >= 0) return single
        }
        return id
    }

    function rowOfMediaId(mediaId) {
        for (var i = 0; i < grid.count; i++) {
            if (mediaIdAt(i) === mediaId) return i
        }
        return -1
    }

    function setSelection(ids) {
        grid.selectedIds = ids
        selectionChanged()
    }

    function toggleSelection(mediaId) {
        var ids = grid.selectedIds.slice()
        var at = ids.indexOf(mediaId)
        if (at >= 0) ids.splice(at, 1)
        else ids.push(mediaId)
        setSelection(ids)
    }

    function addRangeSelection(fromRow, toRow) {
        var ids = grid.selectedIds.slice()
        var start = Math.min(fromRow, toRow)
        var end = Math.max(fromRow, toRow)
        for (var i = start; i <= end; i++) {
            var id = mediaIdAt(i)
            if (id !== null && id !== undefined && ids.indexOf(id) < 0) {
                ids.push(id)
            }
        }
        setSelection(ids)
    }

    function selectAll() {
        addRangeSelection(0, grid.count - 1)
        if (grid.selecting) {
            var keys = grid.selectedTiles.slice()
            for (var i = 0; i < grid.count; i++) {
                var key = tileKeyAt(i)
                if (key !== "" && keys.indexOf(key) < 0) keys.push(key)
            }
            setTiles(keys)
        }
    }

    // ---- Drag select (tag and select mode) ------------------------------------------
    // Dragging on the grid draws a rubber band and selects every file tile it
    // touches. A plain drag replaces the selection; with Ctrl or Shift held it
    // adds to what was selected. Dragging near
    // the top or bottom edge scrolls. A click without dragging still toggles a
    // single tile (the DragHandler only takes over after the drag threshold).

    property bool dragSelecting: false
    property point dragStart: Qt.point(0, 0)   // content coordinates
    property point dragEnd: Qt.point(0, 0)     // content coordinates
    property point dragView: Qt.point(0, 0)    // pointer, in viewport coordinates
    property var dragBase: []
    property var dragBaseTiles: []

    function viewToContent(p) {
        return Qt.point(p.x + grid.contentX, p.y + grid.contentY)
    }


    function sameIds(a, b) {
        if (a.length !== b.length) return false
        for (var i = 0; i < a.length; i++) {
            if (b.indexOf(a[i]) < 0) return false
        }
        return true
    }

    function updateDragSelection() {
        var x0 = Math.min(dragStart.x, dragEnd.x)
        var x1 = Math.max(dragStart.x, dragEnd.x)
        var y0 = Math.min(dragStart.y, dragEnd.y)
        var y1 = Math.max(dragStart.y, dragEnd.y)

        // the layout knows where every tile is (in its own coordinates: the content less the margins)
        var touched = tileRows.hitTest(x0 - grid.edge, y0 - grid.topPad, x1 - grid.edge, y1 - grid.topPad)
        var ids = dragBase.slice()
        var keys = dragBaseTiles.slice()
        for (var t = 0; t < touched.length; t++) {
            var row = touched[t]
            var id = mediaIdAt(row)
            if (id !== null && id !== undefined && ids.indexOf(id) < 0) ids.push(id)
            if (grid.selecting) {
                var key = tileKeyAt(row)
                if (key !== "" && keys.indexOf(key) < 0) keys.push(key)
            }
        }
        var changed = !sameIds(ids, selectedIds) || !sameIds(keys, selectedTiles)
        if (changed) {
            grid.selectedTiles = keys
            setSelection(ids)
        }
    }

    DragHandler {
        id: dragSelect
        enabled: grid.selecting
        target: null
        acceptedButtons: Qt.LeftButton

        onActiveChanged: {
            if (active) {
                grid.forceActiveFocus()
                var additive = centroid.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)
                grid.dragBase = additive ? grid.selectedIds.slice() : []
                grid.dragBaseTiles = additive ? grid.selectedTiles.slice() : []
                grid.dragStart = grid.viewToContent(centroid.pressPosition)
                grid.dragView = centroid.position
                grid.dragEnd = grid.viewToContent(centroid.position)
                grid.dragSelecting = true
                grid.updateDragSelection()
            } else {
                grid.dragSelecting = false
            }
        }

        onCentroidChanged: {
            if (!active) return
            grid.dragView = centroid.position
            grid.dragEnd = grid.viewToContent(centroid.position)
            grid.updateDragSelection()
        }
    }

    // Scroll while the pointer is held near the top or bottom edge
    Timer {
        interval: 16
        repeat: true
        running: grid.dragSelecting
        onTriggered: {
            var edge = 48
            var y = grid.dragView.y
            var dy = 0
            if (y < edge) dy = -(edge - y) / 3
            else if (y > grid.height - edge) dy = (y - (grid.height - edge)) / 3
            if (dy === 0) return
            var maxY = Math.max(grid.originY, grid.originY + grid.contentHeight - grid.height)
            var next = Math.max(grid.originY, Math.min(maxY, grid.contentY + dy))
            if (next === grid.contentY) return
            grid.contentY = next
            grid.dragEnd = grid.viewToContent(grid.dragView)
            grid.updateDragSelection()
        }
    }

    // The rubber band (a child of the Flickable, so it is in content coordinates)
    Rectangle {
        visible: grid.dragSelecting
        z: 100
        x: Math.min(grid.dragStart.x, grid.dragEnd.x)
        y: Math.min(grid.dragStart.y, grid.dragEnd.y)
        width: Math.abs(grid.dragEnd.x - grid.dragStart.x)
        height: Math.abs(grid.dragEnd.y - grid.dragStart.y)
        color: Qt.alpha(palette.highlight, 0.18)
        border.width: 1
        border.color: palette.highlight
    }

    // ---- Keyboard (tag and select mode) --------------------------------------------

    activeFocusOnTab: true
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_T && event.modifiers === Qt.NoModifier) {
            grid.browseTagsRequested()
            event.accepted = true
            return
        }
        if (!grid.selecting) return
        if (event.matches(StandardKey.SelectAll)) {
            grid.selectAll()
            event.accepted = true
        } else if (event.key === Qt.Key_Escape && (grid.selectedIds.length > 0 || grid.selectedTiles.length > 0)) {
            grid.clearSelection()
            event.accepted = true
        }
    }

    // ---- Context menu ---------------------------------------------------

    Menu {
        id: contextMenu

        // open it
        MenuItem {
            text: "Open"
            icon.name: "document-open"
            font.bold: true
            onTriggered: grid.openFileAt(grid.contextMenuData.kind, grid.contextMenuData.fileIndex)
        }
        MenuItem {
            text: "Open in system default"
            icon.name: "document-open"
            onTriggered: grid.openExternallyRequested(grid.contextMenuData.fileIndex)
        }
        MenuItem {
            text: "Play from beginning"
            icon.name: "media-skip-backward"
            visible: grid.contextMenuData.kind === "video" && grid.contextMenuData.resumable === true
            height: visible ? implicitHeight : 0
            onTriggered: grid.playFromStartRequested(grid.contextMenuData.fileIndex)
        }
        MenuSeparator {}

        // about it
        MenuItem {
            id: favoriteItem
            enabled: grid.mediaBackend !== null
            onTriggered: {
                var id = grid.contextMenuData.mediaId
                grid.mediaBackend.setFavorite(id, !grid.mediaBackend.getFavorite(id))
            }
        }
        MenuItem {
            text: "Edit tags"
            icon.name: "tag"
            onTriggered: {
                var id = grid.contextMenuData.mediaId
                // Right-clicking something already in a multi-selection keeps it
                if (!(grid.tagMode && grid.selectedIds.indexOf(id) >= 0)) {
                    grid.selectedIds = [id]
                }
                grid.editTagsRequested(id)
                grid.selectionChanged()
            }
        }
        MenuItem {
            text: "Metadata"
            icon.name: "help-about-symbolic"
            onTriggered: grid.metadataRequested(grid.contextMenuData.mediaId)
        }
        MenuSeparator {}

        // its picture as a cover
        Menu {
            title: "Cover"
            icon.name: "viewimage"
            // Uses this item as the cover of the folder being browsed: a picture as it is, a video a frame of it,
            // a manga or book its own first page
            MenuItem {
                id: coverItem
                text: "Use as folder cover"
                enabled: grid.mediaBackend !== null && typeof grid.mediaBackend.setFolderCover === "function"
                         && (grid.mediaBackend.folderPath !== "" || grid.mediaBackend.virtualId >= 0)   // not in search results
                ToolTip.visible: hovered && grid.contextMenuData.kind === "video"
                ToolTip.delay: 600
                ToolTip.text: "A frame of the video becomes the folder's cover"
                onTriggered: {
                    var kind = grid.contextMenuData.kind
                    var ok = grid.mediaBackend.setFolderCover(grid.contextMenuData.mediaId)
                    if (ok) toast.show("Folder cover updated")
                    else if (kind === "video") toast.show("Couldn't grab a frame (is ffmpeg installed?)")
                    else toast.show("Couldn't set the folder cover")
                }
            }
            MenuItem {
                text: "Choose cover page\u2026"
                icon.name: "view-preview"
                // only a comic or a book has pages to pick from
                enabled: grid.contextMenuData.kind === "comic" || grid.contextMenuData.kind === "ebook"
                onTriggered: grid.coverPickerRequested(grid.contextMenuData.mediaId)
            }
        }
        MenuSeparator {}

        // where it goes
        MenuItem {
            text: "Select"
            icon.name: "edit-select"
            visible: grid.virtualAllowed && !grid.selecting
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(grid.contextMenuData.mediaId, ""); grid.selectRequested(t.ids, t.tiles) }
        }
        MenuItem {
            text: "Add to board\u2026"
            icon.name: "view-media-favorite"
            visible: grid.boardBackend !== null
            height: visible ? implicitHeight : 0
            onTriggered: {
                boardPickMenu.ids = grid.targetOf(grid.contextMenuData.mediaId, "").ids
                grid.boardChoices = grid.boardBackend.boards(grid.boardTab).filter(function(b) { return b.id !== grid.boardId })
                boardPickMenu.popup()
            }
        }
        MenuItem {
            text: "Remove from board"
            icon.name: "list-remove"
            visible: grid.boardBackend !== null && grid.boardId >= 0
            height: visible ? implicitHeight : 0
            onTriggered: grid.boardBackend.removeMedia(grid.boardId, grid.targetOf(grid.contextMenuData.mediaId, "").ids)
        }
        MenuItem {
            text: "Add to virtual folder\u2026"
            icon.name: "folder-add"
            visible: grid.virtualAllowed
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(grid.contextMenuData.mediaId, ""); grid.virtualActionRequested("add", t.ids, t.tiles) }
        }
        MenuItem {
            text: "Add to new virtual folder\u2026"
            icon.name: "folder-new"
            visible: grid.virtualAllowed
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(grid.contextMenuData.mediaId, ""); grid.virtualActionRequested("addNew", t.ids, t.tiles) }
        }
        MenuItem {
            text: "Remove from virtual folder"
            icon.name: "go-up"
            visible: grid.virtualAllowed && grid.virtualPage
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(grid.contextMenuData.mediaId, ""); grid.virtualActionRequested("remove", t.ids, t.tiles) }
        }
        MenuSeparator {}

        // the file on disk
        MenuItem {
            text: "Show in file manager"
            icon.name: "system-file-manager"
            enabled: grid.actionsBackend !== null
            onTriggered: grid.actionsBackend.showInFileManager([grid.contextMenuData.uri])
        }
        MenuItem {
            text: "Copy path"
            icon.name: "edit-copy-path"
            enabled: grid.actionsBackend !== null
            onTriggered: { grid.actionsBackend.copyPaths([grid.contextMenuData.uri]); toast.show("Path copied") }
        }
        MenuItem {
            text: "Rename\u2026"
            icon.name: "edit-rename"
            onTriggered: grid.renameRequested(grid.contextMenuData.uri, grid.contextMenuData.name)
        }
        MenuSeparator {}
        MenuItem {
            text: "Move to Trash"
            icon.name: "user-trash"
            onTriggered: grid.trashRequested(grid.targetOf(grid.contextMenuData.mediaId, "").ids)
        }
    }

    // "Add to board": the tab's boards, and a new one
    Menu {
        id: boardPickMenu
        property var ids: []
        Instantiator {
            model: grid.boardChoices
            delegate: MenuItem {
                required property var modelData
                text: modelData.name
                onTriggered: {
                    grid.boardBackend.addMedia(modelData.id, boardPickMenu.ids)
                    toast.show("Added to \u201C" + modelData.name + "\u201D")
                }
            }
            onObjectAdded: function(i, item) { boardPickMenu.insertItem(i, item) }
            onObjectRemoved: function(i, item) { boardPickMenu.removeItem(item) }
        }
        MenuSeparator { visible: grid.boardChoices.length > 0 }
        MenuItem {
            text: "New board\u2026"
            icon.name: "list-add"
            onTriggered: grid.newBoardRequested(boardPickMenu.ids)
        }
    }

    // kind: "image", "video", "comic" or "ebook"
    function openContextMenu(mediaId, kind, fileIndex, resumable) {
        var uri = grid.mediaBackend ? grid.mediaBackend.getFileUri(fileIndex) : ""
        grid.contextMenuData = { mediaId: mediaId, kind: kind, fileIndex: fileIndex, resumable: resumable === true,
                                 uri: uri, name: decodeURIComponent(String(uri).split("/").pop()) }
        var isFavorite = grid.mediaBackend ? !!grid.mediaBackend.getFavorite(mediaId) : false
        favoriteItem.text = isFavorite ? "Remove from favorites" : "Add to favorites"
        favoriteItem.icon.name = isFavorite ? "non-starred-symbolic" : "starred-symbolic"
        contextMenu.popup()
    }

    // "Open" in a file's menu: what a click does
    function openFileAt(kind, fileIndex) {
        if (kind === "video") grid.videoClicked(fileIndex)
        else if (kind === "comic") grid.comicClicked(fileIndex)
        else if (kind === "ebook") grid.bookClicked(fileIndex)
        else grid.imageClicked(fileIndex)
    }

    // Right-click menu for a folder tile (a folder, a series, or a folder shown as its one file)
    Menu {
        id: subfolderMenu
        property string folderPath: ""
        property bool isFavorite: false
        property bool hasCustomCover: false
        property bool isSeries: false
        property bool isSingle: false
        property string singleFile: ""
        property int singleId: -1
        property bool isShow: false      // a series of videos
        readonly property string part: isShow ? "episode" : "chapter"
        property string heroPath: ""     // the picture this tile shows
        property string format: ""       // a series' format ("" when not said)
        property bool pinned: false      // pinned to Home
        readonly property bool canBeSeries: subfolderMenu.isSeries || (grid.subfolderBackend !== null
                     && (grid.subfolderBackend.filterMode === MediaModel.MangaOnly
                         || grid.subfolderBackend.filterMode === MediaModel.VideosOnly)
                     && !subfolderMenu.isSingle)

        // open it: what a click does first
        MenuItem {
            text: subfolderMenu.isSeries ? (subfolderMenu.isShow ? "Continue watching" : "Continue reading") : "Open"
            icon.name: subfolderMenu.isSeries ? "media-playback-start" : "document-open"
            font.bold: true
            onTriggered: {
                if (subfolderMenu.isSeries) grid.subfolderSeriesRequested(subfolderMenu.folderPath, "resume")
                else if (subfolderMenu.isSingle) grid.subfolderSingleFileRequested(subfolderMenu.folderPath)
                else grid.subfolderClicked(subfolderMenu.folderPath)
            }
        }
        MenuItem {
            text: "Start from the first " + subfolderMenu.part
            icon.name: "go-first"
            visible: subfolderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderSeriesRequested(subfolderMenu.folderPath, "first")
        }
        MenuItem {
            text: "Previous " + subfolderMenu.part
            icon.name: "go-previous"
            visible: subfolderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderSeriesRequested(subfolderMenu.folderPath, "previous")
        }
        MenuItem {
            text: "Next " + subfolderMenu.part
            icon.name: "go-next"
            visible: subfolderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderSeriesRequested(subfolderMenu.folderPath, "next")
        }
        MenuItem {
            text: subfolderMenu.isShow ? "Open series page" : (subfolderMenu.isSeries ? "Browse chapters" : "Browse folder")
            icon.name: "view-list-details"
            visible: subfolderMenu.isSeries || subfolderMenu.isSingle
            height: visible ? implicitHeight : 0
            onTriggered: subfolderMenu.isShow ? grid.showRequested(subfolderMenu.folderPath)
                                              : grid.subfolderClicked(subfolderMenu.folderPath)
        }
        MenuSeparator {}

        // about it
        MenuItem {
            text: subfolderMenu.isFavorite ? "Remove from favorites" : "Add to favorites"
            icon.name: subfolderMenu.isFavorite ? "non-starred-symbolic" : "starred-symbolic"
            enabled: grid.subfolderBackend !== null
            onTriggered: grid.subfolderBackend.setFavorite(subfolderMenu.folderPath, !subfolderMenu.isFavorite)
        }
        MenuItem {
            text: "Edit tags"
            icon.name: "tag"
            visible: subfolderMenu.isSeries || (subfolderMenu.isSingle && subfolderMenu.singleId >= 0)
            height: visible ? implicitHeight : 0
            onTriggered: {
                // a series is tagged as one item; a one-file folder is its file. The selection is set after
                // tag mode starts, which clears a stale one.
                grid.editTagsRequested(subfolderMenu.isSeries ? -1 : subfolderMenu.singleId)
                if (subfolderMenu.isSeries) {
                    grid.selectedIds = []
                    grid.selectedTiles = [subfolderMenu.folderPath]
                } else {
                    grid.selectedTiles = []
                    grid.selectedIds = [subfolderMenu.singleId]
                }
                grid.selectionChanged()
            }
        }
        // what kind of series this is: how the reader opens it (manga right to left, a webtoon as a strip...).
        // (A menu item that opens its own menu: a submenu cannot be hidden on the tiles it does not apply to.)
        MenuItem {
            text: "Format\u2026"
            icon.name: "view-filter"
            visible: subfolderMenu.isSeries && !subfolderMenu.isShow
            height: visible ? implicitHeight : 0
            onTriggered: formatSubmenu.popup()
        }
        MenuSeparator {}

        // its cover, and how it is shown
        Menu {
            title: "Cover"
            icon.name: "viewimage"
            // a tile drawn as a file (a series, or a folder holding one file) can lend its picture to the folder
            // you are in, like a loose file's "Use as folder cover"
            MenuItem {
                text: "Use as folder cover"
                enabled: (subfolderMenu.isSingle || subfolderMenu.isSeries) && subfolderMenu.heroPath !== ""
                         && grid.mediaBackend !== null && grid.mediaBackend.folderPath !== ""   // not in search results
                ToolTip.visible: hovered
                ToolTip.delay: 600
                ToolTip.text: "Use this picture as the cover of the folder you are in"
                onTriggered: {
                    if (grid.mediaBackend.setFolderCoverFromPath(subfolderMenu.heroPath)) toast.show("Folder cover updated")
                    else toast.show("Couldn't set the folder cover (a video needs ffmpeg)")
                }
            }
            MenuItem {
                text: "Choose cover page\u2026"
                icon.name: "view-preview"
                enabled: subfolderMenu.isSingle
                onTriggered: grid.subfolderCoverPickerRequested(subfolderMenu.singleFile)
            }
            MenuItem {
                text: "Choose cover image\u2026"
                enabled: grid.subfolderBackend !== null
                onTriggered: coverPicker.openCoverImageDialog(subfolderMenu.folderPath)
            }
            MenuItem {
                text: "Use default cover"
                icon.name: "edit-undo"
                enabled: subfolderMenu.hasCustomCover && grid.subfolderBackend !== null
                onTriggered: grid.subfolderBackend.clearCover(subfolderMenu.folderPath)
            }
        }
        MenuItem {
            text: subfolderMenu.isSeries ? "Stop treating as a series" : "Treat as a series"
            icon.name: "bookmarks-symbolic"
            visible: subfolderMenu.canBeSeries
            height: visible ? implicitHeight : 0
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: subfolderMenu.isSeries
                          ? "Go back to showing this as an ordinary folder you can open"
                          : (subfolderMenu.isShow || (grid.subfolderBackend !== null && grid.subfolderBackend.filterMode === MediaModel.VideosOnly)
                             ? "Treat this folder's videos as one series: one tile that opens where you left off"
                             : "Treat this folder's chapter files as one manga: one tile that opens where you left off")
            onTriggered: grid.subfolderBackend.setSeries(subfolderMenu.folderPath, !subfolderMenu.isSeries)
        }

        MenuSeparator { visible: grid.virtualAllowed }
        // where it goes
        MenuItem {
            text: "Select"
            icon.name: "edit-select"
            visible: grid.virtualAllowed && !grid.selecting
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, subfolderMenu.folderPath); grid.selectRequested(t.ids, t.tiles) }
        }
        MenuItem {
            text: "Add to virtual folder\u2026"
            icon.name: "folder-add"
            visible: grid.virtualAllowed
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, subfolderMenu.folderPath); grid.virtualActionRequested("add", t.ids, t.tiles) }
        }
        MenuItem {
            text: "Add to new virtual folder\u2026"
            icon.name: "folder-new"
            visible: grid.virtualAllowed
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, subfolderMenu.folderPath); grid.virtualActionRequested("addNew", t.ids, t.tiles) }
        }
        MenuItem {
            text: "Remove from virtual folder"
            icon.name: "go-up"
            visible: grid.virtualAllowed && grid.virtualPage
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, subfolderMenu.folderPath); grid.virtualActionRequested("remove", t.ids, t.tiles) }
        }
        MenuSeparator {}

        // the folder on disk
        MenuItem {
            text: "Show in file manager"
            icon.name: "system-file-manager"
            enabled: grid.actionsBackend !== null
            onTriggered: grid.actionsBackend.showInFileManager([subfolderMenu.folderPath])
        }
        MenuItem {
            text: "Copy path"
            icon.name: "edit-copy-path"
            enabled: grid.actionsBackend !== null
            onTriggered: { grid.actionsBackend.copyPaths([subfolderMenu.folderPath]); toast.show("Path copied") }
        }
    }

    // A series' format (opened from the folder menu's "Format...")
    Menu {
        id: formatSubmenu
        MenuItem {
            text: "Not set"
            checkable: true
            checked: subfolderMenu.format === ""
            onTriggered: grid.subfolderBackend.setFormat(subfolderMenu.folderPath, "")
        }
        MenuSeparator {}
        Instantiator {
            model: grid.subfolderBackend ? grid.subfolderBackend.formats() : []
            delegate: MenuItem {
                required property var modelData
                text: modelData.name
                checkable: true
                checked: subfolderMenu.format === modelData.key
                onTriggered: grid.subfolderBackend.setFormat(subfolderMenu.folderPath, modelData.key)
            }
            onObjectAdded: function(i, item) { formatSubmenu.insertItem(i + 2, item) }
            onObjectRemoved: function(i, item) { formatSubmenu.removeItem(item) }
        }
    }

    // Right-click menu for a virtual folder tile
    Menu {
        id: virtualMenu
        property int virtualId: -1
        property string virtualName: ""
        property bool hasCover: false

        MenuItem {
            text: "Rename\u2026"
            icon.name: "edit-rename"
            onTriggered: grid.virtualRenameRequested(virtualMenu.virtualId, virtualMenu.virtualName)
        }
        MenuItem {
            text: "Use default cover"
            icon.name: "edit-undo"
            enabled: virtualMenu.hasCover
            onTriggered: grid.virtualCoverResetRequested(virtualMenu.virtualId)
        }

        MenuSeparator { visible: grid.virtualAllowed }
        MenuItem {
            text: "Select"
            icon.name: "edit-select"
            visible: grid.virtualAllowed && !grid.selecting
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, "virtual:" + virtualMenu.virtualId); grid.selectRequested(t.ids, t.tiles) }
        }
        MenuItem {
            text: "Add to virtual folder\u2026"
            icon.name: "folder-add"
            visible: grid.virtualAllowed
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, "virtual:" + virtualMenu.virtualId); grid.virtualActionRequested("add", t.ids, t.tiles) }
        }
        MenuItem {
            text: "Add to new virtual folder\u2026"
            icon.name: "folder-new"
            visible: grid.virtualAllowed
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, "virtual:" + virtualMenu.virtualId); grid.virtualActionRequested("addNew", t.ids, t.tiles) }
        }
        MenuItem {
            text: "Remove from virtual folder"
            icon.name: "go-up"
            visible: grid.virtualAllowed && grid.virtualPage
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(-1, "virtual:" + virtualMenu.virtualId); grid.virtualActionRequested("remove", t.ids, t.tiles) }
        }
        MenuSeparator {}
        MenuItem {
            text: "Delete virtual folder"
            icon.name: "edit-delete"
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: "What is in it goes back where it was. No file is touched."
            onTriggered: grid.virtualDeleteRequested(virtualMenu.virtualId, virtualMenu.virtualName)
        }
    }

    // Right-click menu for a board tile
    Menu {
        id: boardMenu
        property int boardId: -1
        property string boardName: ""
        property bool pinned: false
        MenuItem {
            text: "Open"
            icon.name: "document-open"
            font.bold: true
            onTriggered: grid.boardClicked(boardMenu.boardId, boardMenu.boardName)
        }
        MenuSeparator {}
        MenuItem {
            text: "Edit search\u2026"
            icon.name: "edit-find"
            onTriggered: grid.boardEditRequested(boardMenu.boardId)
        }
        MenuItem {
            text: "Rename\u2026"
            icon.name: "edit-rename"
            onTriggered: grid.boardRenameRequested(boardMenu.boardId, boardMenu.boardName)
        }
        MenuItem {
            text: boardMenu.pinned ? "Unpin from Home" : "Pin to Home"
            icon.name: boardMenu.pinned ? "window-unpin" : "window-pin"
            visible: grid.homeBackend !== null
            height: visible ? implicitHeight : 0
            onTriggered: grid.homeBackend.setPinned("board", String(boardMenu.boardId), !boardMenu.pinned)
        }
        MenuSeparator {}
        MenuItem {
            text: "Delete board"
            icon.name: "edit-delete"
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: "A board holds no files: deleting it touches nothing else."
            onTriggered: grid.boardDeleteRequested(boardMenu.boardId, boardMenu.boardName)
        }
    }

    // Right-click on empty space
    Menu {
        id: emptyMenu
        MenuItem {
            text: "New board\u2026"
            icon.name: "list-add"
            visible: grid.boardBackend !== null
            height: visible ? implicitHeight : 0
            onTriggered: grid.newBoardRequested([])
        }
        MenuItem {
            text: "New virtual folder\u2026"
            icon.name: "folder-new"
            onTriggered: grid.newVirtualFolderRequested()
        }
    }
    TapHandler {
        acceptedButtons: Qt.RightButton
        enabled: grid.canCreateHere
        onTapped: emptyMenu.popup()
    }

    // Opens the image dialog for a subfolder's "Choose cover image..."
    FilePicker {
        id: coverPicker
        onCoverImageSelected: function(folderPath, imagePath) {
            if (grid.subfolderBackend) grid.subfolderBackend.setCoverFromFile(folderPath, imagePath)
        }
    }

    // ---- Toast -----------------------------------------------------------
    // A small message at the bottom of the window. It lives in the window's
    // overlay, not in the grid, so it never scrolls with the tiles.

    Timer {
        id: toastTimer
        interval: 2600
        onTriggered: toast.close()
    }

    Popup {
        id: toast
        property string message: ""

        parent: Overlay.overlay
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? parent.height - height - 48 : 0
        padding: 12
        modal: false
        focus: false
        closePolicy: Popup.NoAutoClose

        function show(text) {
            toast.message = text
            toast.open()
            toastTimer.restart()
        }

        background: Rectangle {
            radius: 8
            color: Qt.rgba(0, 0, 0, 0.8)
        }
        contentItem: Label {
            text: toast.message
            color: "white"
        }
    }

    // ---- Layout -----------------------------------------------------------

    TileRows {
        id: tileRows
        source: grid.model
        width: Math.max(0, grid.width - 2 * grid.edge)
        pictureHeight: grid.pictureHeight
        coverWidth: grid.coverWidth
        coverLabel: grid.coverLabel
        layoutMode: grid.layoutMode
        onLayoutUpdated: grid.syncViewport()
    }

    function syncViewport() {
        tileRows.setViewport(grid.contentY - grid.topPad, grid.height)
    }
    onContentYChanged: syncViewport()
    onHeightChanged: syncViewport()
    Component.onCompleted: syncViewport()

    contentWidth: width
    contentHeight: tileRows.contentHeight + 2 * topPad
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar {}

    // the rows near the window (TileRows adds and drops them as the page scrolls)
    Repeater {
        model: tileRows

        delegate: Item {
            id: rowItem
            required property string rowKind
            required property int rowStart
            required property real rowY
            required property real rowHeight
            required property real rowLabel
            required property var tileWidths
            required property var tileXs
            required property int tileCount
            required property string rowTitle

            x: grid.edge
            y: grid.topPad + rowY
            width: grid.width - 2 * grid.edge
            height: rowHeight + rowLabel

            // a group's title: on a tab's top level, whose loose files these are
            Text {
                visible: rowItem.rowKind === "header"
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 8
                text: rowItem.rowTitle
                color: palette.text
                opacity: 0.75
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }

            Repeater {
                model: rowItem.tileCount

                delegate: Item {
                    id: tile
                    required property int index
                    readonly property int itemIndex: rowItem.rowStart + index
                    // Row in the media model: the grid's rows start with the folder tiles
                    readonly property int fileIndex: itemIndex - (grid.model ? grid.model.folderCount : 0)
                    // everything about this tile, read again whenever a tile's data changed (a favorite, a bar)
                    readonly property var d: { tileRows.revision; return grid.model ? grid.model.get(itemIndex) : ({}) }
                    readonly property bool selected: grid.selecting && d.mediaId !== null && d.mediaId !== undefined
                                                     && grid.selectedIds.indexOf(d.mediaId) >= 0
                    readonly property real pictureHeight: rowItem.rowHeight
                    // the thumbnail to ask for: the tile's longer side in real pixels, rounded up to a cache size
                    readonly property int thumbSize: ThumbUri.tierFor(Math.ceil(Math.max(width, pictureHeight) * Screen.devicePixelRatio))

                    x: rowItem.tileXs[index]
                    width: rowItem.tileWidths[index]
                    height: rowItem.height

                    Loader {
                        anchors.fill: parent
                        sourceComponent: tile.d.isFolder === true ? folderTile
                                         : (rowItem.rowKind === "cover" ? bookTile : pictureTile)
                    }

                    Component {
                        id: folderTile
                        CollectionTile {
                            kind: tile.d.subfolderIsBoard === true ? "board"
                                  : tile.d.subfolderIsVirtual === true ? "virtual"
                                  : (tile.d.subfolderIsSeries === true ? "series"
                                  : (tile.d.subfolderSingleFile ? "single" : "folder"))
                            name: tile.d.subfolderName || ""
                            subtitle: grid.folderSubtitle(tile.d)
                            coverSource: tile.d.subfolderHero && tile.d.subfolderHero.length > 0
                                         ? ThumbUri.source(tile.d.subfolderHero) + grid.revisionSuffix : ""
                            collageSources: (tile.d.subfolderCollage || []).map(function(p) {
                                return ThumbUri.source(p) + grid.revisionSuffix })
                            thumbSize: tile.thumbSize
                            coverHeight: tile.pictureHeight
                            // a series: what is left (its one badge), a bar while partway, dimmed once done
                            badge: tile.d.subfolderIsSeries === true && tile.d.subfolderLeft > 0 ? String(tile.d.subfolderLeft) : ""
                            progress: tile.d.subfolderProgress || 0
                            finished: tile.d.subfolderFinished === true
                            picked: grid.selecting && (grid.selectedTiles.indexOf(String(tile.d.subfolderPath)) >= 0
                                || (grid.tagMode && tile.d.subfolderSingleFileId >= 0 && grid.selectedIds.indexOf(tile.d.subfolderSingleFileId) >= 0))
                            onClicked: function(mouse) { grid.folderTileClicked(tile.d, mouse) }
                        }
                    }

                    Component {
                        id: bookTile
                        BookTile {
                            source: tile.d.fileUri ? "image://thumbnail/" + tile.d.fileUri + grid.revisionSuffix : ""
                            thumbSize: tile.thumbSize
                            coverHeight: tile.pictureHeight
                            title: grid.titleOf(tile.d.fileName)
                            selected: tile.selected
                            onClicked: function(mouse) { grid.fileTileClicked(tile, mouse) }
                        }
                    }

                    Component {
                        id: pictureTile
                        PictureTile {
                            source: tile.d.fileUri ? ThumbUri.source(tile.d.fileUri) + grid.revisionSuffix : ""
                            thumbSize: tile.thumbSize
                            fileName: tile.d.fileName || ""
                            isVideo: tile.d.isVideo === true
                            isFavorite: !!tile.d.isFavorite
                            duration: tile.d.duration || 0
                            watchFraction: tile.d.watchFraction || 0
                            watched: tile.d.isWatched === true
                            selected: tile.selected
                            selecting: grid.selecting
                            onClicked: function(mouse) { grid.fileTileClicked(tile, mouse) }
                            onFavoriteToggled: if (grid.mediaBackend) grid.mediaBackend.setFavorite(tile.d.mediaId, !tile.d.isFavorite)
                        }
                    }
                }
            }
        }
    }

    // Under a folder tile: what it holds
    function folderSubtitle(d) {
        var n = d.subfolderCount || 0
        if (d.subfolderIsBoard === true) return "Board \u00B7 " + n
        if (d.subfolderSingleFile) return ""
        if (d.subfolderIsSeries) {
            var format = d.subfolderFormat ? d.subfolderFormat.charAt(0).toUpperCase() + d.subfolderFormat.slice(1) + " \u00B7 " : ""
            if (d.subfolderFinished === true) return format + (d.subfolderIsShow ? "Watched" : "Read")
            return format + n + (d.subfolderIsShow ? (n === 1 ? " episode" : " episodes") : (n === 1 ? " chapter" : " chapters"))
        }
        var parts = []
        // several library folders shown together: which one it is in (two "Set A" folders are told apart)
        if (d.subfolderSource) parts.push("in " + d.subfolderSource)
        if (d.subfolderIsVirtual === true) parts.push("Virtual folder")
        var folders = d.subfolderFolders || 0
        if (folders > 0) parts.push(folders + (folders === 1 ? " folder" : " folders"))
        if (n > 0) parts.push(n + (n === 1 ? " item" : " items"))
        return parts.join(" \u00B7 ")
    }

    // A folder tile was clicked: open it, select it, or show its menu
    function folderTileClicked(d, mouse) {
        if (d.subfolderIsBoard === true) {
            if (mouse.button === Qt.RightButton) {
                boardMenu.boardId = d.subfolderBoardId
                boardMenu.boardName = d.subfolderName
                boardMenu.pinned = grid.homeBackend ? grid.homeBackend.isPinned("board", String(d.subfolderBoardId)) : false
                boardMenu.popup()
            } else if (!grid.selecting) {
                grid.boardClicked(d.subfolderBoardId, d.subfolderName)
            }
            return
        }
        if (mouse.button === Qt.RightButton && d.subfolderIsVirtual === true) {
            virtualMenu.virtualId = d.subfolderVirtualId
            virtualMenu.virtualName = d.subfolderName
            virtualMenu.hasCover = grid.subfolderBackend ? grid.subfolderBackend.hasCustomCover(d.subfolderPath) : false
            virtualMenu.popup()
        } else if (mouse.button === Qt.RightButton) {
            subfolderMenu.folderPath = d.subfolderPath
            subfolderMenu.isFavorite = d.subfolderFavorite
            subfolderMenu.isSeries = !!d.subfolderIsSeries
            subfolderMenu.isShow = !!d.subfolderIsShow
            subfolderMenu.isSingle = !!d.subfolderSingleFile
            subfolderMenu.singleFile = d.subfolderSingleFile || ""
            subfolderMenu.singleId = d.subfolderSingleFileId
            subfolderMenu.heroPath = d.subfolderHero || ""
            subfolderMenu.format = d.subfolderFormat || ""
            subfolderMenu.pinned = grid.homeBackend ? grid.homeBackend.isPinned("folder", String(d.subfolderPath)) : false
            subfolderMenu.hasCustomCover = grid.subfolderBackend ? grid.subfolderBackend.hasCustomCover(d.subfolderPath) : false
            subfolderMenu.popup()
        } else if (grid.selecting) {
            grid.forceActiveFocus()
            var key = String(d.subfolderPath)
            if (grid.tagMode && d.subfolderIsSeries !== true) {
                // a one-file folder is its file: select it like a file tile
                if (d.subfolderSingleFileId >= 0) {
                    if (mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)
                            || grid.selectedIds.indexOf(d.subfolderSingleFileId) >= 0)
                        grid.toggleSelection(d.subfolderSingleFileId)
                    else
                        grid.setSelection([d.subfolderSingleFileId])
                }
                return
            }
            if (mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier) || grid.selectedTiles.indexOf(key) >= 0) {
                grid.toggleTile(key)
            } else {
                grid.selectedIds = []
                grid.setTiles([key])
            }
        } else if (d.subfolderIsVirtual === true) {
            grid.virtualFolderClicked(d.subfolderVirtualId, d.subfolderName)
        } else if (d.subfolderIsShow) {
            grid.showRequested(d.subfolderPath)
        } else if (d.subfolderIsSeries) {
            grid.subfolderSeriesRequested(d.subfolderPath, "resume")
        } else if (d.subfolderSingleFile) {
            grid.subfolderSingleFileRequested(d.subfolderPath)
        } else {
            grid.subfolderClicked(d.subfolderPath)
        }
    }

    // A comic's or book's title for under its cover: the file name without its extension
    function titleOf(fileName) {
        var name = String(fileName || "")
        var dot = name.lastIndexOf(".")
        return dot > 0 ? name.substring(0, dot) : name
    }

    // Routes a click on a file tile to whichever signal matches its type (or to the selection)
    function fileTileClicked(tile, mouse) {
        grid.forceActiveFocus()
        var d = tile.d
        if (mouse.button === Qt.RightButton) {
            grid.openContextMenu(d.mediaId,
                d.isVideo ? "video" : (d.isComic ? "comic" : (d.isBook ? "ebook" : "image")), tile.fileIndex,
                d.isVideo && d.watchFraction > 0 && !d.isWatched)
        } else if (grid.selecting) {
            if ((mouse.modifiers & Qt.ShiftModifier) && grid.selectedIds.length > 0) {
                // Range from the last selected item to this one
                var anchorRow = grid.rowOfMediaId(grid.selectedIds[grid.selectedIds.length - 1])
                if (anchorRow >= 0) grid.addRangeSelection(anchorRow, tile.itemIndex)
            } else if (mouse.modifiers & Qt.ControlModifier) {
                grid.toggleSelection(d.mediaId)
            } else if (grid.selectedIds.indexOf(d.mediaId) >= 0) {
                grid.toggleSelection(d.mediaId)
            } else {
                grid.selectedTiles = []
                grid.setSelection([d.mediaId])
            }
        } else if (d.isVideo) {
            grid.videoClicked(tile.fileIndex)
        } else if (d.isComic) {
            grid.comicClicked(tile.fileIndex)
        } else if (d.isBook) {
            grid.bookClicked(tile.fileIndex)
        } else {
            grid.imageClicked(tile.fileIndex)
        }
    }
}
