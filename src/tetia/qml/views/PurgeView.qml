// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

// Purge mode: go through a folder's pictures one at a time, swiping each to the right to keep it or to
// the left to mark it for the trash. Nothing is touched until the review at the end. The deck itself
// (what is waiting, what was decided, undo) is the PurgeSession; this is only how it looks and feels.
Kirigami.Page {
    id: root

    // Set by whoever opens it
    property var mediaIds: []
    property string folderName: ""

    title: "Purge: " + folderName
    padding: 0

    // main.qml: this page is neither a folder nor the viewer, and its back button asks first
    readonly property bool isPurge: true
    readonly property bool interceptBack: session.hasProgress

    signal cancelRequested()                // the header's back button was pressed (asks first if anything was decided)
    signal trashRequested(var ids)          // the review was confirmed: these media ids go to the trash
    signal finished(string message)         // leave the purge (the message is shown briefly, or empty)

    readonly property alias purgeSession: session
    property bool flying: false             // the card is on its way off the screen
    property bool zoomed: zoomFactor > 1.01
    property real zoomFactor: 1.0
    property bool showMetadata: false

    readonly property real threshold: stage.width * 0.30          // how far to drag before it counts
    readonly property real swipe: Math.max(-1, Math.min(1, card.x / threshold))
    readonly property bool canDecide: session.currentId >= 0 && !flying && !review.opened

    PurgeSession {
        id: session
        objectName: "purgeSession"
    }

    Component.onCompleted: {
        if (!session.start(root.mediaIds)) root.finished("There are no images to purge here")
        keys.forceActiveFocus()
    }

    // ---- deciding ---------------------------------------------------------------------------

    // Send the card off to the left (trash) or right (keep), then decide
    function flyOff(decision) {
        if (!canDecide) return
        flying = true
        flyAnim.decision = decision
        flyX.to = (decision === "trash" ? -1 : 1) * stage.width * 1.25
        flyAnim.start()
    }

    function settle() {
        var velocity = dragVelocity            // pixels per millisecond at the moment of release
        if (card.x <= -threshold || (velocity < -1.2 && card.x < -40)) flyOff("trash")
        else if (card.x >= threshold || (velocity > 1.2 && card.x > 40)) flyOff("keep")
        else springBack.start()
    }

    property real dragVelocity: 0

    ParallelAnimation {
        id: flyAnim
        property string decision: ""
        NumberAnimation { id: flyX; target: card; property: "x"; duration: 220; easing.type: Easing.InQuad }
        NumberAnimation { target: card; property: "opacity"; to: 0; duration: 220 }
        onFinished: {
            session.decide(decision)
            card.x = 0                          // the next image appears in place
            card.opacity = 1
            root.zoomFactor = 1.0
            root.flying = false
            if (session.pending === 0) root.openReview()
        }
    }

    NumberAnimation { id: springBack; target: card; property: "x"; to: 0; duration: 180; easing.type: Easing.OutBack }

    function requestCancel() {
        if (session.hasProgress) cancelDialog.open()
        else root.finished("")
    }

    // The header's back button comes here
    onCancelRequested: requestCancel()

    function openReview() {
        if (session.trashCount === 0 && session.pending === 0) {
            root.finished("Nothing was marked for the trash")
            return
        }
        review.open()
    }

    // The host tells us how the trashing went. What could not be moved stays marked so it can be retried.
    function trashFinished(removedIds) {
        session.forget(removedIds)
        if (session.trashCount === 0) {
            review.close()
            var n = removedIds.length
            root.finished(n === 1 ? "Moved 1 image to the trash" : "Moved " + n + " images to the trash")
        }
    }

    // ---- keys ----------------------------------------------------------------------------------

    Item {
        id: keys
        objectName: "purgeKeys"
        anchors.fill: parent
        focus: true
        // Backspace, Escape and Alt+Left are also "go back" shortcuts elsewhere in the app. Say these keys are ours
        // so they reach onPressed below, instead of leaving the page without asking.
        Keys.onShortcutOverride: function(event) {
            var plain = event.modifiers === Qt.NoModifier
            if ((plain && (event.key === Qt.Key_Backspace || event.key === Qt.Key_Escape))
                    || (event.key === Qt.Key_Left && (event.modifiers & Qt.AltModifier))) {
                event.accepted = true
            }
        }
        Keys.onPressed: function(event) {
            if (review.opened) return
            // Ctrl, Alt and Meta combinations are not ours (Alt+Left would otherwise count as a swipe)
            if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) { event.accepted = true; return }
            switch (event.key) {
            case Qt.Key_Left:      root.flyOff("trash"); break
            case Qt.Key_Right:     root.flyOff("keep"); break
            case Qt.Key_Backspace: if (!root.flying) session.undo(); break
            case Qt.Key_Up:        if (!root.flying) session.goBack(); break
            case Qt.Key_Down:      if (!root.flying) session.goForward(); break
            case Qt.Key_Escape:    root.requestCancel(); break
            case Qt.Key_I:         root.showMetadata = !root.showMetadata; break
            default: return
            }
            event.accepted = true
        }
    }

    // ---- the strip that says this is not the viewer -------------------------------------------------

    Rectangle {
        id: strip
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: Kirigami.Units.gridUnit * 2.6
        color: Qt.alpha(Kirigami.Theme.negativeTextColor, 0.16)

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Qt.alpha(Kirigami.Theme.negativeTextColor, 0.5)
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.largeSpacing
            anchors.rightMargin: Kirigami.Units.largeSpacing

            Button {
                text: "Cancel"
                icon.name: "dialog-cancel"
                onClicked: root.requestCancel()
                ToolTip.visible: hovered
                ToolTip.delay: 600
                ToolTip.text: "Stop purging. Nothing is moved to the trash. (Esc)"
            }
            Item { Layout.fillWidth: true }
            Kirigami.Icon {
                source: "edit-clear-all"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
            Label {
                text: "Purge: " + root.folderName
                font.weight: Font.DemiBold
                elide: Text.ElideMiddle
                Layout.maximumWidth: root.width * 0.5
            }
            Item { Layout.fillWidth: true }
            Button {
                text: "Review now"
                icon.name: "go-next"
                enabled: session.trashCount > 0 && !root.flying
                onClicked: root.openReview()
                ToolTip.visible: hovered
                ToolTip.delay: 600
                ToolTip.text: session.trashCount > 0 ? "Stop here and review the images marked for the trash"
                                                     : "Mark an image for the trash first"
            }
        }
    }

    // ---- the stage: the card ----------------------------------------------------------------------------

    Item {
        id: stage
        anchors.top: strip.bottom
        anchors.bottom: controls.top
        anchors.left: parent.left
        anchors.right: parent.right
        clip: true

        // The card is the image itself. It is dragged sideways, tilts around its bottom edge, and flies off.
        Item {
            id: card
            x: 0
            y: 0
            width: stage.width
            height: stage.height
            transformOrigin: Item.Bottom
            rotation: root.zoomed ? 0 : (card.x / stage.width) * 40

            Flickable {
                id: flick
                anchors.fill: parent
                anchors.margins: Kirigami.Units.largeSpacing * 2
                clip: true
                interactive: root.zoomed
                boundsBehavior: Flickable.StopAtBounds
                contentWidth: width * root.zoomFactor
                contentHeight: height * root.zoomFactor

                Image {
                    id: photo
                    width: flick.contentWidth
                    height: flick.contentHeight
                    source: session.currentUri
                    asynchronous: true
                    fillMode: Image.PreserveAspectFit
                }

                // double-click to look closely, centred on where you clicked
                TapHandler {
                    acceptedButtons: Qt.LeftButton
                    onDoubleTapped: function(eventPoint) {
                        var pointX = eventPoint.position.x - flick.contentX
                        var pointY = eventPoint.position.y - flick.contentY
                        var from = root.zoomFactor
                        var to = root.zoomed ? 1.0 : 2.5
                        root.zoomFactor = to
                        flick.contentX = Math.max(0, Math.min(flick.contentWidth - flick.width, eventPoint.position.x / from * to - pointX))
                        flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, eventPoint.position.y / from * to - pointY))
                    }
                }
            }

            // What the swipe will do, fading in as you drag
            Item {
                id: verdict
                visible: !root.zoomed
                anchors.centerIn: flick
                width: photo.paintedWidth
                height: photo.paintedHeight

                readonly property real trashAmount: Math.max(0, -root.swipe)
                readonly property real keepAmount: Math.max(0, root.swipe)

                Rectangle {
                    anchors.fill: parent
                    color: verdict.trashAmount > 0 ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.positiveTextColor
                    opacity: 0.30 * Math.max(verdict.trashAmount, verdict.keepAmount)
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: Kirigami.Units.gridUnit * 6
                    height: width
                    radius: width / 2
                    color: Qt.rgba(0, 0, 0, 0.55)
                    opacity: Math.max(verdict.trashAmount, verdict.keepAmount)
                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: parent.width * 0.6
                        height: width
                        isMask: true
                        source: verdict.trashAmount > 0 ? "edit-delete" : "dialog-ok-apply"
                        color: verdict.trashAmount > 0 ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.positiveTextColor
                    }
                }
            }

            // a favorite is easy to trash by reflex
            Kirigami.Icon {
                visible: session.currentFavorite
                source: "starred-symbolic"
                width: Kirigami.Units.iconSizes.medium
                height: width
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: Kirigami.Units.largeSpacing * 2
                color: Kirigami.Theme.neutralTextColor
                isMask: true
            }
        }

        // swiping: drag the card sideways (not while zoomed, where a drag pans the picture)
        DragHandler {
            id: swipeHandler
            target: card
            enabled: !root.zoomed && !root.flying && root.canDecide
            yAxis.enabled: false
            property real lastX: 0
            property real lastTime: 0
            onActiveChanged: {
                if (active) {
                    root.dragVelocity = 0
                    lastTime = 0
                } else {
                    root.settle()
                }
            }
            onTranslationChanged: {
                var now = Date.now()
                if (lastTime > 0 && now > lastTime) root.dragVelocity = (card.x - lastX) / (now - lastTime)
                lastX = card.x
                lastTime = now
            }
        }

        // the next picture, loaded ahead of time so it is there the moment this one leaves
        Image {
            visible: false
            source: session.nextUri
            asynchronous: true
        }

        // the buttons from the viewer: look at the next or the previous waiting picture without deciding
        RoundButton {
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            icon.name: "go-previous"
            opacity: session.canGoBack && !root.flying ? 0.85 : 0
            enabled: opacity > 0.05
            Behavior on opacity { NumberAnimation { duration: 150 } }
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: "The previous waiting image (Up)"
            onClicked: session.goBack()
        }
        RoundButton {
            anchors.right: parent.right
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            icon.name: "go-next"
            opacity: session.canGoForward && !root.flying ? 0.85 : 0
            enabled: opacity > 0.05
            Behavior on opacity { NumberAnimation { duration: 150 } }
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: "The next waiting image (Down)"
            onClicked: session.goForward()
        }

        // the metadata button, as in the viewer: file size and dimensions help you decide
        ToolButton {
            id: infoButton
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: 8
            icon.name: "help-about-symbolic"
            display: AbstractButton.IconOnly
            opacity: 0.85
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Metadata (I)"
            onClicked: root.showMetadata = !root.showMetadata
        }

        // the count chip: how many images are still waiting
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            anchors.horizontalCenter: parent.horizontalCenter
            width: chipColumn.implicitWidth + 24
            height: chipColumn.implicitHeight + 12
            radius: Math.min(height / 2, 20)
            color: Qt.rgba(0, 0, 0, 0.65)

            Column {
                id: chipColumn
                anchors.centerIn: parent
                spacing: 0
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: session.pending + " left"
                    color: "white"
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: session.trashCount > 0
                    text: session.trashCount + " to trash"
                    color: Qt.lighter(Kirigami.Theme.negativeTextColor, 1.5)
                    font.pixelSize: 11
                }
            }
        }
    }

    MetadataPanel {
        visible: root.showMetadata
        anchors.top: strip.bottom
        anchors.bottom: controls.top
        anchors.right: parent.right
        mediaId: root.showMetadata ? session.currentId : -1
        onCloseRequested: root.showMetadata = false
    }

    // ---- the buttons: trash, undo, keep ------------------------------------------------------------------------

    Item {
        id: controls
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: Kirigami.Units.gridUnit * 4

        RowLayout {
            anchors.centerIn: parent
            spacing: Kirigami.Units.largeSpacing

            Button {
                text: "Trash"
                icon.name: "edit-delete"
                icon.color: Kirigami.Theme.negativeTextColor
                implicitWidth: Kirigami.Units.gridUnit * 7
                enabled: root.canDecide
                onClicked: root.flyOff("trash")
                ToolTip.visible: hovered
                ToolTip.delay: 600
                ToolTip.text: "Mark for the trash (Left)"
            }
            Button {
                text: "Undo"
                icon.name: "edit-undo"
                enabled: session.canUndo && !root.flying
                onClicked: session.undo()
                ToolTip.visible: hovered
                ToolTip.delay: 600
                ToolTip.text: "Bring back the last image (Backspace)"
            }
            Button {
                text: "Keep"
                icon.name: "dialog-ok-apply"
                icon.color: Kirigami.Theme.positiveTextColor
                implicitWidth: Kirigami.Units.gridUnit * 7
                enabled: root.canDecide
                onClicked: root.flyOff("keep")
                ToolTip.visible: hovered
                ToolTip.delay: 600
                ToolTip.text: "Keep it (Right)"
            }
        }
    }

    // ---- the review, and giving up ----------------------------------------------------------------------------------

    PurgeReviewDialog {
        id: review
        session: session
        onConfirmed: root.trashRequested(session.trashItems().map(function(item) { return item.id }))
        onBackToPurging: {
            review.close()
            if (session.pending === 0) session.undo()      // nothing waits: bring the last one back instead of reopening this
            keys.forceActiveFocus()
        }
        onCancelPurge: {
            review.close()
            root.finished("")
        }
    }

    Kirigami.PromptDialog {
        id: cancelDialog
        title: "Stop purging?"
        subtitle: session.trashCount > 0
                  ? (session.trashCount === 1 ? "The image you marked for the trash stays where it is."
                                              : "The " + session.trashCount + " images you marked for the trash stay where they are.")
                    + " Nothing is deleted."
                  : "Nothing is deleted."
        standardButtons: Kirigami.Dialog.Cancel
        customFooterActions: [
            Kirigami.Action {
                text: "Stop purging"
                icon.name: "dialog-cancel"
                onTriggered: {
                    cancelDialog.close()
                    root.finished("Purge cancelled")
                }
            }
        ]
        onClosed: keys.forceActiveFocus()
    }
}
