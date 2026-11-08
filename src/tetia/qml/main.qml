// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0
import "./views"
import "views/thumbUri.js" as ThumbUri

Kirigami.ApplicationWindow {
    id: root
    width: 900
    height: 700
    visible: true
    title: profileModel.isPrivate
           ? "Tetia \u2014 " + (profileModel.activeKind === "vault" ? "encrypted profile: " : "private profile: ") + profileModel.activeName
           : "Tetia"

    // Closing from an encrypted profile first locks its vault (the model quits when that's done)
    onClosing: function(close) {
        if (!profileModel.requestQuit()) close.accepted = false
    }

    pageStack {
        globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
        defaultColumnWidth: root.width
    }

    property bool isRemoveMode: false

    // Tile sizes, -2 .. +2 (0 is the usual size): five values in all. "top" is shared
    // by every collections grid; each category has its own "<category>.grid", used
    // inside any folder or subfolder. Saved in the profile ("tile.top",
    // "tile.photos.grid" and so on). Changed with Ctrl + wheel, Ctrl + / - / 0
    // (whichever grid is showing) or, for "top", the Tile Size menu.
    property var tileLevels: ({})
    function levelFor(key) {
        var level = tileLevels[key]
        return level === undefined ? 0 : level
    }
    function setTileLevel(key, level) {
        level = Math.max(-2, Math.min(2, level))
        if (levelFor(key) === level) return
        var levels = Object.assign({}, tileLevels)   // a new object, so bindings notice
        levels[key] = level
        tileLevels = levels
        uiSettings.setIntValue("tile." + key, level)
    }
    // Which size a resize applies to right now ("" when there is no grid to resize,
    // e.g. the image viewer or the Favorites tab)
    readonly property string tileTarget: {
        var page = pageStack.currentItem
        if (page && (page.isViewer === true || page.isReader === true)) return ""
        if (pageStack.depth <= 1) return root.onFavoritesTab ? "" : folderModel.currentCategory + ".grid"
        if (page && page.filterCategory !== undefined)
            return (page.filterCategory || folderModel.currentCategory) + ".grid"
        return ""
    }
    function stepTileLevel(delta) {
        if (tileTarget !== "") setTileLevel(tileTarget, levelFor(tileTarget) + delta)
    }

    function loadTileLevels() {
        var levels = { "top": uiSettings.intValue("tile.top", 0) }
        var categories = ["photos", "videos", "manga", "books"]
        for (var i = 0; i < categories.length; i++)
            levels[categories[i] + ".grid"] = uiSettings.intValue("tile." + categories[i] + ".grid", 0)
        tileLevels = levels
    }

    UiSettings { id: uiSettings }

    // Picking a cover page by hand. A change bumps coverRevision, which the grids add to their
    // picture URLs so the tile reloads (an image whose URL is unchanged keeps the old picture).
    property int coverRevision: 0
    CoverPicker {
        id: coverPicker
        onCoverChanged: root.coverRevision++
    }
    CoverPickerDialog {
        id: coverDialog
        picker: coverPicker
        onApplied: showPassiveNotification("Cover updated")
        onFailed: showPassiveNotification("That page could not be used as the cover")
    }
    function pickCoverOfMedia(mediaId) { if (coverPicker.open(mediaId)) coverDialog.open() }
    function pickCoverOfFile(path) { if (coverPicker.openPath(path)) coverDialog.open() }

    Shortcut { sequences: ["Ctrl++", "Ctrl+="]; enabled: root.tileTarget !== ""; onActivated: root.stepTileLevel(1) }
    Shortcut { sequence: "Ctrl+-"; enabled: root.tileTarget !== ""; onActivated: root.stepTileLevel(-1) }
    Shortcut { sequence: "Ctrl+0"; enabled: root.tileTarget !== ""; onActivated: root.setTileLevel(root.tileTarget, 0) }

    // Ctrl + wheel resizes the grid (see WheelZoom: a WheelHandler misses some wheels)
    WheelZoom {
        target: root
        enabled: root.tileTarget !== ""
        onStepped: function(delta) { root.stepTileLevel(delta) }
    }
    property bool isTagMode: false
    // Select mode: pick files and tiles to move into virtual folders (or to the Trash). Tag mode and select mode
    // are two ways of selecting and never on at once.
    property bool isSelectMode: false
    onIsTagModeChanged: if (isTagMode) isSelectMode = false
    onIsSelectModeChanged: if (isSelectMode) isTagMode = false

    // The search strip, and what the search page on the stack (if any) is showing
    property bool searchOpen: false
    property var searchState: null

    // The folder whose contents mediaModel currently holds; reloaded after a
    // delete so removed items disappear from the grid and the viewer.
    property var currentFolder: null
    // A tab's top level (the first page): the library folders of the tab, [{path, name}], and whether the shared
    // models hold that page now (they hold one page's contents at a time)
    property var sourceList: []
    // Whether the tag sidebar is open: one choice for every page, so closing it on one page and going back does
    // not bring it back on the page before
    property bool browseTagsOpen: false
    property bool rootShown: false
    // the board the shared models hold (-1: none)
    property int currentBoard: -1
    // The virtual folder mediaModel holds instead (-1: none); see loadVirtual
    property int currentVirtual: -1

    // The tags of the picture the image viewer shows, for the header; [] outside the viewer
    property var viewerTags: []
    function refreshViewerTags() {
        var page = pageStack.currentItem
        viewerTags = (page && page.isViewer === true && page.currentMediaId >= 0) ? tagModel.tagsShown(page.currentMediaId) : []
    }
    Connections {
        target: pageStack
        function onCurrentItemChanged() {
            var page = pageStack.currentItem
            if (page && page.isViewer === true && page.needsRestore === true) root.restoreViewerSource(page)
            root.refreshViewerTags()
            // back from the player: the bars and marks on the videos follow what was watched
            if (page && page.isGridPage === true) {
                mediaModel.refreshPlayback()
                subfolderModel.refreshProgress()       // and how far each series is
            }
        }
    }
    Connections {
        target: pageStack.currentItem
        ignoreUnknownSignals: true
        function onCurrentMediaIdChanged() { root.refreshViewerTags() }
    }
    Connections {
        target: tagModel
        function onTagsChanged() { root.refreshViewerTags() }
    }

    // Stack layout: 1 = folder grid (or the Favorites tab), 2 = folder contents
    // (or the viewer opened from Favorites), 3 = image viewer from a folder.
    readonly property bool onFavoritesTab: folderModel.currentCategory === "favorites"

    // Tag mode belongs to one page: leaving or entering a page always starts
    // with it off (the viewer re-enables it when its own panel opens).
    Connections {
        target: pageStack
        function onDepthChanged() {
            root.isTagMode = false
            root.isSelectMode = false
        }
    }

    // Persistent header defined at the ApplicationWindow level
    header: Column {
        id: headerColumn
        visible: !root.immersive

        ToolBar {
            width: headerColumn.width
        RowLayout {
            id: headerRow
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8

            // Both side slots always reserve this same width, whichever
            // side needs more (the mode button's text tends to be wider
            // than the icon-only left button). Keeping both slots equal
            // is what keeps the fillWidth title actually centered --
            // otherwise unequal side widths skew the centered midpoint.
            // Measured from the widest label ("Done") so the slots don't
            // resize when the button switches between "Tag" and "Done".
            readonly property real sideSlotWidth: Math.max(leftButton.implicitWidth, doneMetrics.width + 16 + 4 + 20, 40)
            // The sort button sits just left of the mode button. Its slot is also
            // reserved on the left (and when the button is hidden) so the title stays centred.
            readonly property real sortSlotWidth: 40
            readonly property int toolButtonCount: 3     // purge, browse tags and sort sit left of the mode button

            TextMetrics {
                id: doneMetrics
                text: "Done"
                font.weight: Font.Medium
            }

            // Dynamic Left Button (Menu vs. Back)
            Item {
                id: leftSlot
                Layout.preferredWidth: headerRow.sideSlotWidth + headerRow.sortSlotWidth * headerRow.toolButtonCount
                Layout.preferredHeight: leftButton.height

                // On a tag's results: one button that switches where the tag is looked for, between the library
                // folder it was clicked in and the whole tab. It names the place a click would switch to.
                Button {
                    id: scopeButton
                    objectName: "scopeButton"
                    anchors.left: leftButton.right
                    anchors.leftMargin: Kirigami.Units.smallSpacing
                    anchors.verticalCenter: parent.verticalCenter
                    visible: pageStack.currentItem !== null && pageStack.currentItem.isTagPage === true
                    readonly property var page: pageStack.currentItem
                    readonly property string folderName: (page && page.tagFolderName) || ""
                    readonly property string tabLabel: "All " + root.tabName(page ? page.filterCategory : "")
                    readonly property string current: !page ? ""
                        : (page.tagEverywhere ? "Everywhere" : (page.tagWholeTab || folderName === "" ? tabLabel : folderName))
                    text: (current.length > 24 ? current.slice(0, 23) + "\u2026" : current) + "  \u25BE"
                    focusPolicy: Qt.NoFocus
                    ToolTip.visible: hovered
                    ToolTip.delay: 500
                    ToolTip.text: "Where the tag is looked for"
                    onClicked: scopeMenu.popup(scopeButton, 0, scopeButton.height)
                    Menu {
                        id: scopeMenu
                        MenuItem {
                            text: "Only in \u201C" + scopeButton.folderName + "\u201D"
                            visible: scopeButton.folderName !== ""
                            height: visible ? implicitHeight : 0
                            checkable: true
                            checked: !!scopeButton.page && !scopeButton.page.tagWholeTab && !scopeButton.page.tagEverywhere
                            onTriggered: root.setTagScope(scopeButton.page, "folder")
                        }
                        MenuItem {
                            text: scopeButton.tabLabel
                            visible: !!scopeButton.page && scopeButton.page.filterCategory !== ""
                            height: visible ? implicitHeight : 0
                            checkable: true
                            checked: !!scopeButton.page && scopeButton.page.tagWholeTab && !scopeButton.page.tagEverywhere
                            onTriggered: root.setTagScope(scopeButton.page, "tab")
                        }
                        MenuItem {
                            text: "Everywhere (every kind of media)"
                            checkable: true
                            checked: !!scopeButton.page && scopeButton.page.tagEverywhere === true
                            onTriggered: root.setTagScope(scopeButton.page, "everywhere")
                        }
                    }
                }

                // In the image viewer: the picture's tags, starting beside the back button and reaching toward the
                // title. Only as many as fit before the title (or the profile mark), then "+N" with the rest.
                TagChipRow {
                    id: viewerTagRow
                    objectName: "viewerTags"
                    anchors.left: leftButton.right
                    anchors.leftMargin: Kirigami.Units.largeSpacing
                    anchors.verticalCenter: parent.verticalCenter
                    visible: root.viewerTags.length > 0
                    tags: root.viewerTags
                    // up to the title's left edge, or the start of the title area when the profile mark sits there
                    readonly property real limit: profileIndicator.visible
                        ? titleSlot.x - leftSlot.x - Kirigami.Units.smallSpacing
                        : titleSlot.x - leftSlot.x + (titleSlot.width - Math.min(titleText.contentWidth, titleSlot.width)) / 2 - Kirigami.Units.largeSpacing
                    available: Math.max(0, limit - leftButton.x - leftButton.width - Kirigami.Units.largeSpacing)
                    onTagClicked: function(category, name) { root.browseTagFromViewer(category, name) }
                }

                ToolButton {
                    id: leftButton
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    icon.name: pageStack.depth > 1 ? "go-previous" : "application-menu"
                    display: AbstractButton.IconOnly

                    property double lastClosedTime: 0

                    onClicked: {
                        if (pageStack.depth > 1 && pageStack.currentItem && pageStack.currentItem.isPurge === true) {
                            pageStack.currentItem.cancelRequested()    // the purge page decides (it asks first if needed)
                        } else if (pageStack.depth > 1) {
                            // Explicitly destroy the popped page rather than
                            // relying only on Kirigami's exit-transition-
                            // triggered cleanup. That cleanup is gated on the
                            // transition's running state actually toggling,
                            // which can fail to fire when the window is at
                            // its minimum size (there's no geometry left to
                            // animate through), leaving the popped page's
                            // MediaGridView orphaned but still alive on
                            // screen. Destroying it here is a hard guarantee
                            // regardless of what the transition does.
                            var poppedPage = pageStack.pop()
                            if (poppedPage) {
                                // Backing out of the results, or out of a folder with
                                // nothing typed in the search strip, closes the strip
                                if (poppedPage.isSearch === true || searchBar.isEmpty) {
                                    root.searchOpen = false
                                    searchBar.clearAll()
                                }
                                poppedPage.destroy()
                            }
                        } else {
                            if (Date.now() - lastClosedTime < 100) {
                                return
                            }
                            mainMenu.open()
                        }
                    }

                    Menu {
                        id: mainMenu
                        y: leftButton.height
                        onClosed: leftButton.lastClosedTime = Date.now()

                        MenuItem {
                            text: "New Board\u2026"
                            icon.name: "list-add"
                            enabled: !root.onFavoritesTab
                            onTriggered: root.newBoard([], folderModel.currentCategory)
                        }
                        MenuItem {
                            text: "Library Folders\u2026"
                            icon.name: "folder-add"
                            enabled: !root.onFavoritesTab
                            onTriggered: libraryDialog.open()
                        }
                        Menu {
                            title: "Tile Size"
                            enabled: root.tileTarget !== ""
                            MenuItem {
                                text: "Extra small"
                                icon.name: root.levelFor(root.tileTarget) === -2 ? "checkmark" : ""
                                onTriggered: root.setTileLevel(root.tileTarget, -2)
                            }
                            MenuItem {
                                text: "Small"
                                icon.name: root.levelFor(root.tileTarget) === -1 ? "checkmark" : ""
                                onTriggered: root.setTileLevel(root.tileTarget, -1)
                            }
                            MenuItem {
                                text: "Normal"
                                icon.name: root.levelFor(root.tileTarget) === 0 ? "checkmark" : ""
                                onTriggered: root.setTileLevel(root.tileTarget, 0)
                            }
                            MenuItem {
                                text: "Large"
                                icon.name: root.levelFor(root.tileTarget) === 1 ? "checkmark" : ""
                                onTriggered: root.setTileLevel(root.tileTarget, 1)
                            }
                            MenuItem {
                                text: "Extra large"
                                icon.name: root.levelFor(root.tileTarget) === 2 ? "checkmark" : ""
                                onTriggered: root.setTileLevel(root.tileTarget, 2)
                            }
                        }
                        MenuSeparator {}
                        MenuItem {
                            text: "Quit"
                            icon.name: "application-exit"
                            onTriggered: root.close()           // (a vault profile locks first, as on closing the window)
                        }
                        MenuItem {
                            text: "About Tetia"
                            icon.name: "help-about"
                            onTriggered: aboutDialog.open()
                        }
                        MenuItem {
                            text: "Profiles\u2026"
                            icon.name: "user-identity"
                            onTriggered: {
                                root.isRemoveMode = false
                                profilesDialog.open()
                            }
                        }
                    }
                }
            }

            // Dynamic Title (Reads from the active page)
            // On a folder page the title is a breadcrumb trail ("Starfall > Prologue");
            // every segment but the last pops back to that folder.
            Item {
                id: titleSlot
                Layout.fillWidth: true
                Layout.preferredHeight: leftButton.height

                readonly property var crumbs: pageStack.currentItem && pageStack.currentItem.crumbs
                                              ? pageStack.currentItem.crumbs : []

                // Always shows which profile you are in, if it isn't General
                Row {
                    id: profileIndicator
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4
                    visible: profileModel.isPrivate

                    Kirigami.Icon {
                        source: profileModel.activeKind === "vault" ? "lock" : "security-low"
                        width: 16
                        height: 16
                    }
                    Label {
                        visible: titleSlot.width > 560
                        width: Math.min(implicitWidth, 150)
                        text: profileModel.activeName
                        elide: Text.ElideRight
                        font.pixelSize: 12
                        opacity: 0.8
                    }
                }

                Label {
                    id: titleText
                    anchors.fill: parent
                    // centred on the whole header (like the window's own title), not on the room the buttons leave
                    readonly property real shift: headerRow.width / 2 - (titleSlot.x + titleSlot.width / 2)
                    anchors.leftMargin: Math.max(0, 2 * shift)
                    anchors.rightMargin: Math.max(0, -2 * shift)
                    visible: titleSlot.crumbs.length < 2
                    text: pageStack.currentItem && pageStack.currentItem.title ? pageStack.currentItem.title : "Collections"
                    font.pixelSize: 18
                    font.weight: Font.Normal
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                RowLayout {
                    anchors.centerIn: parent
                    width: Math.min(implicitWidth, titleSlot.width)
                    visible: titleSlot.crumbs.length >= 2
                    spacing: 6

                    Repeater {
                        model: titleSlot.crumbs

                        RowLayout {
                            id: crumb
                            readonly property bool isLast: index === titleSlot.crumbs.length - 1
                            spacing: 6

                            Label {
                                visible: index > 0
                                text: "\u203A"
                                font.pixelSize: 18
                                opacity: 0.6
                            }
                            Label {
                                text: modelData
                                font.pixelSize: 18
                                elide: Text.ElideRight
                                Layout.maximumWidth: Math.max(80, titleSlot.width / titleSlot.crumbs.length)
                                opacity: crumb.isLast ? 1.0 : 0.7
                                font.underline: !crumb.isLast && crumbArea.containsMouse

                                MouseArea {
                                    id: crumbArea
                                    anchors.fill: parent
                                    enabled: !crumb.isLast
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.popToCrumb(index)
                                }
                            }
                        }
                    }
                }
            }

            // Purge button: only on a folder of photos. Swipe through its pictures to keep or trash them.
            Item {
                Layout.preferredWidth: headerRow.sortSlotWidth
                Layout.preferredHeight: leftButton.height

                ToolButton {
                    objectName: "purgeButton"
                    anchors.centerIn: parent
                    icon.name: "edit-clear-all"
                    display: AbstractButton.IconOnly
                    visible: pageStack.currentItem !== null
                             && pageStack.currentItem.filterCategory === "photos"
                             && (pageStack.currentItem.isSearch === false || pageStack.currentItem.isTagPage === true)
                    ToolTip.visible: hovered
                    ToolTip.delay: 600
                    ToolTip.text: "Purge: swipe through these pictures to keep them or send them to the Trash"
                    onClicked: root.startPurge()
                }
            }

            // Browse tags: on every page of items (folders, virtual folders, search results)
            Item {
                Layout.preferredWidth: headerRow.sortSlotWidth
                Layout.preferredHeight: leftButton.height

                ToolButton {
                    objectName: "browseTagsButton"
                    anchors.centerIn: parent
                    icon.name: "tag"
                    display: AbstractButton.IconOnly
                    visible: pageStack.currentItem !== null && pageStack.currentItem.isGridPage === true
                             && !(root.onFavoritesTab && pageStack.depth === 1)
                    checkable: true
                    checked: pageStack.currentItem !== null && pageStack.currentItem.browseOpen === true
                    ToolTip.visible: hovered
                    ToolTip.delay: 600
                    ToolTip.text: "Browse by tag (T)"
                    onClicked: root.toggleBrowseTags()
                }
            }

            // Sort button: only on a folder's (or subfolder's) page, and on a tag's results. Search results
            // keep their ranking and the top-level tab lists folders, so neither has it.
            Item {
                Layout.preferredWidth: headerRow.sortSlotWidth
                Layout.preferredHeight: leftButton.height

                ToolButton {
                    id: sortButton
                    objectName: "sortButton"
                    anchors.centerIn: parent
                    icon.name: "view-sort"
                    display: AbstractButton.IconOnly
                    visible: pageStack.currentItem !== null
                             && pageStack.currentItem.filterCategory !== undefined
                             && (pageStack.currentItem.isSearch === false || pageStack.currentItem.isTagPage === true)
                             && !(root.onFavoritesTab && pageStack.depth === 1)
                    onClicked: sortMenu.popup(sortButton, 0, sortButton.height)

                    Menu {
                        id: sortMenu
                        readonly property var page: pageStack.currentItem
                        readonly property bool formats: !!page && page.isRoot === true
                                                        && (page.filterCategory === "manga" || page.filterCategory === "books")
                        // Manga and EBooks: show only the series of one format
                        MenuItem {
                            text: "Show all formats"
                            visible: sortMenu.formats
                            height: visible ? implicitHeight : 0
                            icon.name: sortMenu.formats && sortMenu.page.formatFilter === "" ? "checkmark" : ""
                            onTriggered: { sortMenu.page.formatFilter = ""; root.loadRoot() }
                        }
                        Instantiator {
                            model: subfolderModel.formats()
                            delegate: MenuItem {
                                required property var modelData
                                text: "Show only " + modelData.name
                                visible: sortMenu.formats
                                height: visible ? implicitHeight : 0
                                icon.name: sortMenu.formats && sortMenu.page.formatFilter === modelData.key ? "checkmark" : ""
                                onTriggered: { sortMenu.page.formatFilter = modelData.key; root.loadRoot() }
                            }
                            onObjectAdded: function(i, item) { sortMenu.insertItem(i + 1, item) }
                            onObjectRemoved: function(i, item) { sortMenu.removeItem(item) }
                        }
                        MenuSeparator { visible: sortMenu.formats }
                        // how pictures are laid out here (remembered for this folder, board or tab)
                        MenuItem {
                            text: "Layout: rows"
                            icon.name: sortMenu.page && sortMenu.page.layoutMode === "rows" ? "checkmark" : ""
                            onTriggered: root.chooseLayout(sortMenu.page, "rows")
                        }
                        MenuItem {
                            text: "Layout: columns"
                            icon.name: sortMenu.page && sortMenu.page.layoutMode === "columns" ? "checkmark" : ""
                            onTriggered: root.chooseLayout(sortMenu.page, "columns")
                        }
                        MenuItem {
                            text: "Layout: grid"
                            icon.name: sortMenu.page && sortMenu.page.layoutMode === "grid" ? "checkmark" : ""
                            onTriggered: root.chooseLayout(sortMenu.page, "grid")
                        }
                        MenuSeparator {}

                        MenuItem {
                            text: "Default"
                            icon.name: mediaModel.sortMode === MediaModel.Default ? "checkmark" : ""
                            onTriggered: mediaModel.sortMode = MediaModel.Default
                        }
                        MenuSeparator {}
                        MenuItem {
                            text: "Name, Z to A"
                            icon.name: mediaModel.sortMode === MediaModel.NameDescending ? "checkmark" : ""
                            onTriggered: mediaModel.sortMode = MediaModel.NameDescending
                        }
                        MenuItem {
                            text: "Newest first"
                            icon.name: mediaModel.sortMode === MediaModel.NewestFirst ? "checkmark" : ""
                            onTriggered: mediaModel.sortMode = MediaModel.NewestFirst
                        }
                        MenuItem {
                            text: "Oldest first"
                            icon.name: mediaModel.sortMode === MediaModel.OldestFirst ? "checkmark" : ""
                            onTriggered: mediaModel.sortMode = MediaModel.OldestFirst
                        }
                        MenuItem {
                            text: "Largest first"
                            icon.name: mediaModel.sortMode === MediaModel.LargestFirst ? "checkmark" : ""
                            onTriggered: mediaModel.sortMode = MediaModel.LargestFirst
                        }
                        MenuItem {
                            text: "Smallest first"
                            icon.name: mediaModel.sortMode === MediaModel.SmallestFirst ? "checkmark" : ""
                            onTriggered: mediaModel.sortMode = MediaModel.SmallestFirst
                        }
                    }
                }
            }

            // Dynamic Right Button. One pill that changes with the mode:
            //   remove mode          -> "Done" (red), leaves remove mode
            //   tag mode, select mode -> "Done" (accent), leaves the mode
            //   anywhere but the viewer -> "Search", opens the search strip
            // (tag mode is entered from a tile's right-click menu)
            // Built from plain primitives (Rectangle/Icon/Label/MouseArea)
            // rather than a QQC2 Button, since that avoids relying on
            // this style's Button implicit-size/background computation.
            Item {
                id: modeButtonSlot
                Layout.preferredWidth: headerRow.sideSlotWidth
                Layout.preferredHeight: leftButton.height

                readonly property bool canSearch: !(pageStack.currentItem && (pageStack.currentItem.isViewer === true || pageStack.currentItem.isPurge === true || pageStack.currentItem.isReader === true))
                readonly property string mode: root.isRemoveMode ? "remove"
                                             : (root.isTagMode || root.isSelectMode ? "tag"
                                             : (canSearch ? "idle" : ""))
                readonly property color fg: mode === "remove" ? Kirigami.Theme.negativeTextColor
                                          : (mode === "tag" ? Kirigami.Theme.highlightedTextColor
                                                            : Kirigami.Theme.textColor)

                Rectangle {
                    id: modeButtonBg
                    anchors.fill: parent
                    anchors.margins: 4
                    radius: 4
                    visible: modeButtonSlot.mode !== ""
                    color: modeButtonSlot.mode === "remove" ? Kirigami.Theme.negativeBackgroundColor
                         : (modeButtonSlot.mode === "tag" ? Kirigami.Theme.highlightColor
                                                          : Qt.alpha(Kirigami.Theme.textColor, modeMouseArea.containsMouse ? 0.14 : 0.07))
                    opacity: modeButtonSlot.mode === "idle" ? 1.0 : (modeMouseArea.containsMouse ? 1.0 : 0.85)

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: 4

                        Kirigami.Icon {
                            source: modeButtonSlot.mode === "idle" ? "system-search" : "checkmark"
                            isMask: true
                            color: modeButtonSlot.fg
                            Layout.preferredWidth: 13
                            Layout.preferredHeight: 13
                        }

                        Label {
                            text: modeButtonSlot.mode === "idle" ? "Search" : "Done"
                            color: modeButtonSlot.fg
                            font.pixelSize: 11
                            font.weight: Font.Medium
                        }
                    }

                    MouseArea {
                        id: modeMouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: modeButtonSlot.mode !== ""
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (modeButtonSlot.mode === "remove") {
                                root.isRemoveMode = false
                            } else if (modeButtonSlot.mode === "tag") {
                                // The grid hides its panel and clears its selection
                                // by itself; the viewer page watches isTagMode too.
                                root.isTagMode = false
                                root.isSelectMode = false
                            } else {
                                root.toggleSearch()
                            }
                        }
                    }
                }
            }
        }
        }

        SearchBar {
            id: searchBar
            width: headerColumn.width
            // out of the way on a show's page, back when the results are
            visible: root.searchOpen && !(pageStack.currentItem && (pageStack.currentItem.isShow === true || pageStack.currentItem.isReader === true))
            backend: searchModel
            indexing: searchModel.indexing
            scopeText: root.scopeName(root.currentSearchScope())
            onSearchRequested: function(query) { root.runSearch(query) }
            onCloseRequested: root.closeSearch()
        }
    }

    MediaModel {
        id: mediaModel
        filterMode: MediaModel.All
    }

    // Subfolders of whatever folder mediaModel holds, filtered the same way.
    SubfolderModel {
        id: subfolderModel
        filterMode: mediaModel.filterMode
    }

    // What the media grid shows: subfolder tiles first, then the files
    GridModel {
        id: gridModel
        objectName: "gridModel"
        media: mediaModel
        subfolders: subfolderModel
    }

    Connections {
        target: mediaModel
        function onFolderPathChanged() {
            if (mediaModel.sources.length === 0) subfolderModel.load(mediaModel.folderPath)
        }
    }

    FolderModel {
        id: folderModel
        currentCategory: "photos"
    }

    TagModel {
        id: tagModel
    }

    ProfileModel {
        id: profileModel
    }

    ProfilesDialog {
        id: profilesDialog
        backend: profileModel
    }

    VaultBusyDialog {
        id: vaultBusyDialog
        backend: profileModel
    }

    Connections {
        target: profileModel
        function onSwitchFailed(text) {
            showPassiveNotification(text)
        }
        function onVaultLost() {
            vaultLostDialog.open()
        }
    }

    // The vault was locked from outside (Dolphin, the Vaults applet, ...): the
    // private profile has nothing to work with any more.
    Kirigami.PromptDialog {
        id: vaultLostDialog
        title: "The vault was locked"
        subtitle: "\u201C" + profileModel.activeName + "\u201D was locked outside Tetia, so this profile can't continue. Tetia will go back to General."
        closePolicy: Popup.NoAutoClose
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Back to General"
                icon.name: "go-home"
                onTriggered: {
                    vaultLostDialog.close()
                    profileModel.leaveToGeneral()
                }
            }
        ]
    }

    SearchModel {
        id: searchModel
        // Searches opened before indexing finished fill in once it has
        onIndexFinished: root.refreshSearch()
    }

    Component.onCompleted: {
        loadTileLevels()
        folderModel.currentCategory = "favorites"           // Tetia opens on Home
        pageStack.push(mediaGridComponent, { isRoot: true, filterCategory: "" })
        root.loadRoot()
        searchModel.indexLibrary()
    }

    Shortcut {
        sequence: StandardKey.Find
        onActivated: if (!(pageStack.currentItem && (pageStack.currentItem.isViewer === true || pageStack.currentItem.isPurge === true || pageStack.currentItem.isReader === true))) root.openSearch()
    }

    MediaActions {
        id: mediaActions
    }

    // Shared by the grid's tag panel and the image viewer's.
    // Shown when files could not be moved to the Trash and there is something to tell the user
    // (see trash.py). Nothing was lost: the files are where they were.
    Kirigami.PromptDialog {
        id: trashProblemDialog

        property int failed: 0

        title: failed === 1 ? "Couldn't move 1 item to the Trash" : "Couldn't move " + failed + " items to the Trash"
        subtitle: mediaActions.trashProblem
                  + (mediaActions.trashFixCommand !== "" ? "\n\n" + mediaActions.trashFixCommand : "")
        standardButtons: Kirigami.Dialog.Close
        customFooterActions: [
            Kirigami.Action {
                text: "Copy command"
                icon.name: "edit-copy"
                visible: mediaActions.trashFixCommand !== ""
                onTriggered: {
                    clipboardHelper.text = mediaActions.trashFixCommand
                    clipboardHelper.selectAll()
                    clipboardHelper.copy()
                    showPassiveNotification("Command copied")
                }
            }
        ]
    }

    // QML has no clipboard of its own: a hidden TextEdit can copy its text
    TextEdit { id: clipboardHelper; visible: false }

    Kirigami.PromptDialog {
        id: trashDialog

        property var ids: []
        // Optional callback(removedIds), run after the delete finishes
        property var afterTrash: null

        title: ids.length === 1 ? "Move 1 item to the Trash?"
                                : "Move " + ids.length + " items to the Trash?"
        subtitle: "The files go to the system Trash, so you can restore them from there. Their tags and favorites are removed."
        standardButtons: Kirigami.Dialog.Cancel
        customFooterActions: [
            Kirigami.Action {
                text: "Move to Trash"
                icon.name: "edit-delete"
                onTriggered: {
                    trashDialog.close()
                    root.performTrash(trashDialog.ids, trashDialog.afterTrash)
                }
            }
        ]
    }

    // Virtual folders: the service holds the rules; the dialogs below ask the user a name or a place.
    VirtualFolderService {
        id: virtualFolders
        onChanged: root.reloadPage()
    }

    BoardService {
        id: boardService
        onChanged: root.reloadPage()
    }

    // A name for a new or renamed virtual folder
    Kirigami.PromptDialog {
        id: nameDialog
        objectName: "nameDialog"
        property var onNamed: null          // function(name): the error text, or "" when it worked
        property string problem: ""
        property string okText: ""          // the button's word ("" : Create, or Rename for a rename)
        property bool tagHints: false       // a search is typed: suggest tags for the word being typed
        standardButtons: Kirigami.Dialog.Cancel
        customFooterActions: [
            Kirigami.Action {
                text: nameDialog.okText !== "" ? nameDialog.okText : (nameDialog.title.indexOf("Rename") === 0 ? "Rename" : "Create")
                icon.name: "dialog-ok-apply"
                onTriggered: nameDialog.accept()
            }
        ]
        function accept() {
            var problem = nameDialog.onNamed ? nameDialog.onNamed(nameField.text) : ""
            if (problem === "") {
                nameDialog.close()
            } else {
                nameDialog.problem = problem
            }
        }
        onOpened: { nameDialog.problem = ""; nameField.forceActiveFocus(); nameField.selectAll() }

        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing
            TextField {
                id: nameField
                objectName: "nameField"
                Layout.fillWidth: true
                placeholderText: nameDialog.tagHints ? "Tags, e.g. character:raphtalia -rating:explicit" : "Name"
                maximumLength: nameDialog.tagHints ? 1000 : 100
                onAccepted: nameDialog.accept()
                // the word being typed (after the last space)
                readonly property string lastWord: text.substring(text.lastIndexOf(" ") + 1)
            }
            // A search being typed: tags that fit the word, to click instead of typing them out
            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                visible: nameDialog.tagHints && hintRepeater.count > 0
                Repeater {
                    id: hintRepeater
                    model: nameDialog.tagHints && nameField.lastWord.replace(/^[-~]+/, "").length >= 1
                           ? searchModel.suggest(nameField.lastWord).slice(0, 8) : []
                    delegate: Kirigami.Chip {
                        required property var modelData
                        text: modelData.label
                        closable: false
                        checkable: false
                        onClicked: {
                            var t = nameField.text
                            nameField.text = t.substring(0, t.lastIndexOf(" ") + 1) + modelData.insert + " "
                            nameField.forceActiveFocus()
                        }
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                visible: nameDialog.problem !== ""
                text: nameDialog.problem
                color: Kirigami.Theme.negativeTextColor
                wrapMode: Text.WordWrap
            }
        }
    }

    VirtualPickerDialog { id: virtualPicker; objectName: "virtualPicker" }

    Kirigami.PromptDialog {
        id: aboutDialog
        title: "Tetia " + Qt.application.version
        subtitle: "A media library for manga, images and video: one gallery for everything you like.\n\n"
                  + "Free software under the GNU General Public License, version 3 or later.\n"
                  + "github.com/VainJiraiya/Tetia"
        standardButtons: Kirigami.Dialog.Ok
    }

    LibraryDialog {
        id: libraryDialog
        folders: folderModel
        tabName: root.tabTitle(folderModel.currentCategory)
        onAddRequested: filePicker.openFolderDialog()
        onRemoveRequested: function(path) {
            folderModel.removeFolder(path)
            if (pageStack.depth === 1) root.loadRoot()
        }
    }

    FilePicker {
        id: filePicker
        onFolderSelected: function(selectedFolder) {
            // Favorites is a virtual tab, not a folder category
            if (root.onFavoritesTab) return
            folderModel.addFolder(selectedFolder, folderModel.currentCategory)
            if (pageStack.depth === 1) root.loadRoot()
            searchModel.indexLibrary()
        }
        onFolderRejected: function(problem) { showPassiveNotification(problem, 12000) }
    }

    footer: Kirigami.NavigationTabBar {
        id: navTabBar
        // Hidden while the image viewer is open -- switching categories
        // mid-zoom doesn't make sense, and the viewer wants the full window
        // height anyway. (Tested by page rather than by depth: opened from
        // the Favorites tab the viewer is at depth 2, not 3.) Hidden in purge
        // mode too: a tab would close it and drop the marks without asking.
        visible: !(pageStack.currentItem && (pageStack.currentItem.isViewer === true || pageStack.currentItem.isReader === true
                                             || pageStack.currentItem.isPurge === true))
        actions: [
            // Home (the internal key stays "favorites": the one tab that is not a kind of media)
            Kirigami.Action {
                icon.name: "go-home"
                text: "Home"
                checked: folderModel.currentCategory === "favorites"
                onTriggered: switchTab("favorites")
            },
            Kirigami.Action {
                // Not image-x-generic(-symbolic): in Breeze that falls back to a coloured
                // (green) file-type icon, unlike the single-colour icons of the other tabs
                icon.name: "viewimage"
                text: "Images"
                checked: folderModel.currentCategory === "photos"
                onTriggered: switchTab("photos")
            },
            Kirigami.Action {
                icon.name: "video-x-generic-symbolic"
                text: "Videos"
                checked: folderModel.currentCategory === "videos"
                onTriggered: switchTab("videos")
            },
            Kirigami.Action {
                icon.name: "bookmarks-symbolic"
                text: "Manga"
                checked: folderModel.currentCategory === "manga"
                onTriggered: switchTab("manga")
            },
            Kirigami.Action {
                icon.name: "view-readermode-symbolic"
                text: "EBooks"
                checked: folderModel.currentCategory === "books"
                onTriggered: switchTab("books")
            },
        ]
    }

    function requestTrash(ids, afterTrash) {
        if (!ids || ids.length === 0) return
        trashDialog.ids = ids
        trashDialog.afterTrash = afterTrash ? afterTrash : null
        trashDialog.open()
    }

    // Purge mode: swipe through the open folder's pictures; the marked ones go to the trash after a review.
    function startPurge() {
        var ids = mediaModel.imageIds()
        if (ids.length === 0) {
            showPassiveNotification("There are no pictures to purge here")
            return
        }
        root.isTagMode = false
        pageStack.push(purgeComponent, { mediaIds: ids, folderName: pageStack.currentItem.title })
    }

    Component {
        id: purgeComponent

        PurgeView {
            id: purgePage

            // The review was confirmed: the same code as Delete moves them (and explains a refusal)
            onTrashRequested: function(ids) {
                root.performTrash(ids, function(removed) { purgePage.trashFinished(removed) })
            }
            onFinished: function(message) {
                var popped = pageStack.pop()
                if (popped) popped.destroy()
                if (message !== "") showPassiveNotification(message)
            }
        }
    }

    // Opens a file: comics, PDFs and picture EPUBs in Tetia's reader (so progress and bookmarks are kept),
    // everything else in the system's default app
    ReaderSession { id: readerProbe }
    function openFile(uri) {
        if (uri === "") return
        if (readerProbe.canRead(uri)) pageStack.push(readerComponent, { location: uri })
        else if (playerProbe.canPlay(uri)) playVideos([{ uri: uri, name: "" }], 0, "", "")
        else Qt.openUrlExternally(uri)
    }

    Player { id: playerProbe }
    PlaybackStore { id: playbackStore }

    // A video of the page in the player, with the others of the page to step through
    function playVideoAt(index) {
        var videos = mediaModel.videoList()
        var at = -1
        for (var i = 0; i < videos.length; i++) if (videos[i].row === index) at = i
        if (at < 0 || !playerProbe.canPlay(videos[at].uri)) Qt.openUrlExternally(mediaModel.getFileUri(index))
        else root.playVideos(videos, at, "", "")
    }

    // The player, over the videos to step through: [{uri, name}] and the one to start with. A show gives its title and
    // folder (its episodes, and the arrows seek); anything else is browsed like the photo viewer.
    function playVideos(playlist, index, showTitle, showPath) {
        pageStack.push(playerComponent, { playlist: playlist, index: index, series: showTitle !== "",
                                          showTitle: showTitle, showPath: showPath })
    }
    // an episode of a show, from where its folder is: the player gets the whole show to step through
    function playEpisode(showPath, uri) {
        var uris = subfolderModel.episodeUris(showPath)
        var at = uris.indexOf(uri)
        if (at < 0 || !playerProbe.canPlay(uri)) { openFile(uri); return }
        playVideos(uris.map(function(u) { return { uri: u, name: "" } }), at, folderTitle(showPath), showPath)
    }
    // Fullscreen remembers what it came from, so a maximized window comes back maximized. A window manager can drop
    // a maximize request made in the very moment fullscreen ends (and fall back to the size from before maximizing),
    // so the request is repeated once the change has settled. "Maximized" is also recognised by size, since not
    // every desktop reports the state.
    property bool maximizedBeforeFullscreen: false
    function looksMaximized() {
        if (root.visibility === Window.Maximized) return true
        if (root.visibility !== Window.Windowed || !root.screen) return false
        return root.width >= root.screen.desktopAvailableWidth - 4 && root.height >= root.screen.desktopAvailableHeight - 4
    }
    function leaveReaderFullscreen() {
        if (root.visibility !== Window.FullScreen) return
        root.visibility = root.maximizedBeforeFullscreen ? Window.Maximized : Window.Windowed
        if (root.maximizedBeforeFullscreen) {
            root.restoringMaximized = true
            restoreMaximizedTimer.restart()
        }
    }
    // The desktop may first show the window at its old size; ask again the moment it says so (a timer alone
    // leaves that size on screen for a moment), and stop asking once it is maximized or the wait is over.
    property bool restoringMaximized: false
    onVisibilityChanged: {
        if (!restoringMaximized) return
        if (root.visibility === Window.Windowed) root.visibility = Window.Maximized
        else if (root.visibility === Window.Maximized) restoringMaximized = false
    }
    function toggleReaderFullscreen() {
        if (root.visibility === Window.FullScreen) {
            leaveReaderFullscreen()
        } else {
            root.maximizedBeforeFullscreen = looksMaximized()
            root.visibility = Window.FullScreen
        }
    }
    Timer {
        id: restoreMaximizedTimer
        interval: 600
        onTriggered: {
            root.restoringMaximized = false
            if (root.visibility === Window.Windowed) root.visibility = Window.Maximized
        }
    }
    readonly property bool immersive: pageStack.currentItem !== null && pageStack.currentItem.isReader === true
                                      && root.visibility === Window.FullScreen

    Component {
        id: playerComponent

        PlayerView {
            fullscreen: root.visibility === Window.FullScreen
            onFullscreenToggled: root.toggleReaderFullscreen()
            onLeaveRequested: {
                root.leaveReaderFullscreen()
                var popped = pageStack.pop()
                if (popped) popped.destroy()
            }
            onEpisodeStarted: function(uri) { subfolderModel.rememberEpisode(showPath, uri) }
        }
    }

    Component {
        id: showComponent

        ShowView {
            tagSource: tagModel
            folderSource: subfolderModel
            onPlayRequested: function(uri) { root.playEpisode(location, uri) }
            // a tag of the show: the videos with it, in a page of their own over the show
            onTagClicked: function(category, name) {
                root.runTagPage([{ category: category, name: name }],
                                { filterCategory: "videos", isTagPage: false, virtualId: -1,
                                  folderPath: location, homePath: "", searchScope: "" }, true)
            }
        }
    }

    Component {
        id: readerComponent

        ReaderView {
            id: readerPage
            fullscreen: root.visibility === Window.FullScreen
            onFullscreenToggled: root.toggleReaderFullscreen()
            onLeaveRequested: {
                root.leaveReaderFullscreen()
                var popped = pageStack.pop()
                if (popped) popped.destroy()
            }
            onOpenSystemRequested: function(location) {
                Qt.openUrlExternally(location.indexOf("file:") === 0 ? location : "file://" + encodeURI(location))
                leaveRequested()
            }
        }
    }

    function performTrash(ids, afterTrash) {
        var removed = mediaActions.moveToTrash(ids)
        // Reload so the model drops the removed items: the open folder, or
        // the Favorites lists when deleting from the viewer opened there
        if (root.currentFolder) {
            mediaModel.load_from_qurl(root.currentFolder)
        } else if (root.currentVirtual >= 0) {
            mediaModel.load_virtual_folder(root.currentVirtual)
            subfolderModel.loadVirtual(root.currentVirtual)
        } else if (root.searchState) {
            root.refreshSearch()
        } else if (root.rootShown) {
            root.loadRoot()
        }
        if (root.onFavoritesTab) {
            homeView.refresh()
        }
        if (afterTrash) {
            afterTrash(removed)
        }
        if (removed.length < ids.length) {
            var failed = ids.length - removed.length
            if (mediaActions.trashProblem !== "") {
                // a reason worth explaining (in the Flatpak: the Trash portal said no)
                trashProblemDialog.failed = failed
                trashProblemDialog.open()
            } else {
                showPassiveNotification("Couldn't move " + failed + (failed === 1 ? " item" : " items") + " to the Trash")
            }
        }
    }

    // ---- Virtual folders ----------------------------------------------------------------------------

    function askName(title, initial, onNamed, okText, tagHints) {
        nameDialog.title = title
        nameDialog.okText = okText || ""
        nameDialog.tagHints = tagHints === true
        nameDialog.onNamed = onNamed
        nameField.text = initial
        nameDialog.open()
    }

    function itemsText(count) {
        return count === 1 ? "1 item" : count + " items"
    }

    // What a move said: a result {moved, skipped} or {error}
    function reportMove(result, name) {
        if (result.error !== undefined) {
            showPassiveNotification(result.error)
            return
        }
        root.isSelectMode = false          // done: the items are in their virtual folder
        var text = "Moved " + itemsText(result.moved) + (name ? " to \u201C" + name + "\u201D" : "")
        if (result.skipped > 0) text += " (" + itemsText(result.skipped) + " could not go there)"
        showPassiveNotification(text)
    }

    // Put a selection in an existing virtual folder, or make one for it. `parent` is the virtual folder the
    // new one goes inside (-1: at the top of `home`).
    function addToVirtual(ids, tiles, createNew, parent) {
        var options = virtualFolders.options(ids, tiles)
        if (!options.canCreate && options.targets.length === 0) {
            showPassiveNotification("These items are in different library folders, so they cannot go in one virtual folder.")
            return
        }
        var makeNew = function() {
            askName("New virtual folder", "", function(name) {
                var result = virtualFolders.placeInNew(name, parent, options.home, ids, tiles)
                if (result.error !== undefined) return result.error
                root.reportMove(result, name.trim())
                return ""
            })
        }
        if (createNew) {
            makeNew()
            return
        }
        virtualPicker.targets = options.targets
        virtualPicker.count = ids.length + tiles.length
        virtualPicker.canCreate = options.canCreate
        virtualPicker.onChosen = null
        virtualPicker.openFor(function(id, name) {
            root.reportMove(virtualFolders.place(id, ids, tiles), name)
        }, makeNew)
    }

    function removeFromVirtual(ids, tiles) {
        var count = virtualFolders.remove(ids, tiles)
        showPassiveNotification(count === 0 ? "Nothing to move out" : "Moved " + itemsText(count) + " out of the virtual folder")
    }

    function gridCategory(category) {
        if (category === "photos") mediaModel.filterMode = MediaModel.ImagesOnly
        else if (category === "videos") mediaModel.filterMode = MediaModel.VideosOnly
        else if (category === "manga") mediaModel.filterMode = MediaModel.MangaOnly
        else if (category === "books") mediaModel.filterMode = MediaModel.BooksOnly
        else mediaModel.filterMode = MediaModel.All
    }

    // Makes mediaModel and subfolderModel hold this virtual folder
    function loadVirtual(virtualId, category) {
        root.rootShown = false
        root.currentBoard = -1
        subfolderModel.boardsTab = ""
        root.currentFolder = null
        root.currentVirtual = virtualId
        gridCategory(category)
        mediaModel.load_virtual_folder(virtualId)
        subfolderModel.loadVirtual(virtualId)
    }

    function openVirtualFolder(virtualId, name, category, parentCrumbs) {
        loadVirtual(virtualId, category)
        var info = virtualFolders.info(virtualId)
        pageStack.push(mediaGridComponent, {
            title: name,
            virtualId: virtualId,
            homePath: info.home,
            filterCategory: category,
            crumbs: (parentCrumbs || []).concat(["[" + name + "]"])
        })
    }

    // Reloads what the page on top shows, after virtual folders changed or files were trashed
    function reloadPage() {
        var page = pageStack.currentItem
        if (!page || page.isGridPage !== true) return
        if (page.virtualId >= 0) {
            if (virtualFolders.info(page.virtualId).name === undefined) {
                // this virtual folder was deleted: step out of it
                var popped = pageStack.pop()
                if (popped) popped.destroy()
                return
            }
            loadVirtual(page.virtualId, page.filterCategory)
        } else if (page.boardId >= 0) {
            var info = boardService.info(page.boardId)
            if (info.id === undefined) {
                var gone = pageStack.pop()                      // this board was deleted: step out of it
                if (gone) gone.destroy()
                return
            }
            page.boardInfo = info
            page.title = info.name
            loadBoard(page.boardId, page.filterCategory)
        } else if (page.isSearch) {
            refreshSearch()
        } else if (page.isRoot) {
            loadRoot()
        } else if (page.folderPath) {
            loadFolder(page.folderPath, page.filterCategory)
        }
    }

    // Makes mediaModel hold a board's files (and no tiles)
    function loadBoard(boardId, category) {
        root.rootShown = false
        root.currentFolder = null
        root.currentVirtual = -1
        root.currentBoard = boardId
        subfolderModel.boardsTab = ""
        subfolderModel.formatFilter = ""
        gridCategory(category)
        mediaModel.load_media_ids_sorted(boardService.memberIds(boardId))
        subfolderModel.loadSeries([])
    }

    function openBoard(boardId, name) {
        var info = boardService.info(boardId)
        var category = info.tab || ""
        loadBoard(boardId, category)
        pageStack.push(mediaGridComponent, {
            title: name,
            boardId: boardId,
            boardInfo: info,
            filterCategory: category,
            layoutMode: info.layout || "rows",
            crumbs: [name]
        })
    }

    // A board's search (a tag search, like the search bar's)
    function editBoardSearch(boardId) {
        var info = boardService.info(boardId)
        askName("Board search (tags, like the search bar)", info.query || "", function(query) {
            boardService.setQuery(boardId, query)
            return ""
        }, "Save", true)
    }

    // A new board (put these files on it), then open it
    function newBoard(ids, category) {
        askName("New board", "", function(name) {
            if (name.trim() === "") return "Give the board a name"
            var id = boardService.create(name, "", category || "")
            if (id < 0) return "Couldn't make the board"
            if (ids && ids.length > 0) boardService.addMedia(id, ids)
            openBoard(id, name)
            return ""
        })
    }

    // Where a page's layout choice is kept ("" for none: a search, or a board, which keeps its own)
    function layoutKey(page) {
        if (!page || page.isGridPage !== true || page.isSearch || page.boardId >= 0) return ""
        if (page.virtualId >= 0) return "layout.virtual." + page.virtualId
        if (page.isRoot && !page.folderPath) return "layout.top." + folderModel.currentCategory
        return page.folderPath ? "layout." + String(page.folderPath) : ""
    }
    readonly property var layoutModes: ["rows", "columns", "grid"]
    function chooseLayout(page, mode) {
        if (!page) return
        page.layoutMode = mode
        if (page.boardId >= 0) boardService.setLayout(page.boardId, mode)
        else if (layoutKey(page) !== "") uiSettings.setIntValue(layoutKey(page), layoutModes.indexOf(mode))
    }
    // A page's layout: the one chosen for it, else columns when most of its pictures are tall, else rows
    function applyLayout(page) {
        var key = layoutKey(page)
        if (key === "") return
        var chosen = uiSettings.intValue(key, -1)
        page.layoutMode = chosen >= 0 ? layoutModes[chosen] : (gridModel.mostlyTall() ? "columns" : "rows")
    }

    function tabTitle(category) {
        return ({ photos: "Images", videos: "Videos", manga: "Manga", books: "EBooks", favorites: "Home" })[category] || ""
    }

    // A tab's top level: what is in all its library folders together (their folders and series, then each
    // one's loose files under its name), or one of them alone (a chip, or a tab with a single folder)
    function loadRoot() {
        var page = pageStack.get(0)
        var category = folderModel.currentCategory
        var groups = folderModel.sourceGroups()
        root.sourceList = groups.all
        root.currentVirtual = -1
        if (page) {
            page.title = tabTitle(category)
            page.filterCategory = category === "favorites" ? "" : category
        }
        gridCategory(category)
        root.currentBoard = -1
        subfolderModel.formatFilter = page ? page.formatFilter : ""
        subfolderModel.boardsTab = category === "favorites" ? "" : category
        if (page) page.continueItems = folderModel.continueReading(8)
        var active = page ? page.activeSource : ""
        if (active !== "" && !groups.all.some(function(s) { return s.path === active })) {
            active = ""                                  // that folder left the library
            if (page) page.activeSource = ""
        }
        if (active === "" && groups.expand.length === 1 && groups.tiles.length === 0) active = groups.expand[0]
        if (category !== "favorites" && active !== "") {
            root.currentFolder = active
            if (page) page.folderPath = active
            mediaModel.openFolder(active)
        } else {
            root.currentFolder = null
            if (page) page.folderPath = null
            var expand = category === "favorites" ? [] : groups.expand
            mediaModel.openSources(expand)
            subfolderModel.loadSources(expand, category === "favorites" ? [] : groups.tiles)
        }
        root.rootShown = true
    }

    function switchTab(category) {
        folderModel.currentCategory = category
        root.currentFolder = null
        root.currentVirtual = -1
        root.isSelectMode = false
        root.isRemoveMode = false
        root.isTagMode = false

        while (pageStack.depth > 1) {
            var poppedPage = pageStack.pop()
            if (poppedPage) {
                poppedPage.destroy()
            }
        }
        var top = pageStack.get(0)
        if (top) top.activeSource = ""
        root.loadRoot()
    }

    // ---- Search ----------------------------------------------------------
    // Inside a folder page the search covers that folder and everything below
    // it; anywhere else it covers the whole library.

    function searchPage() {
        var page = pageStack.currentItem
        return (page && page.isSearch === true) ? page : null
    }

    function currentSearchScope() {
        var page = pageStack.currentItem
        if (page && page.isSearch === true) return page.searchScope
        if (page && page.isGridPage === true && page.virtualId >= 0) return page.homePath
        if (page && page.isGridPage === true && page.folderPath) return String(page.folderPath)
        return ""
    }

    function scopeName(scope) {
        return scope === "" ? "all collections" : "\u201C" + folderTitle(scope) + "\u201D and its subfolders"
    }

    function openSearch() {
        root.searchOpen = true
        searchBar.focusField()
    }

    function toggleSearch() {
        if (root.searchOpen) root.closeSearch()
        else root.openSearch()
    }

    function searchTitle(query, count) {
        // a tag page is titled by its tag, not as a search
        if (root.searchState && root.searchState.label) return root.searchState.label + " \u00B7 " + itemsText(count)
        return "Search: " + query + " (" + count + ")"
    }

    // Hits as {ids, series}: the series a search found are tiles, not their chapters (see SearchModel.searchHits)
    function showHits(hits, sorted) {
        root.rootShown = false
        root.currentBoard = -1
        subfolderModel.boardsTab = ""
        if (sorted) mediaModel.load_media_ids_sorted(hits.ids)
        else mediaModel.load_media_ids(hits.ids)
        subfolderModel.loadSeries(hits.series)    // after the media: loading them closes the folder, which clears the tiles
        return hits.ids.length + hits.series.length
    }

    function runSearch(query) {
        if (query.trim() === "") {
            leaveSearch()
            return
        }
        var scope = currentSearchScope()
        var hits = searchModel.searchHits(query, scope, "")
        root.searchState = { query: query, scope: scope }
        var page = searchPage()
        if (page) {
            var count = showHits(hits, false)
            page.title = searchTitle(query, count)
            page.isTagPage = false        // a typed search keeps its own ranking
            page.browsedTags = []
            page.savedSearch = root.searchState
        } else {
            root.currentFolder = null
            root.currentVirtual = -1
            mediaModel.filterMode = MediaModel.All   // results are never narrowed by a folder tab's filter
            var total = showHits(hits, false)
            pageStack.push(mediaGridComponent, {
                title: searchTitle(query, total),
                isSearch: true,
                searchScope: scope,
                savedSearch: root.searchState,   // (the page puts it back whenever it is on top)
                browseOpen: true                 // the tags of the results, to narrow them down (like a booru)
            })
        }
    }

    // ---- Browsing by tag ------------------------------------------------------------------------------

    function toggleBrowseTags() {
        var page = pageStack.currentItem
        if (!page || page.isGridPage !== true) return
        page.browseOpen = !page.browseOpen
        if (page.browseOpen) {
            // the panels share one spot
            root.isTagMode = false
            page.metadataMediaId = -1
        }
    }

    // Shows the items with the chosen tags, staying in the grid: in the library folder this page is in, and in
    // the same kind of items (the tab). Clicking a tag chooses it; on a page that already shows the results of
    // tags, the next tag narrows them. The tag browser stays open: it is closed only by its own button.
    // A tag as a search term (quoted when it has spaces)
    function tagTerm(category, name) {
        return category + ":" + (name.indexOf(" ") >= 0 ? '"' + name + '"' : name)
    }

    // The "-" on a tag in the sidebar: the same items without the ones that have it
    function excludeTag(category, name) {
        var page = pageStack.currentItem
        if (!page || page.isGridPage !== true) return
        var base = ""
        if (page.isSearch && !page.isTagPage && root.searchState) base = root.searchState.query
        else if (page.isTagPage) base = page.browsedTags.map(function(t) { return tagTerm(t.category, t.name) }).join(" ")
        runSearch((base + " -" + tagTerm(category, name)).trim())
    }

    function browseTag(category, name) {
        var page = pageStack.currentItem
        if (!page || page.isGridPage !== true) return
        // a typed search: the tag narrows it, like a booru's "+"
        if (page.isSearch && !page.isTagPage && root.searchState) {
            runSearch(root.searchState.query + " " + tagTerm(category, name))
            return
        }
        var chosen = page.isTagPage ? page.browsedTags.slice() : []
        for (var i = 0; i < chosen.length; i++) {
            if (chosen[i].category === category && chosen[i].name === name) return
        }
        chosen.push({ category: category, name: name })
        runTagPage(chosen, page)
    }

    // A chosen tag's remove button: show the items again without it (the folder itself, with none left)
    function unbrowseTag(category, name) {
        var page = pageStack.currentItem
        if (!page || page.isTagPage !== true) return
        var chosen = page.browsedTags.filter(function(t) { return !(t.category === category && t.name === name) })
        if (chosen.length === 0) {
            var popped = pageStack.pop()
            if (popped) popped.destroy()
            return
        }
        runTagPage(chosen, page)
    }

    // A tag clicked in the image viewer's header: open the items with it over the viewer, so Back returns to the
    // picture. (From a page of tag results the tag narrows what that page shows, in a new page of its own.)
    function browseTagFromViewer(category, name) {
        var viewer = pageStack.currentItem
        if (!viewer || viewer.isViewer !== true) return
        var from = viewer.sourcePage
        // Opened from results already: show this tag's results on that page instead of stacking a page per tag
        // (cycling through tags must not leave a long trail of pages to go back through)
        if (from && from.isSearch === true) {
            var popped = pageStack.pop()
            if (popped) popped.destroy()
            if (from.isTagPage) runTagPage([{ category: category, name: name }], from)
            else runSearch(tagTerm(category, name))
            return
        }
        var chosen = (from && from.isTagPage) ? from.browsedTags.slice() : []
        for (var i = 0; i < chosen.length; i++) {
            if (chosen[i].category === category && chosen[i].name === name) return
        }
        chosen.push({ category: category, name: name })
        viewer.savedIndex = viewer.viewerIndex
        viewer.needsRestore = from !== null
        if (from) {
            runTagPage(chosen, from, true)
        } else {
            // opened from the Favorites tab: look in the whole Photos tab, which is what it shows
            runTagPage(chosen, { filterCategory: "photos", isTagPage: false, virtualId: -1, folderPath: "", homePath: "", searchScope: "" }, true)
        }
    }

    // The viewer is on top again after a page of results was opened over it: put its items back into the media
    // model (the results took it over) and the picture it was showing
    function restoreViewerSource(viewer) {
        var page = viewer.sourcePage
        viewer.needsRestore = false
        if (!page) return
        if (page.virtualId >= 0) {
            loadVirtual(page.virtualId, page.filterCategory)
        } else if (page.isSearch) {
            var state = page.savedSearch
            if (!state) return
            root.searchState = state
            root.currentFolder = null
            root.currentVirtual = -1
            mediaModel.filterMode = MediaModel.All
            showHits(searchModel.searchHits(state.query, state.tab ? "" : state.scope, state.tab), page.isTagPage === true)
        } else if (page.folderPath) {
            loadFolder(page.folderPath, page.filterCategory)
        }
        viewer.restoreIndex(viewer.savedIndex)
    }

    function tagQuery(chosen, tab) {
        var kinds = {"photos": " type:image", "videos": " type:video", "manga": " ~type:comic ~type:ebook",
                     "books": " type:ebook"}[tab] || ""
        return chosen.map(function(t) { return t.category + ":" + t.name }).join(" ") + kinds
    }

    // The name a tab's results are shown under in the scope switch
    function tabName(tab) {
        return {"photos": "Photos", "videos": "Videos", "manga": "Manga", "books": "EBooks"}[tab] || "everything"
    }

    // `from` is the page the click was made on: a folder (the search is for its library folder and tab), or the
    // tag page being narrowed, widened or switched between "this library folder" and "the whole tab"
    // `push` opens a new page even from a tag page (the viewer's header does)
    function runTagPage(chosen, from, push) {
        var tab = from.filterCategory
        var base = from.virtualId >= 0 ? from.homePath : (from.folderPath ? String(from.folderPath) : from.searchScope)
        var folder = from.isTagPage ? from.savedSearch.root : (base ? (searchModel.rootOf(base) || base) : "")
        var everywhere = from.isTagPage === true && from.tagEverywhere === true
        var wholeTab = !everywhere && from.isTagPage === true && from.tagWholeTab === true && tab !== ""
        var query = tagQuery(chosen, everywhere ? "" : tab)
        var label = chosen.map(function(t) { return t.name.replace(/_/g, " ") }).join(", ")
        var hits = everywhere ? searchModel.searchHits(query, "", "")
                              : searchModel.searchHits(query, wholeTab ? "" : folder, wholeTab ? tab : "")
        var state = { query: query, scope: wholeTab || everywhere ? "" : folder, root: folder, label: label,
                      tab: wholeTab ? tab : "" }
        root.searchState = state
        if (from.isTagPage && push !== true) {
            var count = showHits(hits, true)
            from.title = searchTitle(query, count)
            from.browsedTags = chosen
            from.savedSearch = state
            from.searchScope = wholeTab || everywhere ? "" : folder
        } else {
            root.currentFolder = null
            root.currentVirtual = -1
            mediaModel.filterMode = MediaModel.All
            var total = showHits(hits, true)
            pageStack.push(mediaGridComponent, {
                title: searchTitle(query, total),
                isSearch: true,
                isTagPage: true,
                browsedTags: chosen,
                savedSearch: state,
                tagWholeTab: wholeTab,
                browseOpen: true,                  // the browser stays open as the tag is chosen
                tagFolderName: folder ? folderTitle(folder) : "",
                filterCategory: tab,
                searchScope: folder
            })
        }
    }

    // The scope switch on a tag page: the same tags in the page's library folder, or in the whole tab
    // scope: "folder" (the library folder the tag was clicked in), "tab" (the whole tab) or "everywhere" (the whole
    // library, every kind of media)
    function setTagScope(page, scope) {
        if (!page || page.isTagPage !== true) return
        page.tagEverywhere = scope === "everywhere"
        page.tagWholeTab = scope === "tab"
        runTagPage(page.browsedTags, page)
    }

    // The colour of a tag category, as the tag editor and the tag sidebar draw it
    function categoryColor(category) {
        switch (category) {
        case "creator":   return Kirigami.Theme.negativeTextColor
        case "series":    return Kirigami.Theme.visitedLinkColor
        case "character": return Kirigami.Theme.positiveTextColor
        case "genre":     return Kirigami.Theme.neutralTextColor
        default:          return Kirigami.Theme.linkColor
        }
    }

    // Re-run the open search (after a delete, or when indexing finishes)
    function refreshSearch() {
        var page = searchPage()
        if (!page || !root.searchState) return
        var count = showHits(searchModel.searchHits(root.searchState.query,
            root.searchState.tab ? "" : root.searchState.scope, root.searchState.tab || ""), page.isTagPage === true)
        page.title = searchTitle(root.searchState.query, count)
    }

    function leaveSearch() {
        var page = searchPage()
        if (page) {
            var popped = pageStack.pop()
            if (popped) popped.destroy()
        }
    }

    function closeSearch() {
        leaveSearch()
        root.searchOpen = false
        searchBar.clearAll()
    }

    // "file:///home/me/My%20Folder/" -> "My Folder"
    function folderTitle(folderPath) {
        var pathStr = folderPath.toString()
        if (pathStr.endsWith("/")) {
            pathStr = pathStr.slice(0, -1)
        }
        var name = pathStr.split("/").pop()
        try {
            return decodeURIComponent(name)
        } catch (e) {
            return name   // malformed % sequence: show it as-is
        }
    }

    // Pops back to the folder at position `index` of the breadcrumb trail.
    function popToCrumb(index) {
        var page = pageStack.currentItem
        if (!page || !page.crumbs) return
        for (var i = page.crumbs.length - 1; i > index; i--) {
            var popped = pageStack.pop()
            if (popped) popped.destroy()
        }
    }

    // Makes mediaModel hold this folder, filtered for the category.
    function loadFolder(folderPath, category) {
        root.rootShown = false
        root.currentBoard = -1
        subfolderModel.formatFilter = ""
        subfolderModel.boardsTab = ""
        root.currentFolder = folderPath
        root.currentVirtual = -1
        mediaModel.openFolder(folderPath)       // shown at once from the library, scanned in the background
        gridCategory(category)
    }

    // parentCrumbs: the breadcrumb names of the folder this one is nested in
    function openMediaGrid(folderPath, category, parentCrumbs) {
        loadFolder(folderPath, category)

        // Push the component and dynamically set its title property
        pageStack.push(mediaGridComponent, {
            title: folderTitle(folderPath),
            folderPath: folderPath,
            filterCategory: category,
            crumbs: (parentCrumbs || []).concat([folderTitle(folderPath)])
        })
    }

    // Home (the tab that was Favorites): Continue, Pinned, Favorites and Recently added. It sits over the page
    // stack (the page underneath is empty on this tab) and is only shown while no page is pushed on top of it.
    HomeModel { id: homeModel }
    HomeView {
        id: homeView
        objectName: "homeView"
        parent: root.contentItem
        z: 1
        anchors.fill: parent
        visible: root.onFavoritesTab && pageStack.depth === 1
        backend: homeModel
        coverRevision: root.coverRevision
        onContinueOpened: function(item) { root.openFromHome(item.kind, item.path, item.name) }
        onPinnedOpened: function(item) { root.openFromHome(item.kind, item.ref, item.name) }
        onCoverOpened: function(item) { root.openFromHome(item.kind, item.path, item.name) }
        onPictureOpened: function(files, index) {
            var picked = files[index]
            if (picked.kind === "video") { root.openFile(covers_uri(picked.path)); return }
            var pictures = files.filter(function(f) { return f.kind !== "video" })
            root.rootShown = false
            root.currentFolder = null
            mediaModel.filterMode = MediaModel.All
            mediaModel.load_media_ids(pictures.map(function(f) { return f.id }))
            pageStack.push(imageViewerComponent, { initialIndex: pictures.indexOf(picked) })
        }
        onUnpinRequested: function(kind, ref) { homeModel.setPinned(kind, ref, false) }
        actions: mediaActions
        onFavoriteRemoved: function(kind, ref) { homeModel.unfavorite(kind, String(ref)) }
        onTrashRequested: function(ids) { root.requestTrash(ids) }
    }

    function covers_uri(path) {
        return path.indexOf("file://") === 0 ? path : "file://" + encodeURI(path).replace(/#/g, "%23").replace(/\?/g, "%3F")
    }

    // Open something Home shows: a series where it stopped, a book, a video, a board, a folder or a tag
    function openFromHome(kind, ref, name) {
        if (kind === "series" || kind === "show") {
            var uri = covers_uri(ref)
            var chapter = subfolderModel.openSeries(uri, "resume")
            if (chapter !== "") root.playEpisode(uri, chapter)
            else openMediaGrid(uri, "")
        } else if (kind === "book" || kind === "video") {
            root.openFile(covers_uri(ref))
        } else if (kind === "board") {
            openBoard(parseInt(ref), name)
        } else if (kind === "folder") {
            openMediaGrid(covers_uri(ref), "")
        } else if (kind === "tag") {
            var info = tagModel.tagInfo(ref)
            runTagPage([{ category: info.category || "genre", name: ref }],
                       { filterCategory: "", isTagPage: true, tagEverywhere: true, tagWholeTab: false, browsedTags: [],
                         virtualId: -1, folderPath: "", homePath: "", searchScope: "", savedSearch: { root: "" } }, true)
        }
    }

    Component {
        id: mediaGridComponent

        // A plain Page, not a ScrollablePage: the grid scrolls itself and the
        // tag panel sits beside it. (ScrollablePage wants the page's content to
        // BE the scrolling item, so anything that wraps or accompanies the
        // grid ends up zero-sized and the page looks blank.)
        Kirigami.Page {
            id: gridPage
            // The title property is dynamically injected by pageStack.push()
            padding: 0

            // Set by openMediaGrid: which folder this page shows, the category
            // it was filtered for, and the breadcrumb names down to it.
            readonly property bool isGridPage: true
            // the tab's top level (the first page): its library folders; activeSource is the one chip picked ("": all)
            property bool isRoot: false
            property string activeSource: ""
            // Manga and EBooks: the series format picked over the top level ("": all), and what is partway
            property string formatFilter: ""
            property var continueItems: []
            // a board's page: which board, and how its pictures are laid out
            property int boardId: -1
            property var boardInfo: ({})        // the board's summary, read once when it loads (its search runs to make it)
            property string layoutMode: "rows"
            // the layout follows what the page holds (its choice is looked up once the files are in)
            Connections {
                target: gridModel
                function onModelReset() { if (pageStack.currentItem === gridPage) root.applyLayout(gridPage) }
            }
            property var folderPath: null
            property string filterCategory: ""
            property var crumbs: []
            // A virtual folder page: which one, and the real folder it was made in
            property int virtualId: -1
            property string homePath: ""
            // The tag browser is open on this page (it follows root.browseTagsOpen while the page is on top)
            property bool browseOpen: false
            onBrowseOpenChanged: if (pageStack.currentItem === gridPage) root.browseTagsOpen = browseOpen
            Component.onCompleted: if (browseOpen) root.browseTagsOpen = true
            // The results of a tag clicked in the browser (a search page that is sorted and purged like a folder),
            // and the tags chosen so far, [{category, name}]
            property bool isTagPage: false
            property var browsedTags: []
            // the scope switch: false looks in the library folder the tag was clicked in (named here), true in the whole tab
            property bool tagWholeTab: false
            property bool tagEverywhere: false
            property string tagFolderName: ""

            // The file whose metadata panel is open (-1: none)
            property int metadataMediaId: -1
            Connections {
                target: root
                function onIsTagModeChanged() {
                    if (root.isTagMode) {
                        gridPage.metadataMediaId = -1
                        gridPage.browseOpen = false
                    }
                }
            }

            // A search results page: no folder, just the matches of root.searchState. The page keeps its own copy of
            // the state (tag results can be stacked, with a picture between), and root.searchState follows the page on top.
            property bool isSearch: false
            property string searchScope: ""
            property var savedSearch: null
            Component.onDestruction: if (isSearch && root.searchState === savedSearch) root.searchState = null

            // mediaModel is shared by every folder page. After popping back
            // from a subfolder it still holds the subfolder, so reload ours.
            Connections {
                target: pageStack
                function onCurrentItemChanged() {
                    if (pageStack.currentItem !== gridPage) return
                    gridPage.browseOpen = root.browseTagsOpen
                    if (gridPage.isRoot) {
                        if (!root.rootShown) root.loadRoot()
                        else gridPage.continueItems = folderModel.continueReading(8)     // back from the reader
                        return
                    }
                    if (gridPage.isSearch) {
                        root.searchState = gridPage.savedSearch
                        return
                    }
                    if (gridPage.boardId >= 0) {
                        if (root.currentBoard !== gridPage.boardId) root.loadBoard(gridPage.boardId, gridPage.filterCategory)
                        return
                    }
                    if (gridPage.virtualId >= 0) {
                        if (root.currentVirtual !== gridPage.virtualId) {
                            root.loadVirtual(gridPage.virtualId, gridPage.filterCategory)
                        }
                    } else if (String(root.currentFolder) !== String(gridPage.folderPath)) {
                        root.loadFolder(gridPage.folderPath, gridPage.filterCategory)
                    }
                }
            }

            RowLayout {
                anchors.fill: parent
                spacing: 0

                // Browsing by tag: a sidebar on the left (the tags of what the page shows, with counts)
                TagBrowsePanel {
                    objectName: "tagBrowsePanel"
                    Layout.fillHeight: true
                    Layout.preferredWidth: implicitWidth
                    visible: gridPage.browseOpen
                    mediaBackend: mediaModel
                    subfolderBackend: subfolderModel
                    tagBackend: tagModel
                    onCloseRequested: gridPage.browseOpen = false
                    selected: gridPage.browsedTags
                    onTagChosen: function(category, name) { root.browseTag(category, name) }
                    onTagRemoved: function(category, name) { root.unbrowseTag(category, name) }
                    onTagExcluded: function(category, name) { root.excludeTag(category, name) }
                    dockedRight: false
                }

              ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                // A tab's top level: one chip per library folder (to see that one alone), and in Manga and EBooks
                // the series format to show
                RowLayout {
                    readonly property bool formats: gridPage.isRoot && (gridPage.filterCategory === "manga" || gridPage.filterCategory === "books")
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.topMargin: 20         // every strip over the tiles starts where the tiles would
                    // (not "sourceChips.visible": a child counts as hidden while its parent is, so that never turned on)
                    visible: gridPage.isRoot && root.sourceList.length > 1 && !root.onFavoritesTab
                Flow {
                    id: sourceChips
                    objectName: "sourceChips"
                    Layout.fillWidth: true
                    spacing: 8
                    visible: gridPage.isRoot && root.sourceList.length > 1 && !root.onFavoritesTab
                    Repeater {
                        model: parent.visible ? [{ path: "", name: "All" }].concat(root.sourceList) : []
                        delegate: Kirigami.Chip {
                            required property var modelData
                            text: modelData.name
                            closable: false
                            checkable: true
                            checked: gridPage.activeSource === modelData.path
                            onClicked: {
                                gridPage.activeSource = modelData.path
                                root.loadRoot()
                            }
                        }
                    }
                }
                }

                // A board's page: what it is (its search, how many), and how its pictures are laid out
                RowLayout {
                    objectName: "boardBar"
                    readonly property var info: gridPage.boardInfo
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.topMargin: 20         // every strip over the tiles starts where the tiles would
                    visible: gridPage.boardId >= 0
                    spacing: Kirigami.Units.smallSpacing
                    Label {
                        text: "Board \u00B7 " + root.itemsText(parent.info.count || 0)
                        opacity: 0.75
                    }
                    Kirigami.Chip {
                        visible: (parent.info.query || "") !== ""
                        text: parent.info.query || ""
                        closable: false
                        checkable: false
                    }
                    Button {
                        text: (parent.info.query || "") === "" ? "Add a search\u2026" : "Edit search\u2026"
                        icon.name: "edit-find"
                        flat: true
                        onClicked: root.editBoardSearch(gridPage.boardId)
                    }
                    Item { Layout.fillWidth: true }
                }

                // A tag page: the tag (in its category's colour), what else it is called and what it implies
                RowLayout {
                    objectName: "tagHeader"
                    readonly property var only: gridPage.isTagPage && gridPage.browsedTags.length === 1 ? gridPage.browsedTags[0] : null
                    readonly property var info: only ? tagModel.tagInfo(only.name) : ({})
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.topMargin: 20         // every strip over the tiles starts where the tiles would
                    visible: only !== null
                    spacing: Kirigami.Units.largeSpacing
                    Rectangle {
                        readonly property color accent: root.categoryColor(parent.only ? parent.only.category : "")
                        implicitHeight: tagHeaderText.implicitHeight + Kirigami.Units.smallSpacing * 2
                        implicitWidth: tagHeaderText.implicitWidth + Kirigami.Units.largeSpacing * 2
                        radius: height / 2
                        color: Qt.alpha(accent, 0.18)
                        border.width: 1
                        border.color: Qt.alpha(accent, 0.65)
                        Label {
                            id: tagHeaderText
                            anchors.centerIn: parent
                            text: parent.parent.only ? parent.parent.only.category + ":" + parent.parent.only.name.replace(/_/g, " ") : ""
                            font.weight: Font.DemiBold
                        }
                    }
                    Button {
                        readonly property bool pinned: parent.only !== null && (homeView.pinnedItems, homeModel.isPinned("tag", parent.only.name))
                        text: pinned ? "Unpin from Home" : "Pin to Home"
                        icon.name: pinned ? "window-unpin" : "window-pin"
                        flat: true
                        onClicked: homeModel.setPinned("tag", parent.only.name, !pinned)
                    }
                    Label {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        opacity: 0.75
                        text: {
                            var info = parent.info, parts = []
                            if (info.aliases && info.aliases.length) parts.push("Also called " + info.aliases.join(", "))
                            if (info.implies && info.implies.length)
                                parts.push("implies " + info.implies.map(function(t) { return t.category + ":" + t.name }).join(", "))
                            return parts.join(" \u00B7 ")
                        }
                    }
                }

                // A search: keep it as a board
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.topMargin: 20         // every strip over the tiles starts where the tiles would
                    visible: gridPage.isSearch && root.searchState !== null && (root.searchState.query || "") !== ""
                    // what kind of results to show, with how many of each
                    Repeater {
                        model: {
                            gridView.count                      // counted again when the results change
                            var c = mediaModel.kindCounts()
                            return [{ mode: MediaModel.All, name: "All", n: c.all },
                                    { mode: MediaModel.ImagesOnly, name: "Images", n: c.images },
                                    { mode: MediaModel.VideosOnly, name: "Videos", n: c.videos },
                                    { mode: MediaModel.MangaOnly, name: "Manga", n: c.manga },
                                    { mode: MediaModel.BooksOnly, name: "EBooks", n: c.books }]
                                   .filter(function(k) { return k.mode === MediaModel.All || k.n > 0 })
                        }
                        delegate: Kirigami.Chip {
                            required property var modelData
                            text: modelData.name + "  " + modelData.n
                            closable: false
                            checkable: true
                            checked: mediaModel.filterMode === modelData.mode
                            onClicked: mediaModel.filterMode = modelData.mode
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Button {
                        objectName: "saveAsBoard"
                        text: "Save as Board\u2026"
                        icon.name: "list-add"
                        onClicked: {
                            var query = root.searchState.query
                            var tab = root.onFavoritesTab ? "" : folderModel.currentCategory
                            root.askName("Save as board", query, function(name) {
                                if (name.trim() === "") return "Give the board a name"
                                var id = boardService.create(name, query, tab)
                                if (id < 0) return "Couldn't make the board"
                                root.openBoard(id, name)
                                return ""
                            }, "Save")
                        }
                    }
                }

                // Manga and EBooks: what you are partway through, most recent first
                ColumnLayout {
                    objectName: "continueReading"
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.topMargin: 20         // every strip over the tiles starts where the tiles would
                    spacing: 8
                    visible: gridPage.isRoot && gridPage.continueItems.length > 0 && gridPage.formatFilter === ""
                             && (gridPage.filterCategory === "manga" || gridPage.filterCategory === "books")
                    Label {
                        text: "Continue reading"
                        font.weight: Font.DemiBold
                    }
                    Row {
                        id: continueCards
                        Layout.fillWidth: true
                        spacing: 16
                        readonly property int fits: Math.max(1, Math.floor((width + spacing) / (320 + spacing)))
                        Repeater {
                            model: gridPage.continueItems.slice(0, continueCards.fits)
                            delegate: Rectangle {
                                required property var modelData
                                width: 320
                                height: 100
                                radius: 8
                                color: cardHover.hovered ? Qt.tint(Kirigami.Theme.backgroundColor, Qt.alpha(Kirigami.Theme.highlightColor, 0.12))
                                                         : Kirigami.Theme.backgroundColor
                                border.width: 1
                                border.color: Qt.alpha(Kirigami.Theme.textColor, 0.15)
                                HoverHandler { id: cardHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler {
                                    onTapped: {
                                        if (modelData.kind === "series") {
                                            var chapter = subfolderModel.openSeries(modelData.uri, "resume")
                                            if (chapter !== "") root.openFile(chapter)
                                        } else {
                                            root.openFile(modelData.uri)
                                        }
                                    }
                                }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 12
                                    Kirigami.ShadowedImage {
                                        Layout.preferredWidth: 56
                                        Layout.preferredHeight: 84
                                        radius: 4
                                        source: ThumbUri.source(modelData.cover)
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

                MediaGridView {
                    id: gridView
                    objectName: "mediaGrid"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: gridModel
                    tileLevel: root.levelFor((gridPage.filterCategory || folderModel.currentCategory) + ".grid")
                    coverRevision: root.coverRevision
                    onCoverPickerRequested: function(mediaId) { root.pickCoverOfMedia(mediaId) }
                    onSubfolderCoverPickerRequested: function(filePath) { root.pickCoverOfFile(filePath) }
                    mediaBackend: mediaModel
                    tagBackend: tagModel
                    // Only this page reacts: while the image viewer is open on
                    // top, the grid underneath stays out of tag mode.
                    tagMode: root.isTagMode && pageStack.currentItem === gridPage
                    selectMode: root.isSelectMode && pageStack.currentItem === gridPage
                    subfolderBackend: subfolderModel
                    boardBackend: boardService
                    homeBackend: homeModel
                    actionsBackend: mediaActions
                    onTrashRequested: function(ids) { root.requestTrash(ids) }
                    onRenameRequested: function(uri, name) {
                        root.askName("Rename \u201C" + name + "\u201D", name, function(newName) {
                            var problem = mediaActions.rename(uri, newName)
                            if (problem !== "") return problem
                            root.reloadPage()          // the scan knows it by its contents: its tags and favorite stay
                            return ""
                        }, "Rename")
                    }
                    boardTab: gridPage.boardId >= 0 ? (gridPage.boardInfo.tab || "")
                              : (root.onFavoritesTab ? "" : folderModel.currentCategory)
                    boardId: gridPage.boardId
                    layoutMode: gridPage.layoutMode
                    onBoardClicked: function(boardId, name) { root.openBoard(boardId, name) }
                    onBoardEditRequested: function(boardId) { root.editBoardSearch(boardId) }
                    onBoardRenameRequested: function(boardId, name) {
                        root.askName("Rename board", name, function(newName) {
                            if (newName.trim() === "") return "Give the board a name"
                            boardService.rename(boardId, newName)
                            return ""
                        })
                    }
                    onBoardDeleteRequested: function(boardId, name) {
                        boardService.remove(boardId)
                        showPassiveNotification("Deleted the board \u201C" + name + "\u201D (no file was touched)")
                    }
                    onNewBoardRequested: function(ids) { root.newBoard(ids, gridView.boardTab) }
                    // Virtual folders: not in a search that spans every library folder; "Remove" inside one
                    virtualAllowed: !(gridPage.isSearch && gridPage.searchScope === "")
                    virtualPage: gridPage.virtualId >= 0
                    canCreateHere: !gridPage.isSearch

                    onVirtualFolderClicked: function(virtualId, name) {
                        root.openVirtualFolder(virtualId, name, gridPage.filterCategory, gridPage.crumbs)
                    }
                    onSelectRequested: function(ids, tiles) {
                        root.isTagMode = false
                        root.isSelectMode = true
                        gridView.selectedIds = ids
                        gridView.setTiles(tiles)
                    }
                    onVirtualActionRequested: function(action, ids, tiles) {
                        var parent = gridPage.virtualId
                        if (action === "add") root.addToVirtual(ids, tiles, false, parent)
                        else if (action === "addNew") root.addToVirtual(ids, tiles, true, parent)
                        else if (action === "remove") root.removeFromVirtual(ids, tiles)
                        gridView.clearSelection()
                    }
                    onNewVirtualFolderRequested: {
                        var home = gridPage.virtualId >= 0 ? gridPage.homePath : String(gridPage.folderPath)
                        root.askName("New virtual folder", "", function(name) {
                            var result = virtualFolders.create(name, home, gridPage.virtualId)
                            return result.error !== undefined ? result.error : ""
                        })
                    }
                    onVirtualRenameRequested: function(virtualId, name) {
                        root.askName("Rename virtual folder", name, function(newName) {
                            var result = virtualFolders.rename(virtualId, newName)
                            return result.error !== undefined ? result.error : ""
                        })
                    }
                    onVirtualDeleteRequested: function(virtualId, name) {
                        virtualFolders.deleteFolder(virtualId)
                        showPassiveNotification("Deleted \u201C" + name + "\u201D: what was in it went back where it was")
                    }
                    onVirtualCoverResetRequested: function(virtualId) { virtualFolders.clearCover(virtualId) }

                    onSubfolderSingleFileRequested: function(subfolderPath) {
                        var file = subfolderModel.openSingleFile(subfolderPath)
                        if (file !== "") root.openFile(file)
                        else root.openMediaGrid(subfolderPath, gridPage.filterCategory, gridPage.crumbs)
                    }
                    // a show (a video series) opens its page; its "next", "previous" and "first" episode start straight away
                    onShowRequested: function(subfolderPath) {
                        pageStack.push(showComponent, { location: subfolderPath })
                    }
                    onSubfolderSeriesRequested: function(subfolderPath, which) {
                        var chapter = subfolderModel.openSeries(subfolderPath, which)
                        if (chapter !== "") root.playEpisode(subfolderPath, chapter)
                        else root.openMediaGrid(subfolderPath, gridPage.filterCategory, gridPage.crumbs)
                    }
                    onSubfolderClicked: function(subfolderPath) {
                        root.openMediaGrid(subfolderPath, gridPage.filterCategory, gridPage.crumbs)
                    }

                    onEditTagsRequested: function(mediaId) {
                        root.isTagMode = true
                    }

                    // The metadata panel and the tag panel share one spot: showing one hides the other
                    onMetadataRequested: function(mediaId) {
                        root.isTagMode = false
                        gridPage.browseOpen = false
                        gridPage.metadataMediaId = mediaId
                    }
                    onBrowseTagsRequested: root.toggleBrowseTags()

                    onImageClicked: function(index) {
                        pageStack.push(imageViewerComponent, { initialIndex: index, sourcePage: gridPage })
                    }

                    // Videos, comics, and ebooks don't have dedicated in-app
                    // viewers (a video player is next on the list; manga/ebook
                    // readers are deliberately staying out of scope), so for
                    // now they open in whatever the system's default handler
                    // is for that file type.
                    onVideoClicked: function(index) { root.playVideoAt(index) }
                    // from the start: forget where it was stopped (its length stays), then play it
                    onPlayFromStartRequested: function(index) {
                        playbackStore.restart(mediaModel.getFileUri(index))
                        root.playVideoAt(index)
                    }
                    onComicClicked: function(index) { root.openFile(mediaModel.getFileUri(index)) }
                    onBookClicked: function(index) { root.openFile(mediaModel.getFileUri(index)) }
                    onOpenExternallyRequested: function(index) { Qt.openUrlExternally(mediaModel.getFileUri(index)) }
                }

                // An empty virtual folder says how to fill it
                // (a Label over the grid, not in it, so it never scrolls)
                Label {
                    objectName: "emptyVirtualHint"
                    Layout.fillWidth: true
                    Layout.preferredHeight: visible ? implicitHeight + Kirigami.Units.gridUnit * 3 : 0
                    visible: gridPage.virtualId >= 0 && gridView.count === 0
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                    text: "This virtual folder is empty.\nIn the folder it was made in, select items and choose \u201CAdd to virtual folder\u201D."
                }

                // A folder opened for the first time is read in the background: say so instead of looking empty
                RowLayout {
                    objectName: "scanningHint"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredHeight: visible ? implicitHeight + Kirigami.Units.gridUnit * 3 : 0
                    visible: !!gridPage.folderPath && mediaModel.scanning && gridView.count === 0
                    spacing: Kirigami.Units.smallSpacing
                    BusyIndicator { running: parent.visible }
                    Label {
                        text: "Reading this folder\u2026"
                        opacity: 0.7
                    }
                }

                // Select mode's actions, under the grid
                Rectangle {
                    id: selectBar
                    objectName: "selectBar"
                    Layout.fillWidth: true
                    visible: gridView.selectMode
                    implicitHeight: barRow.implicitHeight + Kirigami.Units.largeSpacing * 2
                    color: Kirigami.Theme.alternateBackgroundColor
                    readonly property int fileCount: gridView.selectedIds.length
                    readonly property int tileCount: gridView.selectedTiles.length
                    readonly property int total: fileCount + tileCount

                    Kirigami.Separator { anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right }

                    RowLayout {
                        id: barRow
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: Kirigami.Units.largeSpacing
                        anchors.rightMargin: Kirigami.Units.largeSpacing
                        spacing: Kirigami.Units.smallSpacing

                        Label {
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                            text: selectBar.total === 0 ? "Select items to move"
                                  : selectBar.total + (selectBar.total === 1 ? " selected" : " selected")
                            opacity: selectBar.total === 0 ? 0.65 : 1
                        }
                        Button {
                            objectName: "selectAddButton"
                            text: "Add to virtual folder\u2026"
                            icon.name: "folder-add"
                            enabled: selectBar.total > 0
                            onClicked: gridView.virtualActionRequested("add", gridView.selectedIds.slice(), gridView.selectedTiles.slice())
                        }
                        Button {
                            objectName: "selectNewButton"
                            text: "New virtual folder\u2026"
                            icon.name: "folder-new"
                            enabled: selectBar.total > 0
                            onClicked: gridView.virtualActionRequested("addNew", gridView.selectedIds.slice(), gridView.selectedTiles.slice())
                        }
                        Button {
                            objectName: "selectRemoveButton"
                            text: "Remove from virtual folder"
                            icon.name: "go-up"
                            visible: gridView.virtualPage
                            enabled: selectBar.total > 0
                            onClicked: gridView.virtualActionRequested("remove", gridView.selectedIds.slice(), gridView.selectedTiles.slice())
                        }
                        Item { Layout.preferredWidth: Kirigami.Units.largeSpacing }
                        Button {
                            objectName: "selectTrashButton"
                            text: "Trash"
                            icon.name: "edit-delete"
                            // only files go to the Trash: a folder tile does not
                            enabled: selectBar.fileCount > 0 && selectBar.tileCount === 0
                            ToolTip.visible: hovered && selectBar.tileCount > 0
                            ToolTip.delay: 400
                            ToolTip.text: "Folders are not moved to the Trash from here. Select only files."
                            onClicked: root.requestTrash(gridView.selectedIds.slice(), function(removed) {
                                gridView.clearSelection()
                            })
                        }
                    }
                }
              }

                MetadataPanel {
                    Layout.fillHeight: true
                    Layout.preferredWidth: implicitWidth
                    visible: gridPage.metadataMediaId >= 0
                    mediaId: gridPage.metadataMediaId
                    onCloseRequested: gridPage.metadataMediaId = -1
                }


                // Shown for the whole of tag mode (not only while something is
                // selected) so the grid doesn't resize on every click.
                TagPanel {
                    Layout.fillHeight: true
                    Layout.preferredWidth: implicitWidth
                    visible: gridView.tagMode
                    mediaIds: gridView.selectedIds
                    folderKeys: gridView.selectedTiles
                    folderBackend: subfolderModel
                    tagModel: gridView.tagBackend
                    mediaModel: gridView.mediaBackend

                    onTrashRequested: {
                        root.requestTrash(gridView.selectedIds.slice(), function(removed) {
                            gridView.setSelection([])
                        })
                    }
                }
            }
        }
    }

    Component {
        id: imageViewerComponent

        Kirigami.Page {
            id: viewerPage
            objectName: "viewerPage"
            // a picture is seen best on a dark ground, as in any photo viewer
            background: Rectangle { color: "#141516" }

            // Overridden by pageStack.push(imageViewerComponent, { initialIndex: ... })
            property int initialIndex: 0

            // The model to page through: the open folder's, or the favorited
            // images when opened from the Favorites tab.
            property var viewerModel: mediaModel

            readonly property bool isViewer: true
            // the picture shown, for the tags in the header
            readonly property int currentMediaId: imageViewer.currentMediaId
            // The grid page the viewer was opened from (none from the Favorites tab). Another page of results can be
            // opened over the viewer (a tag clicked in its header) and takes the media model over; coming back,
            // the viewer gets its items and its place back: see restoreViewerSource.
            property var sourcePage: null
            property bool needsRestore: false
            property int savedIndex: 0
            readonly property int viewerIndex: imageViewer.currentIndex
            function restoreIndex(index) {
                imageViewer.currentIndex = index
                imageViewer.positionViewAtIndex(index, ListView.Beginning)
            }

            // Pulls the title dynamically from the imageViewer component
            // which updates on every image switch
            title: imageViewer.title

            // No page padding/margins -- the image should go edge to edge.
            padding: 0

            // The header's "Done" button only flips root.isTagMode; close the
            // viewer's own panel when that happens.
            Connections {
                target: root
                function onIsTagModeChanged() {
                    if (!root.isTagMode) {
                        imageViewer.showTagPanel = false
                    }
                }
            }

            ImageViewer {
                id: imageViewer
                anchors.fill: parent
                model: viewerPage.viewerModel
                initialIndex: viewerPage.initialIndex
                tagBackend: tagModel

                onTagOpened: root.isTagMode = true
                onTagExited: root.isTagMode = false

                onTrashRequested: function(mediaId) {
                    var index = imageViewer.currentIndex
                    root.requestTrash([mediaId], function(removed) {
                        if (imageViewer.count === 0) {
                            // That was the last image: leave the viewer
                            var popped = pageStack.pop()
                            if (popped) popped.destroy()
                        } else {
                            // Show the next image (or the new last one)
                            imageViewer.currentIndex = Math.min(index, imageViewer.count - 1)
                            imageViewer.forceActiveFocus()
                        }
                    })
                }
            }
        }
    }
}
