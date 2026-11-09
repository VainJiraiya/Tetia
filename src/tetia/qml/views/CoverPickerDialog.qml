// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// Pick the cover of a comic, EPUB or PDF from its own pages. The host gives it a
// CoverPicker that has already opened the file, then calls open().
Dialog {
    id: root

    property var picker: null
    property int selected: -1

    signal coverApplied()       // (not "applied": Dialog has its own, for an Apply button)
    signal failed()

    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true
    width: Math.min(parent ? parent.width - Kirigami.Units.gridUnit * 2 : 900, 900)
    height: Math.min(parent ? parent.height - Kirigami.Units.gridUnit * 2 : 640, 640)
    padding: Kirigami.Units.largeSpacing
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    onOpened: root.selected = -1
    onClosed: if (root.picker) root.picker.close()

    function apply() {
        if (root.selected < 0 || !root.picker) return
        if (root.picker.choose(root.selected)) {
            root.close()
            root.coverApplied()
        } else {
            root.failed()
        }
    }

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
                text: "Choose the cover"
                Layout.fillWidth: true
            }
            Label {
                text: root.picker ? root.picker.title : ""
                elide: Text.ElideMiddle
                opacity: 0.7
                Layout.fillWidth: true
            }
            Item { Layout.fillHeight: true }
        }
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Label {
            visible: root.picker && root.picker.count === 0
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: root.picker ? root.picker.message : ""
        }

        Label {
            visible: root.picker && root.picker.count > 0
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: "Click the page to use as the cover, then Use as cover (or double-click it). "
                  + (root.picker && root.picker.count >= 150 ? "The first 150 pages are shown." : "")
        }

        GridView {
            id: grid
            visible: root.picker && root.picker.count > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            model: root.picker ? root.picker.count : 0
            cellWidth: 150
            cellHeight: 225

            // spread the leftover width so the columns sit centred
            property int columns: Math.max(1, Math.floor(width / cellWidth))
            property real sidePadding: Math.max(0, Math.floor((width - columns * cellWidth) / 2))

            delegate: Item {
                id: page
                required property int index
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
                        color: root.selected === page.index ? Qt.alpha(Kirigami.Theme.highlightColor, 0.2)
                                                            : Qt.alpha(Kirigami.Theme.textColor, pageHover.hovered ? 0.07 : 0.03)
                        border.width: root.selected === page.index ? 2 : 0
                        border.color: Kirigami.Theme.highlightColor

                        HoverHandler { id: pageHover; cursorShape: Qt.PointingHandCursor }

                        Image {
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: pageNumber.top
                            anchors.margins: 4
                            source: root.picker && root.picker.token !== ""
                                    ? "image://bookpage/" + root.picker.token + "/" + page.index : ""
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                        }

                        Label {
                            id: pageNumber
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 4
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: page.index + 1
                            font: Kirigami.Theme.smallFont
                            opacity: 0.7
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: root.selected = page.index
                            onDoubleClicked: {
                                root.selected = page.index
                                root.apply()
                            }
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
            text: "Use the automatic cover"
            icon.name: "edit-undo"
            visible: root.picker && root.picker.custom
            onClicked: {
                if (root.picker.useAutomatic()) {
                    root.close()
                    root.coverApplied()
                }
            }
        }
        Item { Layout.fillWidth: true }
        Button {
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            text: "Cancel"
            onClicked: root.close()
        }
        Button {
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            text: "Use as cover"
            highlighted: true
            enabled: root.selected >= 0
            onClicked: root.apply()
        }
    }
}
