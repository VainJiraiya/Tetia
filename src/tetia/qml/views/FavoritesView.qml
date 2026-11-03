// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

// The Favorites tab: every favorited item in one place, grouped by type with a
// labelled separator between groups (like Dolphin's "group by type"):
//
//   -------- Collections --------   (favorited folders)
//   ---------- Books ----------
//   ---------- Manga ----------
//   ---------- Images ----------
//   ---------- Videos ----------
//
// Empty groups are left out. The list is built as header rows and rows of
// tiles, so only the rows on screen are ever created, however many favorites
// there are.
Rectangle {
    id: root
    color: Kirigami.Theme.backgroundColor

    // Favorited images only, in the order they appear here. The image viewer
    // pages through this model; imageClicked() carries the index into it.
    property alias imagesModel: imagesModelObj

    signal imageClicked(int index)
    signal openExternally(string fileUri)
    // A favorited folder was clicked; folderUri is a file:// URI, the same
    // form FolderGridView's folderClicked carries.
    signal collectionClicked(string folderUri)

    readonly property int cellWidth: 160
    readonly property int cellHeight: 185

    property int columns: Math.max(1, Math.floor(width / cellWidth))
    property real sidePadding: Math.max(0, Math.floor((width - columns * cellWidth) / 2))
    property var rows: []
    property int total: 0

    FavoritesModel { id: allModel }
    FavoritesModel { id: imagesModelObj; kind: "image" }

    // Re-read from the database (also done whenever the view is shown again,
    // so favorites changed elsewhere appear).
    function refresh() {
        allModel.reload()
        imagesModelObj.reload()
        rebuild()
    }

    function rebuild() {
        var saved = list.contentY
        root.total = allModel.count + allModel.collectionCount
        root.rows = allModel.layoutRows(root.columns)
        list.contentY = saved
    }

    function removeFavorite(mediaId) {
        allModel.removeFavorite(mediaId)
        imagesModelObj.reload()
        rebuild()
    }

    function removeCollectionFavorite(folderUri) {
        allModel.removeCollectionFavorite(folderUri)
        rebuild()
    }

    onColumnsChanged: rebuild()
    onVisibleChanged: if (visible) refresh()
    Component.onCompleted: refresh()

    // Empty state (same wording as the folder view's Favorites tab)
    Label {
        anchors.centerIn: parent
        visible: root.total === 0
        text: "All your faves in one place\nAdd a favourite to get started"
        font.pixelSize: 18
        color: Kirigami.Theme.textColor
        horizontalAlignment: Text.AlignHCenter
    }

    Menu {
        id: contextMenu
        property int mediaId: -1
        property string folderUri: ""   // set instead of mediaId for a folder tile

        MenuItem {
            text: "Remove from favorites"
            icon.name: "non-starred-symbolic"
            onTriggered: {
                if (contextMenu.folderUri !== "") root.removeCollectionFavorite(contextMenu.folderUri)
                else root.removeFavorite(contextMenu.mediaId)
            }
        }
    }

    ListView {
        id: list
        anchors.fill: parent
        visible: root.total > 0
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        bottomMargin: Kirigami.Units.largeSpacing
        model: root.rows
        ScrollBar.vertical: ScrollBar {}

        delegate: Item {
            id: row
            required property var modelData
            readonly property bool isHeader: modelData.type === "header"

            width: list.width
            height: isHeader ? Kirigami.Units.gridUnit * 3 : root.cellHeight

            // ---------- Section ----------
            RowLayout {
                visible: row.isHeader
                anchors.left: parent.left
                anchors.right: parent.right
                // Line up with the block of tiles below
                anchors.leftMargin: root.sidePadding + 8
                anchors.rightMargin: root.sidePadding + 8
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.largeSpacing

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: Qt.alpha(Kirigami.Theme.textColor, 0.25)
                }
                Label {
                    text: row.isHeader ? row.modelData.title : ""
                    font.weight: Font.DemiBold
                    font.pixelSize: 15
                    color: Kirigami.Theme.textColor
                }
                Label {
                    text: row.isHeader ? row.modelData.count : ""
                    font: Kirigami.Theme.smallFont
                    color: Kirigami.Theme.textColor
                    opacity: 0.6
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: Qt.alpha(Kirigami.Theme.textColor, 0.25)
                }
            }

            // ---------- Tiles ----------
            Row {
                visible: !row.isHeader
                x: root.sidePadding

                Repeater {
                    model: row.isHeader ? [] : row.modelData.items

                    delegate: Item {
                        id: tile
                        required property var modelData
                        width: root.cellWidth
                        height: root.cellHeight

                        Rectangle {
                            id: card
                            anchors.fill: parent
                            anchors.margins: 8
                            radius: 6
                            color: Qt.alpha(palette.text, hover.hovered ? 0.07 : 0)

                            HoverHandler {
                                id: hover
                                cursorShape: Qt.PointingHandCursor
                            }

                            ToolTip.visible: hover.hovered && nameText.truncated
                            ToolTip.delay: 700
                            ToolTip.text: tile.modelData.fileName

                            Image {
                                id: tileImage
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: nameText.top
                                anchors.margins: 4
                                anchors.bottomMargin: 6
                                // A folder with no picture has an empty fileUri
                                source: tile.modelData.fileUri !== ""
                                        ? "image://thumbnail/" + tile.modelData.fileUri : ""
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                            }

                            Kirigami.Icon {
                                anchors.centerIn: tileImage
                                width: Math.min(tileImage.width, tileImage.height) * 0.5
                                height: width
                                source: "folder"
                                opacity: 0.5
                                visible: tile.modelData.kind === "collection"
                                         && (tile.modelData.fileUri === "" || tileImage.status === Image.Error)
                            }

                            Text {
                                id: nameText
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 4
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.leftMargin: 4
                                anchors.rightMargin: 4
                                text: tile.modelData.fileName
                                color: palette.text
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideMiddle
                                font.pixelSize: 12
                            }

                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton | Qt.RightButton

                                onClicked: function(mouse) {
                                    if (mouse.button === Qt.RightButton) {
                                        contextMenu.mediaId = tile.modelData.mediaId
                                        contextMenu.folderUri = tile.modelData.kind === "collection"
                                                                ? tile.modelData.folderUri : ""
                                        contextMenu.popup()
                                    } else if (tile.modelData.kind === "collection") {
                                        root.collectionClicked(tile.modelData.folderUri)
                                    } else if (tile.modelData.kind === "image") {
                                        root.imageClicked(tile.modelData.kindIndex)
                                    } else {
                                        // Videos, manga and books open in the system's
                                        // default app, same as in the folder grid.
                                        root.openExternally(tile.modelData.fileUri)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
