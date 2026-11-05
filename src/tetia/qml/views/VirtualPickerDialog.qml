// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// Choose the virtual folder a selection goes into. The folders are listed as a tree (nested ones indented),
// and a click on one picks it. The host gives it `targets` ([{id, name, depth}]) and `count`.
Kirigami.Dialog {
    id: root

    property var targets: []
    property int count: 1
    property bool canCreate: true

    // What to do when a folder is chosen ((id, name)) or "New virtual folder" is pressed (): set by openFor
    property var onChosen: null
    property var onNew: null
    function openFor(pick, make) {
        onChosen = pick
        onNew = make
        open()
    }

    title: count === 1 ? "Add 1 item to a virtual folder" : "Add " + count + " items to a virtual folder"
    standardButtons: Kirigami.Dialog.Cancel
    padding: 0
    preferredWidth: Kirigami.Units.gridUnit * 24

    customFooterActions: [
        Kirigami.Action {
            text: "New virtual folder…"
            icon.name: "folder-new"
            enabled: root.canCreate
            onTriggered: {
                root.close()
                if (root.onNew) root.onNew()
            }
        }
    ]

    ListView {
        id: list
        implicitHeight: Math.min(Kirigami.Units.gridUnit * 18, Math.max(Kirigami.Units.gridUnit * 4, contentHeight))
        clip: true
        model: root.targets
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        delegate: ItemDelegate {
            id: row
            required property var modelData
            width: list.width
            leftPadding: Kirigami.Units.largeSpacing + modelData.depth * Kirigami.Units.gridUnit * 1.5
            text: modelData.name
            icon.name: "folder"
            display: AbstractButton.TextBesideIcon
            onClicked: {
                root.close()
                if (root.onChosen) root.onChosen(modelData.id, modelData.name)
            }
        }

        Label {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 2
            visible: root.targets.length === 0
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            opacity: 0.7
            text: "There are no virtual folders here yet. Make one with the button below."
        }
    }
}
