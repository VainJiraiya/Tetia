// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// The library folders of a tab: where its files come from. They are not shown as tiles; the tab shows what is
// in them. Removing one only takes it out of the library: no file is touched.
Kirigami.Dialog {
    id: dialog

    property var folders: null          // FolderModel (the current tab's folders)
    property string tabName: ""

    signal addRequested()
    signal removeRequested(string path)

    title: tabName + " library folders"
    preferredWidth: Kirigami.Units.gridUnit * 30
    padding: Kirigami.Units.largeSpacing
    standardButtons: Kirigami.Dialog.NoButton

    customFooterActions: [
        Kirigami.Action {
            text: "Add Folder…"
            icon.name: "folder-add"
            onTriggered: dialog.addRequested()
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.75
            text: "The " + dialog.tabName + " tab shows what is in these folders. Removing a folder takes it out of the library; no file is touched."
        }

        Label {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.largeSpacing
            horizontalAlignment: Text.AlignHCenter
            visible: list.count === 0
            opacity: 0.7
            text: "No folders yet."
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, Kirigami.Units.gridUnit * 18)
            clip: true
            model: dialog.folders
            delegate: ItemDelegate {
                id: row
                required property string folderPath
                required property string folderName
                width: ListView.view.width
                contentItem: RowLayout {
                    spacing: Kirigami.Units.largeSpacing
                    Kirigami.Icon {
                        source: "folder"
                        Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                        Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Label {
                            Layout.fillWidth: true
                            text: row.folderName
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            text: decodeURIComponent(String(row.folderPath).replace(/^file:\/\//, ""))
                            opacity: 0.7
                            font: Kirigami.Theme.smallFont
                            elide: Text.ElideMiddle
                        }
                    }
                    ToolButton {
                        icon.name: "list-remove"
                        display: AbstractButton.IconOnly
                        text: "Remove from library"
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Remove from the library (no file is touched)"
                        onClicked: dialog.removeRequested(row.folderPath)
                    }
                }
            }
        }
    }
}
