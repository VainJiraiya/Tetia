import QtQuick
import QtQuick.Controls

// Defines the main grid layout that will hold all the media tiles
GridView {
    id: grid

    // Emitted when a tile is tapped, routed by the tapped item's own type
    // so callers don't have to re-check model roles themselves.
    signal imageClicked(int index)
    signal videoClicked(int index)
    signal comicClicked(int index)
    signal bookClicked(int index)
    signal selectionChanged()
    signal deleteRequested()

    // Exposed properties
    property int columns: Math.max(1, Math.floor(width / cellWidth))
    property real sidePadding: Math.max(0, Math.floor((width - (columns * cellWidth)) / 2))
    property bool tagMode: false
    property var tagBackend: null
    property var mediaBackend: null
    property var selectedIds: []

    onTagModeChanged: {
        if (!tagMode) {
            selectedIds = []
        }
    }

    function toggleSelection(mediaId) {
        var newIds = grid.selectedIds.slice()
        var idx = newIds.indexOf(mediaId)
        if (idx >= 0) { newIds.splice(idx, 1) } else { newIds.push(mediaId) }
        grid.selectedIds = newIds
        selectionChanged()
    }

    function addRangeSelection(fromIndex, toIndex) {
        var start = Math.min(fromIndex, toIndex)
        var end = Math.max(fromIndex, toIndex)
        for (var i = start; i <= end; i++) {
            var item = grid.model.data(grid.model.index(i), 257)
            if (item !== null && item !== undefined) {
                var idx = grid.selectedIds.indexOf(item)
                if (idx < 0) {
                    grid.selectedIds.push(item)
                }
            }
        }
        selectionChanged()
    }

    Menu {
        id: contextMenu
        x: 0
        y: 0
        MenuItem {
            text: "Edit tags"
            onTriggered: {
                grid.tagMode = true
                var mediaId = contextMenuData.mediaId
                grid.selectedIds = [mediaId]
                grid.selectionChanged()
            }
        }
    }

    property var contextMenuData: ({})

    // We increase the cell height slightly so there is room for both the picture and the text
    cellWidth: 160
    cellHeight: 185
    clip: true

    // 1. Calculate how many columns can fit, and how much left-over space there is

    // The delegate dictates how every individual item in the model is drawn on the screen
    delegate: Item {
        width: grid.cellWidth
        height: grid.cellHeight

        // 2. We shift the visual contents inside the delegate to perfectly center the whole block.
        // This avoids QML bugs with dynamic margins breaking the scroll position.
        Item {
            x: grid.sidePadding
            width: parent.width
            height: parent.height

            // Creates a container for the tile with a small margin so items don't touch each other
            Rectangle {
                anchors.fill: parent
                anchors.margins: 8
                color: "transparent"
                radius: 4

                // Selection highlight
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: -2
                    radius: 6
                    color: "transparent"
                    border.color: Qt.rgba(0.2, 0.6, 1.0, 0.6)
                    border.width: 2
                    visible: grid.tagMode && grid.selectedIds.indexOf(model.mediaId) >= 0
                }

                // TWEAK 2: The image thumbnail setup
                Image {
                    id: thumbnail
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    // Anchors the bottom of the image to the top of the text label
                    anchors.bottom: fileNameText.top
                    anchors.bottomMargin: 6

                    // Request the image through our thumbnail provider
                    source: "image://thumbnail/" + model.fileUri

                    // PreserveAspectFit scales the image down so the entire picture fits
                    // inside the square without cropping any edges off
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }

                // TWEAK 3: The file name label setup
                Text {
                    id: fileNameText
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right

                    text: model.fileName

                    // Pulls the native text color from the user's active KDE Plasma color scheme
                    color: palette.text

                    // Centers the text and adds an ellipsis (...) in the middle if the filename
                    // is too long to fit on one line
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideMiddle
                    font.pixelSize: 12
                }

                // Checkmark badge (top-right)
                Rectangle {
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 4
                    width: 20
                    height: 20
                    radius: 10
                    color: Qt.rgba(0.2, 0.6, 1.0, 0.85)
                    visible: grid.tagMode && grid.selectedIds.indexOf(model.mediaId) >= 0

                    Text {
                        anchors.centerIn: parent
                        text: "\u2713"
                        color: "white"
                        font.pixelSize: 12
                        font.bold: true
                    }
                }

                // Routes the tap to whichever signal matches this item's type.
                // Each delegate instance knows its own type via the model
                // roles already in context here, so we decide the route at
                // the source instead of making callers re-check roles.
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: {
                        if (mouse.button === Qt.RightButton) {
                            grid.contextMenuData = { mediaId: model.mediaId }
                            contextMenu.popup()
                        } else if (grid.tagMode) {
                            if (mouse.modifiers & Qt.ShiftModifier && grid.selectedIds.length > 0) {
                                var lastSelected = grid.selectedIds[grid.selectedIds.length - 1]
                                var lastIdx = -1
                                for (var i = 0; i < grid.model.count; i++) {
                                    if (grid.model.data(grid.model.index(i), 257) === lastSelected) {
                                        lastIdx = i
                                        break
                                    }
                                }
                                if (lastIdx >= 0) {
                                    grid.addRangeSelection(lastIdx, index)
                                }
                            } else if (mouse.modifiers & Qt.ControlModifier) {
                                grid.toggleSelection(model.mediaId)
                            } else {
                                if (grid.selectedIds.indexOf(model.mediaId) >= 0) {
                                    grid.toggleSelection(model.mediaId)
                                } else {
                                    grid.selectedIds = [model.mediaId]
                                    grid.selectionChanged()
                                }
                            }
                        } else {
                            if (model.isVideo) {
                                grid.videoClicked(index)
                            } else if (model.isComic) {
                                grid.comicClicked(index)
                            } else if (model.isBook) {
                                grid.bookClicked(index)
                            } else {
                                grid.imageClicked(index)
                            }
                        }
                    }
                }
            }
        }
    }

    TagPanel {
        visible: grid.tagMode && grid.selectedIds.length > 0
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        mediaIds: grid.selectedIds
        tagModel: grid.tagBackend
        mediaModel: grid.mediaBackend
    }
}
