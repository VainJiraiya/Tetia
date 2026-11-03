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
    property bool isTagMode: false

    // The search strip, and what the search page on the stack (if any) is showing
    property bool searchOpen: false
    property var searchState: null

    // The folder whose contents mediaModel currently holds; reloaded after a
    // delete so removed items disappear from the grid and the viewer.
    property var currentFolder: null

    // Stack layout: 1 = folder grid (or the Favorites tab), 2 = folder contents
    // (or the viewer opened from Favorites), 3 = image viewer from a folder.
    readonly property bool onFavoritesTab: folderModel.currentCategory === "favorites"

    // Tag mode belongs to one page: leaving or entering a page always starts
    // with it off (the viewer re-enables it when its own panel opens).
    Connections {
        target: pageStack
        function onDepthChanged() {
            root.isTagMode = false
        }
    }

    // Persistent header defined at the ApplicationWindow level
    header: Column {
        id: headerColumn

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

            TextMetrics {
                id: doneMetrics
                text: "Done"
                font.weight: Font.Medium
            }

            // Dynamic Left Button (Menu vs. Back)
            Item {
                Layout.preferredWidth: headerRow.sideSlotWidth
                Layout.preferredHeight: leftButton.height

                ToolButton {
                    id: leftButton
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    icon.name: pageStack.depth > 1 ? "go-previous" : "application-menu"
                    display: AbstractButton.IconOnly

                    property double lastClosedTime: 0

                    onClicked: {
                        if (pageStack.depth > 1) {
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

            // Dynamic Right Button. One pill that changes with the mode:
            //   remove mode          -> "Done" (red), leaves remove mode
            //   tag mode             -> "Done" (accent), leaves tag mode
            //   anywhere but the viewer -> "Search", opens the search strip
            // (tag mode is entered from a tile's right-click menu)
            // Built from plain primitives (Rectangle/Icon/Label/MouseArea)
            // rather than a QQC2 Button, since that avoids relying on
            // this style's Button implicit-size/background computation.
            Item {
                id: modeButtonSlot
                Layout.preferredWidth: headerRow.sideSlotWidth
                Layout.preferredHeight: leftButton.height

                readonly property bool canSearch: !(pageStack.currentItem && pageStack.currentItem.isViewer === true)
                readonly property string mode: root.isRemoveMode ? "remove"
                                             : (root.isTagMode ? "tag"
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

    Component.onCompleted: searchModel.indexLibrary()

    Shortcut {
        sequence: StandardKey.Find
        onActivated: if (!(pageStack.currentItem && pageStack.currentItem.isViewer === true)) root.openSearch()
    }

    MediaActions {
        id: mediaActions
    }

    // Shared by the grid's tag panel and the image viewer's.
    Kirigami.PromptDialog {
        id: deleteDialog

        property var ids: []
        // Optional callback(removedIds), run after the delete finishes
        property var afterDelete: null

        title: ids.length === 1 ? "Move 1 item to the trash?"
                                : "Move " + ids.length + " items to the trash?"
        subtitle: "The files go to the system trash, so you can restore them from there. Their tags and favorites are removed."
        standardButtons: Kirigami.Dialog.Cancel
        customFooterActions: [
            Kirigami.Action {
                text: "Move to Trash"
                icon.name: "edit-delete"
                onTriggered: {
                    deleteDialog.close()
                    root.performDelete(deleteDialog.ids, deleteDialog.afterDelete)
                }
            }
        ]
    }

    FilePicker {
        id: filePicker
        onFolderSelected: function(selectedFolder) {
            // Favorites is a virtual tab, not a folder category
            if (root.onFavoritesTab) return
            folderModel.addFolder(selectedFolder, folderModel.currentCategory)
            searchModel.indexLibrary()
        }
    }

    footer: Kirigami.NavigationTabBar {
        id: navTabBar
        // Hidden while the image viewer is open -- switching categories
        // mid-zoom doesn't make sense, and the viewer wants the full window
        // height anyway. (Tested by page rather than by depth: opened from
        // the Favorites tab the viewer is at depth 2, not 3.)
        visible: !(pageStack.currentItem && pageStack.currentItem.isViewer === true)
        actions: [
            Kirigami.Action {
                icon.name: "image-x-generic-symbolic"
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

    function requestDelete(ids, afterDelete) {
        if (!ids || ids.length === 0) return
        deleteDialog.ids = ids
        deleteDialog.afterDelete = afterDelete ? afterDelete : null
        deleteDialog.open()
    }

    function performDelete(ids, afterDelete) {
        var removed = mediaActions.moveToTrash(ids)
        // Reload so the model drops the removed items: the open folder, or
        // the Favorites lists when deleting from the viewer opened there
        if (root.currentFolder) {
            mediaModel.load_from_qurl(root.currentFolder)
        } else if (root.searchState) {
            root.refreshSearch()
        }
        if (root.onFavoritesTab) {
            favoritesView.refresh()
        }
        if (afterDelete) {
            afterDelete(removed)
        }
        if (removed.length < ids.length) {
            var failed = ids.length - removed.length
            showPassiveNotification("Couldn't move " + failed + (failed === 1 ? " item" : " items") + " to the trash")
        }
    }

    function switchTab(category) {
        folderModel.currentCategory = category
        root.currentFolder = null
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
        mediaModel.load_from_qurl(folderPath)

        if (category === "photos") {
            mediaModel.filterMode = MediaModel.ImagesOnly
        } else if (category === "videos") {
            mediaModel.filterMode = MediaModel.VideosOnly
        } else if (category === "manga") {
            mediaModel.filterMode = MediaModel.MangaOnly
        } else if (category === "books") {
            mediaModel.filterMode = MediaModel.BooksOnly
        } else {
            mediaModel.filterMode = MediaModel.All
        }
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

        FolderGridView {
            anchors.fill: parent
            model: folderModel
            visible: !root.onFavoritesTab

            removeMode: root.isRemoveMode
            onRemoveModeExitRequested: root.isRemoveMode = false

            onAddFolderRequested: filePicker.openFolderDialog()

            onFolderClicked: function(folderPath) {
                openMediaGrid(folderPath, folderModel.currentCategory)
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

        onImageClicked: function(index) {
            pageStack.push(imageViewerComponent, {
                initialIndex: index,
                viewerModel: favoritesView.imagesModel
            })
        }
        onOpenExternally: function(fileUri) {
            Qt.openUrlExternally(fileUri)
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

            // A search results page: no folder, just the matches of root.searchState
            property bool isSearch: false
            property string searchScope: ""
            Component.onDestruction: if (isSearch) root.searchState = null

            // mediaModel is shared by every folder page. After popping back
            // from a subfolder it still holds the subfolder, so reload ours.
            Connections {
                target: pageStack
                function onCurrentItemChanged() {
                    if (pageStack.currentItem === gridPage
                            && String(root.currentFolder) !== String(gridPage.folderPath)) {
                        root.loadFolder(gridPage.folderPath, gridPage.filterCategory)
                    }
                }
            }

            RowLayout {
                anchors.fill: parent
                spacing: 0

                MediaGridView {
                    id: gridView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: gridModel
                    mediaBackend: mediaModel
                    tagBackend: tagModel
                    // Only this page reacts: while the image viewer is open on
                    // top, the grid underneath stays out of tag mode.
                    tagMode: root.isTagMode && pageStack.currentItem === gridPage
                    subfolderBackend: subfolderModel

                    onSubfolderClicked: function(subfolderPath) {
                        root.openMediaGrid(subfolderPath, gridPage.filterCategory, gridPage.crumbs)
                    }

                    onEditTagsRequested: function(mediaId) {
                        root.isTagMode = true
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
                    onComicClicked: function(index) {
                        Qt.openUrlExternally(mediaModel.getFileUri(index))
                    }
                    onBookClicked: function(index) {
                        Qt.openUrlExternally(mediaModel.getFileUri(index))
                    }
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

                    onDeleteRequested: {
                        root.requestDelete(gridView.selectedIds.slice(), function(removed) {
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

                onDeleteRequested: function(mediaId) {
                    var index = imageViewer.currentIndex
                    root.requestDelete([mediaId], function(removed) {
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
