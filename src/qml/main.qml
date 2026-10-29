import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Gallery 1.0
import "./views"

Kirigami.ApplicationWindow {
    id: root
    width: 900
    height: 700
    visible: true
    title: "Gallery"

    pageStack {
        globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
        defaultColumnWidth: root.width
    }

    property bool isRemoveMode: false

    // Persistent header defined at the ApplicationWindow level
    header: ToolBar {
        RowLayout {
            id: headerRow
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8

            // Both side slots always reserve this same width, whichever
            // side needs more (the Done button's text tends to be wider
            // than the icon-only left button). Keeping both slots equal
            // is what keeps the fillWidth title actually centered --
            // otherwise unequal side widths skew the centered midpoint.
            readonly property real sideSlotWidth: Math.max(leftButton.implicitWidth, doneButtonContent.implicitWidth + 20, 40)

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
                            onTriggered: {
                                root.isRemoveMode = false
                                filePicker.openFolderDialog()
                            }
                        }
                        MenuItem {
                            text: root.isRemoveMode ? "Cancel Removal" : "Remove Folder"
                            icon.name: "edit-delete"
                            onTriggered: root.isRemoveMode = !root.isRemoveMode
                        }
                    }
                }
            }

            // Dynamic Title (Reads from the active page)
            Label {
                text: pageStack.currentItem && pageStack.currentItem.title ? pageStack.currentItem.title : "Collections"
                font.pixelSize: 18
                font.weight: Font.normal
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            // Dynamic Right Button (Done, shown only in remove mode).
            // Built from plain primitives (Rectangle/Icon/Label/MouseArea)
            // rather than a QQC2 Button, since that avoids relying on
            // this style's Button implicit-size/background computation.
            Item {
                id: doneButtonSlot
                Layout.preferredWidth: headerRow.sideSlotWidth
                Layout.preferredHeight: leftButton.height

                Rectangle {
                    id: doneButtonBg
                    anchors.fill: parent
                    anchors.margins: 4
                    radius: 4
                    color: Kirigami.Theme.negativeBackgroundColor
                    opacity: doneMouseArea.containsMouse ? 1.0 : 0.85
                    visible: root.isRemoveMode

                    RowLayout {
                        id: doneButtonContent
                        anchors.centerIn: parent
                        spacing: 4

                        Kirigami.Icon {
                            source: "checkmark"
                            color: Kirigami.Theme.negativeTextColor
                            Layout.preferredWidth: 16
                            Layout.preferredHeight: 16
                        }

                        Label {
                            text: "Done"
                            color: Kirigami.Theme.negativeTextColor
                            font.weight: Font.Medium
                        }
                    }

                    MouseArea {
                        id: doneMouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: root.isRemoveMode
                        onClicked: root.isRemoveMode = false
                    }
                }
            }
        }
    }

    MediaModel {
        id: mediaModel
        filterMode: MediaModel.All
    }

    FolderModel {
        id: folderModel
        currentCategory: "photos" 
    }

    FilePicker {
        id: filePicker
        onFolderSelected: function(selectedFolder) {
            folderModel.addFolder(selectedFolder, folderModel.currentCategory)
        }
    }

    footer: Kirigami.NavigationTabBar {
        id: navTabBar
        // Hidden while the image viewer is open (pageStack depth 3:
        // 1 = folder grid, 2 = folder contents, 3 = image viewer) --
        // switching categories mid-zoom doesn't make sense, and the
        // viewer wants the full window height anyway.
        visible: pageStack.depth < 3
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

    function switchTab(category) {
        folderModel.currentCategory = category
        root.isRemoveMode = false 
        
        while (pageStack.depth > 1) {
            var poppedPage = pageStack.pop()
            if (poppedPage) {
                poppedPage.destroy()
            }
        }
    }

    function openMediaGrid(folderPath, category) {
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
        
        // Convert the path to a string and remove any trailing slashes
        var pathStr = folderPath.toString()
        if (pathStr.endsWith("/")) {
            pathStr = pathStr.slice(0, -1)
        }
        
        // Split the path by slashes and grab the very last segment (the folder name)
        var folderName = pathStr.split("/").pop()
        
        // Push the component and dynamically set its title property
        pageStack.push(mediaGridComponent, { title: folderName })
    }

    pageStack.initialPage: Kirigami.ScrollablePage {
        title: "Collections"

        FolderGridView {
            anchors.fill: parent
            model: folderModel
            
            removeMode: root.isRemoveMode
            onRemoveModeExitRequested: root.isRemoveMode = false
            
            onAddFolderRequested: filePicker.openFolderDialog()

            onFolderClicked: function(folderPath) {
                openMediaGrid(folderPath, folderModel.currentCategory)
            }
        }
    }
    
    Component {
        id: mediaGridComponent
        
        Kirigami.ScrollablePage {
            // The title property is dynamically injected by pageStack.push()
            
            MediaGridView {
                model: mediaModel 
                anchors.fill: parent

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
        }
    }

    Component {
        id: imageViewerComponent

        Kirigami.Page {
            id: viewerPage

            // Overridden by pageStack.push(imageViewerComponent, { initialIndex: ... })
            property int initialIndex: 0

            // Pulls the title dynamically from the imageViewer component 
            // which updates on every image switch
            title: imageViewer.title

            // No page padding/margins -- the image should go edge to edge.
            padding: 0

            ImageViewer {
                id: imageViewer
                anchors.fill: parent
                model: mediaModel
                initialIndex: viewerPage.initialIndex
            }
        }
    }
}