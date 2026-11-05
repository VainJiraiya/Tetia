// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

Item {
    id: root

    property var model
    property bool removeMode: false

    // Tile size: -2 .. +2, 0 being the size the grid always had (see MediaGridView)
    property int tileLevel: 0
    // (the base cell is 180 wide, so +1 and +2 come to 280 and 400 pixels, as in the media grid)
    readonly property real tileScale: [1 / 3, 2 / 3, 1, 1.55, 2.2][tileLevel + 2]
    readonly property int thumbHint: [128, 128, 256, 256, 512][tileLevel + 2]
    readonly property bool showLabels: tileLevel > -2

    signal folderClicked(string folderPath)
    // A series tile was opened: which chapter to open is "resume", "first" or "next"
    signal seriesRequested(string folderPath, string which)
    // A one-file folder was opened: it shows as that file, so open the file
    signal singleFileRequested(string folderPath)
    // "Choose cover page..." on a one-file folder: the path of its file
    signal coverPickerRequested(string filePath)

    // A cover changed by hand: this number is added to the pictures' URLs so they reload
    property int coverRevision: 0
    readonly property string revisionSuffix: coverRevision > 0 ? "?v=" + coverRevision : ""
    signal addFolderRequested()
    signal removeModeExitRequested()

    ColumnLayout {
        anchors.centerIn: parent
        visible: grid.count === 0
        spacing: 16

        Label {
            text: (root.model && root.model.currentCategory === "favorites")
                  ? "All your faves in one place\nAdd a favourite to get started"
                  : "Ready to start building your collection?"
            font.pixelSize: 18
            color: Kirigami.Theme.textColor
            Layout.alignment: Qt.AlignHCenter
            horizontalAlignment: Text.AlignHCenter
        }

        Button {
            text: "Add Folder"
            icon.name: "folder-add"
            Layout.alignment: Qt.AlignHCenter
            onClicked: root.addFolderRequested()
            visible: root.model && root.model.currentCategory !== "favorites"
        }
    }

    // Opens the image dialog for "Choose cover image..."
    FilePicker {
        id: coverPicker
        onCoverImageSelected: function(folderPath, imagePath) {
            if (root.model) root.model.setCoverFromFile(folderPath, imagePath)
        }
    }

    // Right-click menu for a folder tile
    Menu {
        id: folderMenu
        property string folderPath: ""
        property bool isFavorite: false
        property bool hasCustomCover: false
        property bool isSeries: false
        property bool isSingle: false
        property string singleFile: ""

        MenuItem {
            text: "Choose cover page\u2026"
            icon.name: "view-preview"
            visible: folderMenu.isSingle
            height: visible ? implicitHeight : 0
            onTriggered: root.coverPickerRequested(folderMenu.singleFile)
        }
        MenuItem {
            text: "Browse folder"
            icon.name: "folder-open"
            visible: folderMenu.isSingle
            height: visible ? implicitHeight : 0
            onTriggered: root.folderClicked(folderMenu.folderPath)
        }
        MenuSeparator { visible: folderMenu.isSingle }
        MenuItem {
            text: "Open next chapter"
            icon.name: "go-next"
            visible: folderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: root.seriesRequested(folderMenu.folderPath, "next")
        }
        MenuItem {
            text: "Open previous chapter"
            icon.name: "go-previous"
            visible: folderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: root.seriesRequested(folderMenu.folderPath, "previous")
        }
        MenuItem {
            text: "Open first chapter"
            icon.name: "go-first"
            visible: folderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: root.seriesRequested(folderMenu.folderPath, "first")
        }
        MenuItem {
            text: "Browse chapters"
            icon.name: "view-list-details"
            visible: folderMenu.isSeries
            height: visible ? implicitHeight : 0
            onTriggered: root.folderClicked(folderMenu.folderPath)
        }
        MenuSeparator { visible: folderMenu.isSeries }
        MenuItem {
            text: folderMenu.isSeries ? "Show as a folder" : "Show as a series"
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: folderMenu.isSeries
                          ? "Go back to showing this as an ordinary folder you can open"
                          : "Treat this folder's chapter files as one manga: one tile that opens where you left off"
            icon.name: "bookmarks-symbolic"
            // Only manga folders hold chapters
            visible: root.model && root.model.currentCategory === "manga" && !folderMenu.isSingle
            height: visible ? implicitHeight : 0
            onTriggered: root.model.setSeries(folderMenu.folderPath, !folderMenu.isSeries)
        }
        MenuItem {
            text: "Choose cover image…"
            icon.name: "image-x-generic"
            onTriggered: coverPicker.openCoverImageDialog(folderMenu.folderPath)
        }
        MenuItem {
            text: "Use default cover"
            icon.name: "edit-undo"
            enabled: folderMenu.hasCustomCover
            onTriggered: root.model.clearCover(folderMenu.folderPath)
        }
        MenuSeparator {}
        MenuItem {
            text: folderMenu.isFavorite ? "Remove from favorites" : "Add to favorites"
            icon.name: folderMenu.isFavorite ? "non-starred-symbolic" : "starred-symbolic"
            onTriggered: root.model.setFavorite(folderMenu.folderPath, !folderMenu.isFavorite)
        }
    }

    GridView {
        id: grid
        anchors.fill: parent
        anchors.margins: 16
        visible: grid.count > 0

        model: root.model
        cellWidth: Math.round(180 * root.tileScale)
        cellHeight: root.showLabels ? Math.round(220 * root.tileScale) : cellWidth
        clip: true

        // 1. Calculate the available columns and left-over horizontal space
        property int columns: Math.max(1, Math.floor(width / cellWidth))
        property real sidePadding: Math.floor((width - (columns * cellWidth)) / 2)

        delegate: Item {
            width: grid.cellWidth
            height: grid.cellHeight

            // 2. Shift the delegate's contents visually instead of modifying the layout margins
            Item {
                x: grid.sidePadding
                width: parent.width
                height: parent.height

                Rectangle {
                    id: cardBg
                    anchors.fill: parent
                    anchors.margins: 8
                    radius: 8
                    color: Kirigami.Theme.backgroundColor
                    border.width: 1
                    border.color: Qt.rgba(0, 0, 0, 0.2)
    
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 1
                        spacing: 0
    
                            Item {
                                id: heroRect
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                Layout.minimumHeight: Math.round(100 * root.tileScale)
    
                                // Plain fallback fill so there's a background even
                                // before the image loads / if there's no heroPath.
                                // Must match heroTexture's corner rounding, or its
                                // sharp corners poke out from behind the texture.
    /*                             Rectangle {
                                    anchors.fill: parent
                                    color: Qt.rgba(0, 0, 0, 0.2)
                                    topLeftRadius: cardBg.radius - 1
                                    topRightRadius: cardBg.radius - 1
                                } */
    
                                Image {
                                    id: heroImage
                                    anchors.fill: parent
                                    // opacity: 0 (not visible: false) -- this item
                                    // must still go through a normal render pass
                                    // for its `layer` to update. visible: false
                                    // would prune it from that pass entirely and
                                    // the layer texture below would go stale/blank.
                                    opacity: 0
                                    // layer.enabled forces Qt to pre-render this
                                    // Image (respecting fillMode's crop/fit math)
                                    // into an offscreen texture. Without this,
                                    // ShadowedTexture.source grabs the RAW decoded
                                    // pixmap directly -- bypassing fillMode
                                    // entirely -- and stretches that to fill its
                                    // own bounds regardless of aspect ratio. This
                                    // is what caused the persistent stretching.
                                    layer.enabled: true
                                    source: model.heroPath && model.heroPath.length > 0
                                            ? "image://thumbnail/" + model.heroPath + root.revisionSuffix
                                            : ""
                                    sourceSize: Qt.size(root.thumbHint, root.thumbHint)
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    cache: true
    
                                    onStatusChanged: {
                                        if (status === Image.Error) {
                                            console.log("Image ERROR for", model.folderName, "source:", source)
                                        }
                                    }
                                }
    
                                Kirigami.ShadowedTexture {
                                    id: heroTexture
                                    anchors.fill: parent
                                    source: heroImage
                                    visible: model.heroPath && model.heroPath.length > 0 && heroImage.status !== Image.Error
                                    opacity: root.removeMode ? 0.4 : 1.0
                                    shadow.size: 0  // we only want this for the corner clipping, not a drop shadow
                                    // PreserveAspectFit above leaves transparent gaps around
                                    // non-matching aspect ratios; without this they'd show
                                    // through as ShadowedRectangle's default white fill.
                                    color: Qt.rgba(0, 0, 0, 0.2)
                                    corners {
                                        topLeftRadius: cardBg.radius - 1
                                        topRightRadius: cardBg.radius - 1
                                        bottomLeftRadius: 0
                                        bottomRightRadius: 0
                                    }
    
                                    Behavior on opacity { NumberAnimation { duration: 200 } }
                                }
    
                            Kirigami.Icon {
                                id: fallbackIcon
                                anchors.centerIn: parent
                                width: Math.min(parent.width, parent.height) * 0.45
                                height: width
                                source: "folder"
                                opacity: 0.5
                                visible: (!model.heroPath || model.heroPath.length === 0 || heroImage.status === Image.Error)
                                         && !root.removeMode
                            }
    
                            Rectangle {
                                anchors.bottom: parent.bottom
                                anchors.left: parent.left
                                anchors.right: parent.right
                                height: parent.height * 0.35
                                gradient: Gradient {
                                    GradientStop { position: 0.0; color: "transparent" }
                                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.4) }
                                }
                                visible: model.heroPath && model.heroPath.length > 0 && !root.removeMode
                            }
    
                            Rectangle {
                                anchors.fill: parent
                                color: Kirigami.Theme.negativeBackgroundColor
                                opacity: root.removeMode ? 0.55 : 0.0
                                topLeftRadius: cardBg.radius - 1
                                topRightRadius: cardBg.radius - 1
                                visible: root.removeMode
                            }
    
                            Kirigami.Icon {
                                source: "edit-delete"
                                visible: root.removeMode
                                anchors.centerIn: parent
                                width: 48
                                height: 48
                                color: Kirigami.Theme.negativeTextColor
                            }
    
                            Rectangle {
                                anchors.top: parent.top
                                anchors.right: parent.right
                                anchors.margins: 8
                                width: countBadgeText.implicitWidth + 14
                                height: countBadgeText.implicitHeight + 8
                                radius: height / 2
                                color: Qt.rgba(0, 0, 0, 0.65)
                                visible: model.itemCount !== undefined && model.itemCount > 0 && !root.removeMode && root.showLabels
                                         && !model.singleFile && (!model.isSeries || hoverArea.containsMouse)
    
                                Label {
                                    id: countBadgeText
                                    anchors.centerIn: parent
                                    text: model.itemCount || 0
                                    color: "white"
                                    font.pixelSize: 11
                                    font.weight: Font.Bold
                                }
                            }
                        }
    
                        Rectangle {
                            id: labelBackground
                            Layout.fillWidth: true
                            visible: root.showLabels
                            Layout.preferredHeight: root.showLabels ? 36 : 0
                            
                            // Fill the background color you want
                            color: Kirigami.Theme.alternateBackgroundColor 
                            
                            // Match the bottom corner radii of cardBg so it clips flush to the outer border
                            bottomLeftRadius: cardBg.radius - 1
                            bottomRightRadius: cardBg.radius - 1
    
                            Label {
                                id: folderNameLabel
                                anchors.fill: parent
                                // Put the padding/margins on the text inside the label instead of the container layout
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                anchors.bottomMargin: 2
                                
                                text: model.folderName || ""
                                color: root.removeMode ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideMiddle
                                font.pixelSize: 13
                                font.weight: Font.Bold
                            }
                        }
                    }
                }
    
                Rectangle {
                    id: outlineRect
                    anchors.centerIn: parent
                    width: cardBg.width + 4
                    height: cardBg.height + 4
                    radius: cardBg.radius + 2
                    color: "transparent"
                    border.color: root.removeMode
                                  ? Kirigami.Theme.negativeTextColor
                                  : (hoverArea.containsMouse ? Kirigami.Theme.highlightColor : "transparent")
                    border.width: (hoverArea.containsMouse || root.removeMode) ? 2 : 0
                    z: -1
                }
    
                MouseArea {
                    id: hoverArea
                    anchors.fill: cardBg
                    hoverEnabled: true
                    ToolTip.visible: containsMouse && !root.showLabels
                    ToolTip.delay: 700
                    ToolTip.text: model.folderName || ""
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.RightButton) {
                            if (root.removeMode) return
                            folderMenu.folderPath = model.folderPath
                            folderMenu.isFavorite = !!model.isFavorite
                            folderMenu.hasCustomCover = !!model.hasCustomCover
                            folderMenu.isSeries = !!model.isSeries
                            folderMenu.isSingle = !!model.singleFile
                            folderMenu.singleFile = model.singleFile || ""
                            folderMenu.popup()
                            return
                        }
                        if (root.removeMode) {
                            root.model.removeFolder(model.folderPath)
                        } else if (model.isSeries) {
                            root.seriesRequested(model.folderPath, "resume")
                        } else if (model.singleFile) {
                            root.singleFileRequested(model.folderPath)
                        } else {
                            root.folderClicked(model.folderPath)
                        }
                    }
                }
            }
        }
    }

    // NOTE: The floating "Done" pill that used to live here has been
    // replaced by a Done button in the ApplicationWindow's custom header
    // bar (right side, styled like the hamburger menu button). That
    // button toggles isRemoveMode directly, so removeModeExitRequested
    // is no longer emitted from here, but the signal is left in place
    // in case other callers still rely on it.
}