// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0
import "./views"

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
        if (pageStack.depth <= 1) return root.onFavoritesTab ? "" : "top"
        if (page && page.filterCategory !== undefined)
            return (page.filterCategory || folderModel.currentCategory) + ".grid"
        return ""
    }
    readonly property int topTileLevel: levelFor("top")
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
    // The virtual folder mediaModel holds instead (-1: none); see loadVirtual
    property int currentVirtual: -1

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
            readonly property int toolButtonCount: 2     // purge and sort sit left of the mode button

            TextMetrics {
                id: doneMetrics
                text: "Done"
                font.weight: Font.Medium
            }

            // Dynamic Left Button (Menu vs. Back)
            Item {
                Layout.preferredWidth: headerRow.sideSlotWidth + headerRow.sortSlotWidth * headerRow.toolButtonCount
                Layout.preferredHeight: leftButton.height

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
                            text: "Add Folder"
                            icon.name: "folder-add"
                            enabled: !root.onFavoritesTab
                            onTriggered: {
                                root.isRemoveMode = false
                                filePicker.openFolderDialog()
                            }
                        }
                        MenuItem {
                            text: root.isRemoveMode ? "Cancel Removal" : "Remove Folder"
                            icon.name: "edit-delete"
                            enabled: !root.onFavoritesTab
                            onTriggered: root.isRemoveMode = !root.isRemoveMode
                        }
                        Menu {
                            title: "Tile Size"
                            enabled: !root.onFavoritesTab
                            MenuItem {
                                text: "Extra small"
                                icon.name: root.topTileLevel === -2 ? "checkmark" : ""
                                onTriggered: root.setTileLevel("top", -2)
                            }
                            MenuItem {
                                text: "Small"
                                icon.name: root.topTileLevel === -1 ? "checkmark" : ""
                                onTriggered: root.setTileLevel("top", -1)
                            }
                            MenuItem {
                                text: "Normal"
                                icon.name: root.topTileLevel === 0 ? "checkmark" : ""
                                onTriggered: root.setTileLevel("top", 0)
                            }
                            MenuItem {
                                text: "Large"
                                icon.name: root.topTileLevel === 1 ? "checkmark" : ""
                                onTriggered: root.setTileLevel("top", 1)
                            }
                            MenuItem {
                                text: "Extra large"
                                icon.name: root.topTileLevel === 2 ? "checkmark" : ""
                                onTriggered: root.setTileLevel("top", 2)
                            }
                        }
                        MenuSeparator {}
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
                    anchors.fill: parent
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
                    anchors.centerIn: parent
                    icon.name: "edit-clear-all"
                    display: AbstractButton.IconOnly
                    visible: pageStack.currentItem !== null
                             && pageStack.currentItem.filterCategory === "photos"
                             && pageStack.currentItem.isSearch === false
                    ToolTip.visible: hovered
                    ToolTip.delay: 600
                    ToolTip.text: "Purge: swipe through these pictures to keep them or send them to the Trash"
                    onClicked: root.startPurge()
                }
            }

            // Sort button: only on a folder's (or subfolder's) page. Search results
            // keep their ranking and the top-level tab lists folders, so neither has it.
            Item {
                Layout.preferredWidth: headerRow.sortSlotWidth
                Layout.preferredHeight: leftButton.height

                ToolButton {
                    id: sortButton
                    anchors.centerIn: parent
                    icon.name: "view-sort"
                    display: AbstractButton.IconOnly
                    visible: pageStack.currentItem !== null
                             && pageStack.currentItem.filterCategory !== undefined
                             && pageStack.currentItem.isSearch === false
                    onClicked: sortMenu.popup(sortButton, 0, sortButton.height)

                    Menu {
                        id: sortMenu

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
                            Layout.preferredWidth: 16
                            Layout.preferredHeight: 16
                        }

                        Label {
                            text: modeButtonSlot.mode === "idle" ? "Search" : "Done"
                            color: modeButtonSlot.fg
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
            visible: root.searchOpen
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
            subfolderModel.load(mediaModel.folderPath)
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

    // A name for a new or renamed virtual folder
    Kirigami.PromptDialog {
        id: nameDialog
        objectName: "nameDialog"
        property var onNamed: null          // function(name): the error text, or "" when it worked
        property string problem: ""
        standardButtons: Kirigami.Dialog.Cancel
        customFooterActions: [
            Kirigami.Action {
                text: nameDialog.title.indexOf("Rename") === 0 ? "Rename" : "Create"
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
                placeholderText: "Name"
                maximumLength: 100
                onAccepted: nameDialog.accept()
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

    FilePicker {
        id: filePicker
        onFolderSelected: function(selectedFolder) {
            // Favorites is a virtual tab, not a folder category
            if (root.onFavoritesTab) return
            folderModel.addFolder(selectedFolder, folderModel.currentCategory)
            searchModel.indexLibrary()
        }
        onFolderRejected: function(problem) { showPassiveNotification(problem, 12000) }
    }

    footer: Kirigami.NavigationTabBar {
        id: navTabBar
        // Hidden while the image viewer is open -- switching categories
        // mid-zoom doesn't make sense, and the viewer wants the full window
        // height anyway. (Tested by page rather than by depth: opened from
        // the Favorites tab the viewer is at depth 2, not 3.)
        visible: !(pageStack.currentItem && (pageStack.currentItem.isViewer === true || pageStack.currentItem.isReader === true))
        actions: [
            Kirigami.Action {
                // Not image-x-generic(-symbolic): in Breeze that falls back to a coloured
                // (green) file-type icon, unlike the single-colour icons of the other tabs
                icon.name: "viewimage"
                text: "Photos"
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
            Kirigami.Action {
                icon.name: "favorite"
                text: "Favorites"
                checked: folderModel.currentCategory === "favorites"
                onTriggered: switchTab("favorites")
            }
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
        else Qt.openUrlExternally(uri)
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
        }
        if (root.onFavoritesTab) {
            favoritesView.refresh()
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

    function askName(title, initial, onNamed) {
        nameDialog.title = title
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
        } else if (page.isSearch) {
            refreshSearch()
        } else if (page.folderPath) {
            loadFolder(page.folderPath, page.filterCategory)
        }
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
        return "Search: " + query + " (" + count + ")"
    }

    function runSearch(query) {
        if (query.trim() === "") {
            leaveSearch()
            return
        }
        var scope = currentSearchScope()
        var ids = searchModel.search(query, scope)
        root.searchState = { query: query, scope: scope }
        var page = searchPage()
        if (page) {
            mediaModel.load_media_ids(ids)
            page.title = searchTitle(query, ids.length)
        } else {
            root.currentFolder = null
            root.currentVirtual = -1
            mediaModel.filterMode = MediaModel.All   // results are never narrowed by a folder tab's filter
            mediaModel.load_media_ids(ids)
            pageStack.push(mediaGridComponent, {
                title: searchTitle(query, ids.length),
                isSearch: true,
                searchScope: scope
            })
        }
    }

    // Re-run the open search (after a delete, or when indexing finishes)
    function refreshSearch() {
        var page = searchPage()
        if (!page || !root.searchState) return
        var ids = searchModel.search(root.searchState.query, root.searchState.scope)
        mediaModel.load_media_ids(ids)
        page.title = searchTitle(root.searchState.query, ids.length)
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
        root.currentFolder = folderPath
        root.currentVirtual = -1
        mediaModel.load_from_qurl(folderPath)
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

    pageStack.initialPage: Kirigami.ScrollablePage {
        title: root.onFavoritesTab ? "Favorites" : "Collections"
        padding: 0      // the tiles inset themselves, so this lines up with the folder grids

        FolderGridView {
            anchors.fill: parent
            model: folderModel
            visible: !root.onFavoritesTab

            removeMode: root.isRemoveMode
            onRemoveModeExitRequested: root.isRemoveMode = false
            tileLevel: root.topTileLevel
            coverRevision: root.coverRevision
            onCoverPickerRequested: function(filePath) { root.pickCoverOfFile(filePath) }

            onAddFolderRequested: filePicker.openFolderDialog()

            onFolderClicked: function(folderPath) {
                openMediaGrid(folderPath, folderModel.currentCategory)
            }

            onSingleFileRequested: function(folderPath) {
                var file = folderModel.openSingleFile(folderPath)
                if (file !== "") root.openFile(file)
                else openMediaGrid(folderPath, folderModel.currentCategory)   // it has gained files since: just browse it
            }

            onSeriesRequested: function(folderPath, which) {
                var chapter = folderModel.openSeries(folderPath, which)
                if (chapter !== "") root.openFile(chapter)
                else openMediaGrid(folderPath, folderModel.currentCategory)   // no chapter files: just browse it
            }
        }
    }

    // The Favorites tab: every favorite, grouped by type. It sits over the page
    // stack (the folder grid underneath is hidden on this tab) and is only
    // shown while no page is pushed on top of it, e.g. the image viewer.
    FavoritesView {
        id: favoritesView
        parent: root.contentItem
        z: 1
        anchors.fill: parent
        visible: root.onFavoritesTab && pageStack.depth === 1
        coverRevision: root.coverRevision

        onImageClicked: function(index) {
            pageStack.push(imageViewerComponent, {
                initialIndex: index,
                viewerModel: favoritesView.imagesModel
            })
        }
        onOpenExternally: function(fileUri) {
            root.openFile(fileUri)
        }
        onCollectionClicked: function(folderUri) {
            openMediaGrid(folderUri, folderModel.currentCategory)
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
            property var folderPath: null
            property string filterCategory: ""
            property var crumbs: []
            // A virtual folder page: which one, and the real folder it was made in
            property int virtualId: -1
            property string homePath: ""

            // The file whose metadata panel is open (-1: none)
            property int metadataMediaId: -1
            Connections {
                target: root
                function onIsTagModeChanged() {
                    if (root.isTagMode) gridPage.metadataMediaId = -1
                }
            }

            // A search results page: no folder, just the matches of root.searchState
            property bool isSearch: false
            property string searchScope: ""
            Component.onDestruction: if (isSearch) root.searchState = null

            // mediaModel is shared by every folder page. After popping back
            // from a subfolder it still holds the subfolder, so reload ours.
            Connections {
                target: pageStack
                function onCurrentItemChanged() {
                    if (pageStack.currentItem !== gridPage) return
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

              ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

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
                    onSubfolderSeriesRequested: function(subfolderPath, which) {
                        var chapter = subfolderModel.openSeries(subfolderPath, which)
                        if (chapter !== "") root.openFile(chapter)
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
                        gridPage.metadataMediaId = mediaId
                    }

                    onImageClicked: function(index) {
                        pageStack.push(imageViewerComponent, { initialIndex: index })
                    }

                    // Videos, comics, and ebooks don't have dedicated in-app
                    // viewers (a video player is next on the list; manga/ebook
                    // readers are deliberately staying out of scope), so for
                    // now they open in whatever the system's default handler
                    // is for that file type.
                    onVideoClicked: function(index) {
                        Qt.openUrlExternally(mediaModel.getFileUri(index))
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

            // Overridden by pageStack.push(imageViewerComponent, { initialIndex: ... })
            property int initialIndex: 0

            // The model to page through: the open folder's, or the favorited
            // images when opened from the Favorites tab.
            property var viewerModel: mediaModel

            readonly property bool isViewer: true

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
