import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

Item {
    id: root

    property var model
    property bool removeMode: false

    signal folderClicked(string folderPath)
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

    GridView {
        id: grid
        anchors.fill: parent
        anchors.margins: 16
        visible: grid.count > 0

        model: root.model
        cellWidth: 180
        cellHeight: 220
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
                                Layout.minimumHeight: 100
    
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
                                            ? "image://thumbnail/" + model.heroPath
                                            : ""
                                    sourceSize: Qt.size(320, 320)
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
                                visible: model.itemCount !== undefined && model.itemCount > 0 && !root.removeMode
    
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
                            Layout.preferredHeight: 36
                            
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
                    onClicked: {
                        if (root.removeMode) {
                            root.model.removeFolder(model.folderPath)
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