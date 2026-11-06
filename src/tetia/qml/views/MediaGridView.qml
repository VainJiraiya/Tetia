// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0
import "thumbUri.js" as ThumbUri

// The grid of media tiles. It is only the grid: the tag panel lives next to it
// in main.qml, so it never ends up inside this Flickable's scrolling content.
GridView {
    id: grid

    // Emitted when a tile is tapped, routed by the tapped item's own type
    // so callers don't have to re-check model roles themselves.
    signal imageClicked(int index)
    signal videoClicked(int index)
    signal comicClicked(int index)
    signal bookClicked(int index)
    signal openExternallyRequested(int index)   // "Open in system default" from the right-click menu
    signal selectionChanged()

    // A subfolder tile was tapped; folderPath is a file:// URI.
    signal subfolderClicked(string subfolderPath)
    // A series tile was opened: which chapter is "resume", "first", "next" or "previous"
    signal subfolderSeriesRequested(string subfolderPath, string which)
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
    signal virtualRenameRequested(int virtualId, string name)
    signal virtualDeleteRequested(int virtualId, string name)
    signal virtualCoverResetRequested(int virtualId)

    // A cover changed by hand: this number is added to the pictures' URLs so they reload
    property int coverRevision: 0
    readonly property string revisionSuffix: coverRevision > 0 ? "?v=" + coverRevision : ""

    // Tile size: -2 .. +2. The cell widths are 110, 140, 180, 265 and 350 px (kept the same in
    // FolderGridView, so a level is one size everywhere); the cell then stretches a little to fill the row.
    // thumbHint is the thumbnail size to ask for (0: no preference, so the biggest cached one). -2 and -1
    // use the normal (128 px) thumbnails; +1 and +2 ask for the large (256) and x-large (512) ones.
    property int tileLevel: 0
    readonly property real tileScale: [110, 140, 180, 265, 350][tileLevel + 2] / 160
    readonly property int thumbHint: [128, 128, 0, 256, 512][tileLevel + 2]
    // Even the smallest size is big enough for a (shortened) name
    readonly property bool showLabels: true

    // Exposed properties
    // Layout: one rule shared with FolderGridView (keep them in sync). A tile sits `inset` inside its cell, and
    // the grid keeps `edge` on the left and right, so a tile is edge + inset = 24 px from the wall and from the
    // header, whatever the tile size or the window. The cells stretch a little to fill the width, instead of
    // leaving a leftover gap that would grow and shrink with the tile size.
    readonly property real edge: 12
    readonly property real inset: 12
    readonly property real minCell: 160 * tileScale
    property int columns: Math.max(1, Math.floor((width - 2 * edge) / minCell))
    property real sidePadding: edge
    property bool tagMode: false
    // Select mode: the same click and drag selection as tag mode, for moving things into virtual
    // folders. Folder tiles can be selected in it (tag mode only tags files).
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
    onSelectModeChanged: {
        // folder tiles can only be selected in select mode
        if (!selectMode) selectedTiles = []
    }

    // Folder tiles in the grid's rows: Qt.UserRole + 100 (isFolder) and + 101 (the tile's path or "virtual:<id>")
    readonly property int isFolderRole: 356
    readonly property int tilePathRole: 357

    function tileKeyAt(row) {
        var index = grid.model.index(row, 0)
        return grid.model.data(index, grid.isFolderRole) === true ? String(grid.model.data(index, grid.tilePathRole)) : ""
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
        return grid.model.data(grid.model.index(row, 0), grid.mediaIdRole)
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
        if (grid.selectMode) {
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
    // adds to what was selected. Folder tiles are never selected. Dragging near
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

        // Tiles sit `inset` px inside their cells (see the delegates)
        var inset = grid.inset
        var firstCol = Math.max(0, Math.floor((x0 - sidePadding) / cellWidth))
        var lastCol = Math.min(columns - 1, Math.floor((x1 - sidePadding) / cellWidth))
        var firstRow = Math.max(0, Math.floor(y0 / cellHeight))
        var lastRow = Math.floor(y1 / cellHeight)

        var ids = dragBase.slice()
        var keys = dragBaseTiles.slice()
        for (var r = firstRow; r <= lastRow; r++) {
            for (var c = firstCol; c <= lastCol; c++) {
                var row = r * columns + c
                if (row >= grid.count) break
                var left = sidePadding + c * cellWidth + inset
                var top = r * cellHeight + inset
                if (left + cellWidth - 2 * inset <= x0 || left >= x1) continue
                if (top + cellHeight - 2 * inset <= y0 || top >= y1) continue
                var id = mediaIdAt(row)
                if (id !== null && id !== undefined && ids.indexOf(id) < 0) ids.push(id)
                if (grid.selectMode) {
                    var key = tileKeyAt(row)
                    if (key !== "" && keys.indexOf(key) < 0) keys.push(key)
                }
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
            text: "Open in system default"
            icon.name: "document-open"
            visible: grid.contextMenuData.kind === "comic" || grid.contextMenuData.kind === "ebook"
            height: visible ? implicitHeight : 0
            onTriggered: grid.openExternallyRequested(grid.contextMenuData.fileIndex)
        }

        MenuItem {
            text: "Metadata"
            icon.name: "help-about-symbolic"
            onTriggered: grid.metadataRequested(grid.contextMenuData.mediaId)
        }

        MenuItem {
            id: pickCoverItem
            text: "Choose cover page\u2026"
            icon.name: "view-preview"
            // only a comic or a book has pages to pick from
            visible: grid.contextMenuData.kind === "comic" || grid.contextMenuData.kind === "ebook"
            height: visible ? implicitHeight : 0
            onTriggered: grid.coverPickerRequested(grid.contextMenuData.mediaId)
        }

        MenuItem {
            id: favoriteItem
            enabled: grid.mediaBackend !== null
            onTriggered: {
                var id = grid.contextMenuData.mediaId
                grid.mediaBackend.setFavorite(id, !grid.mediaBackend.getFavorite(id))
            }
        }

        // Uses this item as the cover of the folder being browsed. The wording
        // follows the item: a picture is used as is, a video gives a frame, a
        // manga or book uses its own first page.
        MenuItem {
            id: coverItem
            icon.name: "image-x-generic"
            enabled: grid.mediaBackend !== null && typeof grid.mediaBackend.setFolderCover === "function"
                     && (grid.mediaBackend.folderPath !== "" || grid.mediaBackend.virtualId >= 0)   // not in search results
            onTriggered: {
                var kind = grid.contextMenuData.kind
                var ok = grid.mediaBackend.setFolderCover(grid.contextMenuData.mediaId)
                if (ok) {
                    toast.show("Folder cover updated")
                } else if (kind === "video") {
                    toast.show("Couldn't grab a frame (is ffmpeg installed?)")
                } else {
                    toast.show("Couldn't set the folder cover")
                }
            }
        }

        MenuSeparator { visible: grid.virtualAllowed }
        MenuItem {
            text: "Select"
            icon.name: "edit-select"
            visible: grid.virtualAllowed && !grid.selecting
            height: visible ? implicitHeight : 0
            onTriggered: { var t = grid.targetOf(grid.contextMenuData.mediaId, ""); grid.selectRequested(t.ids, t.tiles) }
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
    }

    // kind: "image", "video", "comic" or "ebook"
    function openContextMenu(mediaId, kind, fileIndex) {
        grid.contextMenuData = { mediaId: mediaId, kind: kind, fileIndex: fileIndex }
        var isFavorite = grid.mediaBackend ? !!grid.mediaBackend.getFavorite(mediaId) : false
        favoriteItem.text = isFavorite ? "Remove from favorites" : "Add to favorites"
        favoriteItem.icon.name = isFavorite ? "non-starred-symbolic" : "starred-symbolic"
        coverItem.text = kind === "video" ? "Use a frame as folder cover"
                       : (kind === "image" ? "Set as folder cover" : "Use as folder cover")
        contextMenu.popup()
    }

    // Right-click menu for a subfolder tile
    Menu {
        id: subfolderMenu
        property string folderPath: ""
        property bool isFavorite: false
        property bool hasCustomCover: false
        property bool isSeries: false
        property bool isSingle: false
        property string singleFile: ""
        property string heroPath: ""     // the picture this tile shows

        MenuItem {
            text: "Choose cover page\u2026"
            icon.name: "view-preview"
            visible: subfolderMenu.isSingle
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderCoverPickerRequested(subfolderMenu.singleFile)
        }
        MenuItem {
            text: "Browse folder"
            icon.name: "folder-open"
            visible: subfolderMenu.isSingle
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderClicked(subfolderMenu.folderPath)
        }
        MenuSeparator { visible: subfolderMenu.isSingle }
        MenuItem {
            text: "Open next chapter"
            icon.name: "go-next"
            visible: subfolderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderSeriesRequested(subfolderMenu.folderPath, "next")
        }
        MenuItem {
            text: "Open previous chapter"
            icon.name: "go-previous"
            visible: subfolderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderSeriesRequested(subfolderMenu.folderPath, "previous")
        }
        MenuItem {
            text: "Open first chapter"
            icon.name: "go-first"
            visible: subfolderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderSeriesRequested(subfolderMenu.folderPath, "first")
        }
        MenuItem {
            text: "Browse chapters"
            icon.name: "view-list-details"
            visible: subfolderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderClicked(subfolderMenu.folderPath)
        }
        MenuSeparator { visible: subfolderMenu.isSeries }
        MenuItem {
            text: subfolderMenu.isSeries ? "Show as a folder" : "Show as a series"
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: subfolderMenu.isSeries
                          ? "Go back to showing this as an ordinary folder you can open"
                          : "Treat this folder's chapter files as one manga: one tile that opens where you left off"
            icon.name: "bookmarks-symbolic"
            // Only manga folders hold chapters
            visible: grid.subfolderBackend !== null && grid.subfolderBackend.filterMode === MediaModel.MangaOnly
                     && !subfolderMenu.isSingle
            height: visible ? implicitHeight : 0
            onTriggered: grid.subfolderBackend.setSeries(subfolderMenu.folderPath, !subfolderMenu.isSeries)
        }
        // A tile drawn as a file (a series, or a folder holding one file) can lend its picture
        // to the folder you are in, like a loose file's "Use as folder cover"
        MenuItem {
            text: "Use as folder cover"
            icon.name: "image-x-generic"
            visible: (subfolderMenu.isSingle || subfolderMenu.isSeries) && subfolderMenu.heroPath !== ""
                     && grid.mediaBackend !== null && grid.mediaBackend.folderPath !== ""   // not in search results
            height: visible ? implicitHeight : 0
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: "Use this picture as the cover of the folder you are in"
            onTriggered: {
                if (grid.mediaBackend.setFolderCoverFromPath(subfolderMenu.heroPath)) {
                    toast.show("Folder cover updated")
                } else {
                    toast.show("Couldn't set the folder cover (a video needs ffmpeg)")
                }
            }
        }
        MenuItem {
            text: "Choose cover image\u2026"
            icon.name: "image-x-generic"
            enabled: grid.subfolderBackend !== null
            onTriggered: coverPicker.openCoverImageDialog(subfolderMenu.folderPath)
        }
        MenuItem {
            text: "Use default cover"
            icon.name: "edit-undo"
            enabled: subfolderMenu.hasCustomCover && grid.subfolderBackend !== null
            onTriggered: grid.subfolderBackend.clearCover(subfolderMenu.folderPath)
        }
        MenuSeparator {}
        MenuItem {
            text: subfolderMenu.isFavorite ? "Remove from favorites" : "Add to favorites"
            icon.name: subfolderMenu.isFavorite ? "non-starred-symbolic" : "starred-symbolic"
            enabled: grid.subfolderBackend !== null
            onTriggered: grid.subfolderBackend.setFavorite(subfolderMenu.folderPath, !subfolderMenu.isFavorite)
        }

        MenuSeparator { visible: grid.virtualAllowed }
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

    // Right-click on empty space
    Menu {
        id: emptyMenu
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

    // ---- Grid ------------------------------------------------------------

    // Cell height leaves room for both the picture and the file name
    cellWidth: (width - 2 * edge) / columns
    cellHeight: showLabels ? Math.round(cellWidth * 185 / 160) : cellWidth
    topMargin: edge
    bottomMargin: edge
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar {}

    // The delegate dictates how every individual item in the model is drawn
    delegate: Item {
        id: tile
        width: grid.cellWidth
        height: grid.cellHeight

        readonly property bool selected: grid.selecting && grid.selectedIds.indexOf(model.mediaId) >= 0

        // Row in the media model: the grid's rows start with the folder tiles
        readonly property int fileIndex: index - grid.model.folderCount


        // A subfolder tile, drawn like a file tile; the count badge marks it as a folder
        Component {
            id: folderCard

            Rectangle {
                id: folderTile
                // A series (a folder of chapters) or a folder holding one file is drawn exactly
                // like a single file: no outline, no bold name, and (series) the count badge only on hover
                readonly property bool asFile: model.subfolderIsSeries === true || !!model.subfolderSingleFile
                readonly property bool isVirtual: model.subfolderIsVirtual === true
                readonly property bool picked: grid.selectMode && grid.selectedTiles.indexOf(String(model.subfolderPath)) >= 0
                radius: 6
                color: picked ? Qt.alpha(palette.highlight, 0.18)
                              : Qt.alpha(palette.text, folderHover.hovered ? 0.07 : (asFile ? 0 : 0.03))
                border.width: picked ? 2 : (asFile ? 0 : 1)
                border.color: picked ? palette.highlight : Qt.alpha(palette.text, 0.15)

                HoverHandler {
                    id: folderHover
                    cursorShape: Qt.PointingHandCursor
                }

                ToolTip.visible: folderHover.hovered && !grid.showLabels
                ToolTip.delay: 700
                ToolTip.text: model.subfolderName || ""

                Image {
                    id: folderHero
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: folderNameText.top
                    anchors.margins: 4
                    anchors.bottomMargin: 6
                    source: model.subfolderHero && model.subfolderHero.length > 0
                            ? "image://thumbnail/" + ThumbUri.fromPath(model.subfolderHero) + grid.revisionSuffix : ""
                    sourceSize: grid.thumbHint > 0 ? Qt.size(grid.thumbHint, grid.thumbHint) : Qt.size(0, 0)
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }

                Kirigami.Icon {
                    anchors.centerIn: folderHero
                    width: Math.min(folderHero.width, folderHero.height) * 0.5
                    height: width
                    source: "folder"
                    opacity: 0.5
                    visible: folderHero.status !== Image.Ready && !folderTile.asFile
                }

                Rectangle {
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 6
                    width: folderCountText.implicitWidth + 14
                    height: folderCountText.implicitHeight + 8
                    radius: height / 2
                    color: Qt.rgba(0, 0, 0, 0.65)
                    // A series shows its chapter count only on hover: the one tell that it is not a single file
                    visible: model.subfolderCount > 0 && grid.showLabels && !model.subfolderSingleFile
                             && (!folderTile.asFile || folderHover.hovered) && !folderTile.picked

                    Text {
                        id: folderCountText
                        anchors.centerIn: parent
                        text: model.subfolderCount
                        color: "white"
                        font.pixelSize: 11
                        font.bold: true
                    }
                }

                // Marks a virtual folder (it exists only in Tetia)
                Rectangle {
                    // only on hover: on every tile it clutters the pictures
                    visible: folderTile.isVirtual && grid.showLabels && folderHover.hovered
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.margins: 6
                    width: virtualMark.implicitWidth + 12
                    height: virtualMark.implicitHeight + 6
                    radius: height / 2
                    color: Qt.rgba(0, 0, 0, 0.65)
                    Text {
                        id: virtualMark
                        anchors.centerIn: parent
                        text: "\u25C7"
                        color: "white"
                        font.pixelSize: 11
                        font.bold: true
                    }
                }

                // Selection check badge (top-right), like a file's
                Rectangle {
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 6
                    width: 20
                    height: 20
                    radius: 10
                    color: palette.highlight
                    visible: folderTile.picked
                    Text {
                        anchors.centerIn: parent
                        text: "\u2713"
                        color: palette.highlightedText
                        font.pixelSize: 12
                        font.bold: true
                    }
                }

                Text {
                    id: folderNameText
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 4
                    anchors.rightMargin: 4
                    text: model.subfolderName
                    color: palette.text
                    font.bold: !folderTile.asFile
                    font.pixelSize: 12
                    visible: grid.showLabels
                    height: grid.showLabels ? implicitHeight : 0
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideMiddle
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.RightButton && folderTile.isVirtual) {
                            virtualMenu.virtualId = model.subfolderVirtualId
                            virtualMenu.virtualName = model.subfolderName
                            virtualMenu.hasCover = grid.subfolderBackend
                                ? grid.subfolderBackend.hasCustomCover(model.subfolderPath) : false
                            virtualMenu.popup()
                        } else if (mouse.button === Qt.RightButton) {
                            subfolderMenu.folderPath = model.subfolderPath
                            subfolderMenu.isFavorite = model.subfolderFavorite
                            subfolderMenu.isSeries = !!model.subfolderIsSeries
                            subfolderMenu.isSingle = !!model.subfolderSingleFile
                            subfolderMenu.singleFile = model.subfolderSingleFile || ""
                            subfolderMenu.heroPath = model.subfolderHero || ""
                            subfolderMenu.hasCustomCover = grid.subfolderBackend
                                ? grid.subfolderBackend.hasCustomCover(model.subfolderPath) : false
                            subfolderMenu.popup()
                        } else if (grid.selectMode) {
                            grid.forceActiveFocus()
                            var key = String(model.subfolderPath)
                            if (mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier) || grid.selectedTiles.indexOf(key) >= 0) {
                                grid.toggleTile(key)
                            } else {
                                grid.selectedIds = []
                                grid.setTiles([key])
                            }
                        } else if (!grid.tagMode) {
                            if (folderTile.isVirtual) grid.virtualFolderClicked(model.subfolderVirtualId, model.subfolderName)
                            else if (model.subfolderIsSeries) grid.subfolderSeriesRequested(model.subfolderPath, "resume")
                            else if (model.subfolderSingleFile) grid.subfolderSingleFileRequested(model.subfolderPath)
                            else grid.subfolderClicked(model.subfolderPath)
                        }
                    }
                }
            }
        }

        // Shift the visual contents to center the whole block of columns
        // (avoids dynamic margins breaking the scroll position).
        Item {
            x: grid.sidePadding
            width: parent.width
            height: parent.height


            Loader {
                anchors.fill: parent
                anchors.margins: grid.inset
                active: model.isFolder === true
                sourceComponent: folderCard
            }

            Rectangle {
                id: card
                visible: !model.isFolder
                anchors.fill: parent
                anchors.margins: grid.inset
                radius: 6
                color: tile.selected ? Qt.alpha(palette.highlight, 0.18)
                                     : Qt.alpha(palette.text, hover.hovered ? 0.07 : 0)
                border.width: tile.selected ? 2 : 0
                border.color: palette.highlight

                HoverHandler {
                    id: hover
                    cursorShape: Qt.PointingHandCursor
                }

                ToolTip.visible: hover.hovered && (fileNameText.truncated || !grid.showLabels)
                ToolTip.delay: 700
                ToolTip.text: model.fileName || ""

                Image {
                    id: thumbnail
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: fileNameText.top
                    anchors.margins: 4
                    anchors.bottomMargin: 6

                    source: model.isFolder ? "" : "image://thumbnail/" + model.fileUri + grid.revisionSuffix
                    sourceSize: grid.thumbHint > 0 ? Qt.size(grid.thumbHint, grid.thumbHint) : Qt.size(0, 0)

                    // Scale down so the entire picture fits without cropping
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }

                Text {
                    id: fileNameText
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 4
                    anchors.rightMargin: 4

                    text: model.fileName || ""
                    color: palette.text
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideMiddle
                    font.pixelSize: 12
                    visible: grid.showLabels
                    height: grid.showLabels ? implicitHeight : 0
                }

                // Selection check badge (top-right)
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
                        text: "\u2713"
                        color: palette.highlightedText
                        font.pixelSize: 12
                        font.bold: true
                    }
                }

                // Routes the tap to whichever signal matches this item's type.
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton

                    onClicked: function(mouse) {
                        grid.forceActiveFocus()

                        if (mouse.button === Qt.RightButton) {
                            grid.openContextMenu(model.mediaId,
                                model.isVideo ? "video"
                                : (model.isComic ? "comic"
                                : (model.isBook ? "ebook" : "image")), tile.fileIndex)
                        } else if (grid.selecting) {
                            if ((mouse.modifiers & Qt.ShiftModifier) && grid.selectedIds.length > 0) {
                                // Range from the last selected item to this one
                                var anchorRow = grid.rowOfMediaId(grid.selectedIds[grid.selectedIds.length - 1])
                                if (anchorRow >= 0) {
                                    grid.addRangeSelection(anchorRow, index)
                                }
                            } else if (mouse.modifiers & Qt.ControlModifier) {
                                grid.toggleSelection(model.mediaId)
                            } else if (grid.selectedIds.indexOf(model.mediaId) >= 0) {
                                grid.toggleSelection(model.mediaId)
                            } else {
                                grid.selectedTiles = []
                                grid.setSelection([model.mediaId])
                            }
                        } else if (model.isVideo) {
                            grid.videoClicked(tile.fileIndex)
                        } else if (model.isComic) {
                            grid.comicClicked(tile.fileIndex)
                        } else if (model.isBook) {
                            grid.bookClicked(tile.fileIndex)
                        } else {
                            grid.imageClicked(tile.fileIndex)
                        }
                    }
                }
            }
        }
    }
}
