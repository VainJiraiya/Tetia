// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// Move to Private Profile: the chosen files leave this library completely (the files, their entries and
// thumbnails here) for a folder of a private profile, taking their tags, favorite and rating with them. A vault
// profile's vault is unlocked first (KDE asks for the password) and may be locked again when done.
Kirigami.Dialog {
    id: dialog

    property var service: null              // PrivateMoveService
    property var mediaIds: []
    property var targets: []
    property var destinations: []
    property string readyProfile: ""        // the profile whose destinations are listed
    property bool moving: false
    property int done: 0
    signal moved(int count, var problems)

    title: "Move to Private Profile"
    preferredWidth: Kirigami.Units.gridUnit * 28
    padding: Kirigami.Units.largeSpacing
    standardButtons: Kirigami.Dialog.NoButton
    closePolicy: moving ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside

    readonly property var target: targets.length > 0 ? targets[Math.max(0, profileChoice.currentIndex)] : null
    readonly property bool canMove: !moving && target !== null && readyProfile === target.id && destinations.length > 0

    function start(ids) {
        mediaIds = ids
        targets = service ? service.targets() : []
        destinations = []
        readyProfile = ""
        moving = false
        done = 0
        open()
        if (target !== null && !target.locked) service.prepare(target.id)    // nothing to unlock: list at once
    }

    Connections {
        target: dialog.service
        function onReady(profileId, list) {
            dialog.readyProfile = profileId
            dialog.destinations = list
            dialog.targets = dialog.service.targets()                         // (now unlocked)
        }
        function onFailed(text) { problem.text = text }
        function onProgress(count, total) { dialog.done = count }
        function onFinished(count, problems) {
            dialog.moving = false
            dialog.close()
            dialog.moved(count, problems)
        }
    }

    customFooterActions: [
        Kirigami.Action {
            text: "Move"
            icon.name: "go-next"
            enabled: dialog.canMove
            onTriggered: {
                problem.text = ""
                dialog.moving = true
                dialog.service.move(dialog.target.id, dialog.destinations[folderChoice.currentIndex].path,
                                    dialog.mediaIds, lockAfter.checked)
            }
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Label { text: (dialog.mediaIds.length === 1 ? "Move 1 file" : "Move " + dialog.mediaIds.length + " files") + " into:" }
            ComboBox {
                id: profileChoice
                Layout.fillWidth: true
                enabled: !dialog.moving
                textRole: "name"
                model: dialog.targets
                onActivated: {
                    problem.text = ""
                    dialog.destinations = []
                    dialog.readyProfile = ""
                    if (dialog.target !== null && !dialog.target.locked) dialog.service.prepare(dialog.target.id)
                }
            }
        }

        // a locked vault: KDE asks for its password
        RowLayout {
            Layout.fillWidth: true
            visible: dialog.target !== null && dialog.target.locked && dialog.readyProfile !== dialog.target.id
            Kirigami.Icon {
                source: "object-locked"
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: implicitWidth
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: dialog.service && dialog.service.busy ? "Waiting for the vault to be unlocked…"
                                                          : "Its vault is locked."
            }
            Button {
                text: "Unlock…"
                icon.name: "object-unlocked"
                enabled: !(dialog.service && dialog.service.busy)
                onClicked: {
                    problem.text = ""
                    dialog.service.prepare(dialog.target.id)
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: dialog.destinations.length > 0
            Label { text: "Folder:" }
            ComboBox {
                id: folderChoice
                Layout.fillWidth: true
                enabled: !dialog.moving
                textRole: "name"
                model: dialog.destinations
            }
        }
        Label {
            Layout.fillWidth: true
            visible: dialog.readyProfile !== "" && dialog.destinations.length === 0
            wrapMode: Text.WordWrap
            text: "That profile has no folder to put them in."
        }
        CheckBox {
            id: lockAfter
            visible: dialog.target !== null && dialog.target.kind === "vault"
            checked: true
            text: "Lock the vault when done"
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.75
            font.pixelSize: 12
            text: "They leave this library completely: the files, their entries here and their thumbnails. Their " +
                  "tags, favorite and rating go with them. A file that can't be copied safely stays where it is."
        }

        ProgressBar {
            Layout.fillWidth: true
            visible: dialog.moving
            from: 0
            to: Math.max(1, dialog.mediaIds.length)
            value: dialog.done
        }
        Label {
            id: problem
            Layout.fillWidth: true
            visible: text !== ""
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
        }
    }
}
