import QtQuick
import QtQuick.Controls

// Full-screen image viewer, built mouse/keyboard-first (this is a desktop
// app, not a touch one -- see the notes below on why drag-to-swipe was
// removed in favor of buttons/arrow keys).
// Root item IS the view, same pattern as MediaGridView.qml.
ListView {
    id: root

    // Which item to land on when the viewer first opens. Set once from
    // outside via pageStack.push(component, { initialIndex: ... }).
    property int initialIndex: 0

    // Whether the left/right nav buttons are currently shown. Only true
    // while the mouse is actively moving -- see hoverTracker below.
    property bool controlsVisible: true
    
    // TWEAK 2: Auto-hiding state for the bottom counter chip
    property bool chipVisible: true

    // TWEAK 2: Read the file name from the currently active delegate so 
    // the global header can display it.
    property string title: currentItem ? currentItem.fileName : ""

    orientation: ListView.Horizontal
    snapMode: ListView.SnapOneItem
    highlightRangeMode: ListView.StrictlyEnforceRange

    // Fixed duration (not velocity-based) so every page change snaps in
    // exactly this long, regardless of how it was triggered -- gives a
    // consistent, crisp transition instead of the mushy variable-speed
    // snap you get from flick-velocity-driven paging.
    highlightMoveDuration: 180

    clip: true
    cacheBuffer: width * 2

    // This is a desktop app with no touchscreen to test against, so
    // drag-to-swipe is out entirely -- navigation is only ever driven by
    // the on-screen buttons or arrow keys below. Setting this false also
    // means the per-image Flickable (used for panning while zoomed) never
    // has to fight this outer view for a drag gesture.
    interactive: false

    focus: true
    Keys.onLeftPressed: goPrevious()
    Keys.onRightPressed: goNext()

    function goNext() {
        if (root.currentIndex < root.count - 1) {
            root.currentIndex += 1
        }
    }

    function goPrevious() {
        if (root.currentIndex > 0) {
            root.currentIndex -= 1
        }
    }

    Component.onCompleted: {
        root.currentIndex = root.initialIndex
        root.positionViewAtIndex(root.initialIndex, ListView.Beginning)
        root.forceActiveFocus()
        hideControlsTimer.start()
        hideChipTimer.start()
    }

    // TWEAK 2: Restart the chip timer every time the image changes
    onCurrentIndexChanged: {
        root.chipVisible = true
        hideChipTimer.restart()
    }

    delegate: Item {
        id: page
        width: root.width
        height: root.height

        // True once the user has pinched/double-clicked past 1x zoom.
        // While true, the inner Flickable takes over dragging for panning.
        property bool zoomed: photo.scale > 1.02
        
        // Expose the model's fileName so the ListView can read it as currentItem.fileName
        property string fileName: model.fileName 

        Flickable {
            id: flick
            anchors.fill: parent
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            // Only pannable once actually zoomed in.
            interactive: page.zoomed

            contentWidth: Math.max(width, photo.width * photo.scale)
            contentHeight: Math.max(height, photo.height * photo.scale)

            // TWEAK 1: Disable the animations while the user is dragging or the 
            // kinetic engine is flicking. This allows raw, instant frame updates 
            // during pans and stops the diagonal smoothing arc.
            Behavior on contentX { 
                enabled: !flick.moving
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic } 
            }
            Behavior on contentY { 
                enabled: !flick.moving
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic } 
            }

            Image {
                id: photo

                // Fixed at (0,0), deliberately NOT anchors.centerIn.
                // Flickable reparents its declared children into an
                // internal contentItem whose size tracks contentWidth/
                // contentHeight -- which grow as scale grows. centerIn
                // was re-centering photo within that *growing* box on
                // every scale change, silently fighting the explicit
                // contentX/contentY math below (which assumes photo's
                // unscaled top-left sits at content-space 0,0 always).
                // That fight is what produced the shifted, direction-
                // inconsistent zoom target you were seeing.
                x: 0
                y: 0
                width: flick.width
                height: flick.height

                source: model.fileUri
                asynchronous: true
                fillMode: Image.PreserveAspectFit

                property real minScale: 1.0
                property real maxScale: 4.0
                scale: 1.0

                // TopLeft matches Flickable's own content coordinate
                // origin, so the zoom-to-cursor math in onDoubleTapped
                // below can treat scale and pan as the same coordinate
                // space instead of fighting a mismatched pivot point.
                transformOrigin: Item.TopLeft

                Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
            }

            PinchArea {
                anchors.fill: parent
                pinch.target: photo
                pinch.minimumScale: photo.minScale
                pinch.maximumScale: photo.maxScale
                onPinchFinished: {
                    if (photo.scale < photo.minScale) {
                        photo.scale = photo.minScale
                    }
                }
            }

            // Double-click to zoom, centered on the actual cursor position
            // rather than always toward the top-left.
            TapHandler {
                id: doubleTapHandler
                acceptedButtons: Qt.LeftButton
                onDoubleTapped: {
                    if (photo.scale > 1.0) {
                        // Zooming back out: just reset to fit -- there's no
                        // meaningful "zoom to cursor" for the outward case.
                        photo.scale = 1.0
                        flick.contentX = 0
                        flick.contentY = 0
                    } else {
                        // point.position is in flick.contentItem coordinates
                        // (because TapHandler is reparented there by Flickable),
                        // NOT flick viewport coordinates. Convert to viewport
                        // coordinates before using for zoom-to-point math.
                        var mx = point.position.x - flick.contentX
                        var my = point.position.y - flick.contentY

                        // PreserveAspectFit letterboxes the image within
                        // photo's box whenever its aspect ratio doesn't
                        // match the viewport's -- paintedWidth/Height is
                        // the actual rendered picture, smaller than the
                        // box on one axis. Ignore double-clicks that land
                        // in that empty gutter rather than on the picture.
                        var gutterX = (photo.width - photo.paintedWidth) / 2
                        var gutterY = (photo.height - photo.paintedHeight) / 2
                        var withinImage = mx >= gutterX && mx <= gutterX + photo.paintedWidth &&
                                           my >= gutterY && my <= gutterY + photo.paintedHeight
                        if (!withinImage) {
                            return
                        }

                        var newScale = photo.maxScale > 2.0 ? 2.0 : photo.maxScale
                        var ratio = newScale / photo.scale

                        // Standard zoom-to-point formula: keep whatever
                        // content point is currently under the cursor
                        // pinned under the cursor after the scale change.
                        var targetX = (flick.contentX + mx) * ratio - mx
                        var targetY = (flick.contentY + my) * ratio - my

                        photo.scale = newScale
                        flick.contentX = Math.max(0, Math.min(targetX, photo.width * newScale - flick.width))
                        flick.contentY = Math.max(0, Math.min(targetY, photo.height * newScale - flick.height))
                    }
                }
            }
        }

        BusyIndicator {
            anchors.centerIn: parent
            running: photo.status === Image.Loading
            visible: running
        }

        Label {
            anchors.centerIn: parent
            visible: photo.status === Image.Error
            text: "Couldn't load this image"
            color: palette.text
        }
    }

    // --- Desktop navigation chrome ---
    
    MouseArea {
        id: hoverTracker
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onPositionChanged: {
            root.controlsVisible = true
            hideControlsTimer.restart()
        }
    }

    Timer {
        id: hideControlsTimer
        interval: 2000
        onTriggered: root.controlsVisible = false
    }
    
    Timer {
        id: hideChipTimer
        interval: 2000
        onTriggered: root.chipVisible = false
    }

    RoundButton {
        id: prevButton
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        icon.name: "go-previous"
        hoverEnabled: true

        opacity: (root.controlsVisible && root.currentIndex > 0) ? 0.85 : 0
        enabled: opacity > 0.05
        Behavior on opacity { NumberAnimation { duration: 150 } }

        onHoveredChanged: {
            if (hovered) {
                root.controlsVisible = true
                hideControlsTimer.stop()
            } else {
                hideControlsTimer.restart()
            }
        }

        onClicked: root.goPrevious()
    }

    RoundButton {
        id: nextButton
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        icon.name: "go-next"
        hoverEnabled: true

        opacity: (root.controlsVisible && root.currentIndex < root.count - 1) ? 0.85 : 0
        enabled: opacity > 0.05
        Behavior on opacity { NumberAnimation { duration: 150 } }

        onHoveredChanged: {
            if (hovered) {
                root.controlsVisible = true
                hideControlsTimer.stop()
            } else {
                hideControlsTimer.restart()
            }
        }

        onClicked: root.goNext()
    }
    
    // TWEAK 2: The bottom counter chip
    Rectangle {
        id: counterChip
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 32
        anchors.horizontalCenter: parent.horizontalCenter
        width: chipLabel.implicitWidth + 24
        height: chipLabel.implicitHeight + 12
        radius: height / 2
        color: Qt.rgba(0, 0, 0, 0.65)
        
        opacity: root.chipVisible ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 250 } }

        Label {
            id: chipLabel
            anchors.centerIn: parent
            text: (root.currentIndex + 1) + " / " + root.count
            color: "white"
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
    }
}