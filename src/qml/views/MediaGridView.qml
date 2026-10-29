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

    // We increase the cell height slightly so there is room for both the picture and the text
    cellWidth: 160
    cellHeight: 185 
    clip: true

    // 1. Calculate how many columns can fit, and how much left-over space there is
    property int columns: Math.max(1, Math.floor(width / cellWidth))
    property real sidePadding: Math.max(0, Math.floor((width - (columns * cellWidth)) / 2))

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

                // Routes the tap to whichever signal matches this item's type.
                // Each delegate instance knows its own type via the model
                // roles already in context here, so we decide the route at
                // the source instead of making callers re-check roles.
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
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