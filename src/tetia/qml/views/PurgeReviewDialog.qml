// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// The last look before anything goes to the trash: every image marked for it, in a grid like the
// cover picker's. Clicking an image keeps it after all. The host gives it the PurgeSession.
Dialog {
    id: root

    property var session: null
    // The marked images, [{id, uri, name, favorite}], refreshed whenever the session changes
    property var items: []

    signal confirmed()          // Move to trash
    signal backToPurging()      // return to the deck, nothing lost
    signal cancelPurge()        // give up the whole purge

    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true
    width: Math.min(parent ? parent.width - Kirigami.Units.gridUnit * 2 : 900, 900)
    height: Math.min(parent ? parent.height - Kirigami.Units.gridUnit * 2 : 640, 640)
    padding: Kirigami.Units.largeSpacing
    closePolicy: Popup.CloseOnEscape

    function refresh() { root.items = root.session ? root.session.trashItems() : [] }

    Connections {
        target: root.session
        function onChanged() { root.refresh() }
    }
    onAboutToShow: refresh()
    onRejected: root.backToPurging()          // Escape

    header: Item {
        implicitHeight: Kirigami.Units.gridUnit * 3
        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.largeSpacing
            anchors.rightMargin: Kirigami.Units.largeSpacing
            spacing: 0
            Item { Layout.fillHeight: true }
            Kirigami.Heading {
                level: 3
                text: root.items.length === 0 ? "Nothing is marked for the trash"
                      : "Move " + root.items.length + (root.items.length === 1 ? " image" : " images") + " to the trash?"
                Layout.fillWidth: true
            }
            Label {
                text: "They go to the system trash, so you can restore them from there."
                opacity: 0.7
                Layout.fillWidth: true
            }
            Item { Layout.fillHeight: true }
        }
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: root.items.length === 0 ? "Go back to keep purging, or cancel."
                  : "Click an image to keep it after all."
        }

        GridView {
            id: grid
            visible: root.items.length > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            model: root.items
            cellWidth: 150
            cellHeight: 190

            property int columns: Math.max(1, Math.floor(width / cellWidth))
            property real sidePadding: Math.max(0, Math.floor((width - columns * cellWidth) / 2))

            delegate: Item {
                id: tile
                required property var modelData
                width: grid.cellWidth
                height: grid.cellHeight

                Rectangle {
                    x: grid.sidePadding
                    width: parent.width
                    height: parent.height
                    color: "transparent"

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 6
                        radius: 6
                        color: Qt.alpha(Kirigami.Theme.negativeTextColor, tileHover.hovered ? 0.16 : 0.08)
                        border.width: 1
                        border.color: Qt.alpha(Kirigami.Theme.negativeTextColor, 0.5)

                        HoverHandler { id: tileHover; cursorShape: Qt.PointingHandCursor }

                        Image {
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: nameLabel.top
                            anchors.margins: 4
                            source: "image://thumbnail/" + tile.modelData.uri
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                        }

                        // a favorite is easy to trash by reflex: mark it
                        Kirigami.Icon {
                            visible: tile.modelData.favorite
                            source: "starred-symbolic"
                            width: 18
                            height: 18
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.margins: 6
                            color: Kirigami.Theme.neutralTextColor
                            isMask: true
                        }

                        Label {
                            id: nameLabel
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 4
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: 4
                            anchors.rightMargin: 4
                            text: tile.modelData.name
                            elide: Text.ElideMiddle
                            horizontalAlignment: Text.AlignHCenter
                            font: Kirigami.Theme.smallFont
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: root.session.keepInstead(tile.modelData.id)
                            ToolTip.visible: containsMouse
                            ToolTip.delay: 600
                            ToolTip.text: "Keep this image after all"
                            hoverEnabled: true
                        }
                    }
                }
            }
        }
    }

    footer: RowLayout {
        spacing: Kirigami.Units.smallSpacing

        Button {
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            text: "Back to purging"
            icon.name: "go-previous"
            onClicked: root.backToPurging()
        }
        Item { Layout.fillWidth: true }
        Button {
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            text: "Cancel purge"
            onClicked: root.cancelPurge()
        }
        Button {
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            text: root.items.length === 1 ? "Move 1 to trash" : "Move " + root.items.length + " to trash"
            icon.name: "edit-delete"
            highlighted: true
            enabled: root.items.length > 0
            onClicked: root.confirmed()
        }
    }
}
