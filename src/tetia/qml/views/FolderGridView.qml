// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0
import "thumbUri.js" as ThumbUri

Item {
    id: root

    property var model
    property bool removeMode: false

    // Tile size: -2 .. +2, two tiles more or fewer in a row per step (14, 12, 10, 8 and 6 tiles per row in a
    // 2560 px wide window), always an even number, like the folder and file grids (see MediaGridView), whose
    // tiles are two per row smaller at every level.
    property int tileLevel: 0
    readonly property real minCell: [175, 205, 245, 300, 400][tileLevel + 2]
    readonly property int thumbHint: [128, 128, 256, 256, 512][tileLevel + 2]
    readonly property bool showLabels: true

    // Every tile, in every tab, has the same shape: a vertical rectangle (3:4) with the cover cropped to fill
    // it and the name below. 3:4 is shorter than a manga cover (about 2:3), so a cover loses only a little
    // (cut from the bottom, so the title at the top stays), and still takes a landscape picture without it
    // looking squeezed. The gap between tiles is wider than the gap inside one, so each reads as one thing.
    readonly property real coverRatio: 4 / 3
    // Layout: one rule shared with MediaGridView (keep them in sync): a tile sits `inset` inside its cell and the
    // grid keeps `edge` at the sides, so a tile is edge + inset = 24 px from the wall and the header, whatever the
    // tile size or the window; the cells stretch a little to fill the width. The gap between tiles is 2 * inset.
    readonly property int inset: 12
    readonly property int edge: 12

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
        // no margin of its own: the tiles inset themselves, so the grid lines up with the folder grids
        visible: grid.count > 0

        model: root.model
        // the count badge shrinks with the tile, but not below a readable size, and is never bigger than at size 0
        // (as in MediaGridView)
        readonly property int badgeFont: Math.max(9, Math.min(11, Math.round(11 * cellWidth / 180)))
        property int columns: Math.max(1, Math.floor((width - 2 * root.edge) / root.minCell))
        property real sidePadding: root.edge
        cellWidth: (width - 2 * root.edge) / columns
        topMargin: root.edge
        bottomMargin: root.edge
        readonly property real coverHeight: Math.round((cellWidth - 2 * root.inset) * root.coverRatio)
        cellHeight: coverHeight + (root.showLabels ? 34 : 0) + 2 * root.inset
        clip: true

        delegate: Item {
            id: cell
            width: grid.cellWidth
            height: grid.cellHeight

            Item {
                id: cover
                x: grid.sidePadding + root.inset
                y: root.inset
                width: grid.cellWidth - 2 * root.inset
                height: grid.coverHeight

                // The Image is drawn to a texture (layer), which ShadowedTexture rounds the corners of.
                // opacity 0, not visible: false: an invisible item is left out of the render pass that
                // updates its layer, and the texture would go stale.
                Image {
                    id: coverImage
                    anchors.fill: parent
                    opacity: 0
                    layer.enabled: true
                    source: model.heroPath && model.heroPath.length > 0
                            ? "image://thumbnail/" + ThumbUri.fromPath(model.heroPath) + root.revisionSuffix : ""
                    sourceSize: Qt.size(root.thumbHint, root.thumbHint)
                    fillMode: Image.PreserveAspectCrop
                    verticalAlignment: Image.AlignTop      // a taller cover loses its bottom, not its title
                    asynchronous: true
                    cache: true
                }
                Kirigami.ShadowedTexture {
                    anchors.fill: parent
                    source: coverImage
                    visible: model.heroPath && model.heroPath.length > 0 && coverImage.status !== Image.Error
                    opacity: root.removeMode ? 0.4 : 1.0
                    shadow.size: 0           // only for the rounded corners, not a drop shadow
                    color: Qt.rgba(0, 0, 0, 0.12)
                    radius: 6
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                }
                // no picture: a soft tile with a folder on it
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: Qt.alpha(Kirigami.Theme.textColor, 0.06)
                    visible: (!model.heroPath || model.heroPath.length === 0 || coverImage.status === Image.Error)
                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: Math.min(parent.width, parent.height) * 0.4
                        height: width
                        source: "folder"
                        opacity: 0.5
                    }
                }
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: Kirigami.Theme.negativeBackgroundColor
                    opacity: 0.55
                    visible: root.removeMode
                    Kirigami.Icon {
                        source: "edit-delete"
                        anchors.centerIn: parent
                        width: 48
                        height: 48
                        color: Kirigami.Theme.negativeTextColor
                    }
                }
                Rectangle {
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: Math.round(grid.badgeFont * 0.6)
                    width: Math.max(height, countBadgeText.implicitWidth + grid.badgeFont)
                    height: Math.round(grid.badgeFont * 1.9)
                    radius: height / 2
                    color: Qt.rgba(0, 0, 0, 0.5)
                    visible: model.itemCount !== undefined && model.itemCount > 0 && !root.removeMode && root.showLabels
                             && !model.singleFile && (!model.isSeries || hoverArea.containsMouse)
                    Label {
                        id: countBadgeText
                        anchors.centerIn: parent
                        text: model.itemCount || 0
                        color: "white"
                        font.pixelSize: grid.badgeFont
                        font.weight: Font.Bold
                    }
                }
                // outline on hover, or in remove mode
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: -2
                    radius: 8
                    color: "transparent"
                    border.width: root.removeMode || hoverArea.containsMouse ? 2 : 0
                    border.color: root.removeMode ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor
                }
            }

            Label {
                x: grid.sidePadding + root.inset
                anchors.top: cover.bottom
                anchors.topMargin: 6
                width: grid.cellWidth - 2 * root.inset
                visible: root.showLabels
                text: model.folderName || ""
                color: root.removeMode ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideMiddle
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            MouseArea {
                id: hoverArea
                x: grid.sidePadding + root.inset
                y: root.inset
                width: grid.cellWidth - 2 * root.inset
                height: grid.cellHeight - 2 * root.inset
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
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

    // NOTE: The floating "Done" pill that used to live here has been
    // replaced by a Done button in the ApplicationWindow's custom header
    // bar (right side, styled like the hamburger menu button). That
    // button toggles isRemoveMode directly, so removeModeExitRequested
    // is no longer emitted from here, but the signal is left in place
    // in case other callers still rely on it.
}