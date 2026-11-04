// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

// Side panel showing the standard metadata of one file: size and dates for
// every file, plus what the file itself carries (EXIF, video streams, comic
// and book details). It is docked and styled like the TagPanel, and is
// read-only. The host sets mediaId (a negative id clears it).
Rectangle {
    id: root

    property int mediaId: -1

    // Which edge touches the content, so the divider line is drawn on it.
    property bool dockedRight: true

    signal closeRequested()

    implicitWidth: 320
    height: parent ? parent.height : implicitHeight
    color: Kirigami.Theme.alternateBackgroundColor

    // The reading happens off the UI thread; this panel owns its own so the grid's
    // and the viewer's panels never show each other's file.
    MetadataModel { id: reader }

    onMediaIdChanged: reader.load(root.mediaId)
    Component.onCompleted: reader.load(root.mediaId)

    Kirigami.Separator {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: root.dockedRight ? parent.left : undefined
        anchors.right: root.dockedRight ? undefined : parent.right
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.largeSpacing

        // Header
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "help-about-symbolic"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }

            Kirigami.Heading {
                level: 3
                text: "Metadata"
                Layout.fillWidth: true
                elide: Text.ElideRight
            }

            BusyIndicator {
                running: reader.loading
                visible: reader.loading
                implicitWidth: Kirigami.Units.gridUnit * 1.4
                implicitHeight: implicitWidth
            }

            ToolButton {
                icon.name: "window-close-symbolic"
                display: AbstractButton.IconOnly
                implicitWidth: Kirigami.Units.gridUnit * 1.8
                implicitHeight: implicitWidth
                hoverEnabled: true
                Accessible.name: "Close"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Close"
                onClicked: root.closeRequested()
            }
        }

        Label {
            visible: !reader.loading && reader.sections.length === 0
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            color: Kirigami.Theme.textColor
            opacity: 0.65
            text: "There is no metadata to show."
        }

        Flickable {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: sectionColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            Column {
                id: sectionColumn
                width: scroll.width - Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                Repeater {
                    model: reader.sections

                    delegate: Column {
                        id: sectionDelegate
                        required property var modelData
                        width: sectionColumn.width
                        spacing: Kirigami.Units.smallSpacing

                        Label {
                            text: sectionDelegate.modelData.title
                            font.weight: Font.DemiBold
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            color: Kirigami.Theme.linkColor
                        }

                        Repeater {
                            model: sectionDelegate.modelData.rows

                            delegate: Column {
                                id: rowDelegate
                                required property var modelData
                                width: sectionDelegate.width
                                spacing: 0

                                Label {
                                    text: rowDelegate.modelData.label
                                    font: Kirigami.Theme.smallFont
                                    color: Kirigami.Theme.textColor
                                    opacity: 0.65
                                }
                                // A TextEdit, not a Label, so a value (a path, a prompt) can be selected and copied
                                TextEdit {
                                    width: parent.width
                                    text: rowDelegate.modelData.value
                                    readOnly: true
                                    selectByMouse: true
                                    wrapMode: TextEdit.Wrap
                                    color: Kirigami.Theme.textColor
                                    selectedTextColor: Kirigami.Theme.highlightedTextColor
                                    selectionColor: Kirigami.Theme.highlightColor
                                    font: Kirigami.Theme.defaultFont
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
