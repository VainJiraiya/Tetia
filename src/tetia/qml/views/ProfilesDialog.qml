// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// Lists the profiles and lets you switch, create, rename and delete them.
// Switching (and creating, which switches into the new profile) goes through
// the ProfileModel: it unlocks a vault first (KDE asks for the password),
// locks the one you're leaving, and relaunches the app.
Kirigami.Dialog {
    id: dialog

    // The ProfileModel
    property var backend: null

    // "" (nothing), "create", or the id of the profile being renamed
    property string editing: ""
    property string error: ""

    // Creating: a vault only when Plasma Vault is usable AND "Encrypted" is chosen
    readonly property bool useVault: backend !== null && backend.vaultAvailable && kindBox.currentIndex === 0

    title: "Profiles"
    preferredWidth: Kirigami.Units.gridUnit * 32
    padding: Kirigami.Units.largeSpacing
    showCloseButton: true

    onClosed: {
        editing = ""
        error = ""
    }

    function startCreate() {
        error = ""
        if (backend) backend.refreshVaults()   // the first (and only) time D-Bus is asked about Plasma Vault
        editing = "create"
        kindBox.currentIndex = 0
        createName.text = ""
        if (useVault) {
            vaultBox.currentIndex = vaultBox.count > 0 ? 0 : -1
        }
    }

    function startRename(id, currentName) {
        error = ""
        editing = id
        renameField.text = currentName
        renameField.forceActiveFocus()
        renameField.selectAll()
    }

    function chosenDevice() {
        var list = backend.vaults
        return (useVault && vaultBox.currentIndex >= 0 && vaultBox.currentIndex < list.length)
               ? list[vaultBox.currentIndex].device : ""
    }

    function commitCreate() {
        var text = createName.text
        var problem = useVault ? backend.vaultProfileError(text, chosenDevice())
                               : backend.nameError(text, "")
        if (problem !== "") {
            dialog.error = problem
            return
        }
        var id = useVault ? backend.createVaultProfile(text, chosenDevice())
                          : backend.createProfile(text)
        if (id === "") {
            dialog.error = "Couldn't create the profile."
            return
        }
        dialog.editing = ""
        dialog.close()
        backend.switchTo(id)   // unlocks the vault if there is one, then relaunches
    }

    function commitRename() {
        var problem = backend.nameError(renameField.text, dialog.editing)
        if (problem === "") problem = backend.renameProfile(dialog.editing, renameField.text)
        if (problem !== "") {
            dialog.error = problem
            return
        }
        dialog.editing = ""
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.8
            text: "General is your normal library. A private profile has its own library, tags, favorites, covers and thumbnails, kept apart from everything else. An encrypted profile lives inside a KDE Plasma Vault: Tetia asks KDE to unlock it when you switch in, and locks it when you switch out or quit. Switching restarts Tetia."
        }

        Repeater {
            model: dialog.backend ? dialog.backend.profiles : []

            delegate: RowLayout {
                id: row
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: row.modelData.kind === "vault" ? "security-high"
                          : (row.modelData.kind === "local" ? "security-low" : "user-home")
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                }
                ColumnLayout {
                    spacing: 0
                    Layout.fillWidth: true
                    Label {
                        text: row.modelData.name
                        font.weight: row.modelData.active ? Font.DemiBold : Font.Normal
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Label {
                        visible: row.modelData.kind !== "general"
                        text: row.modelData.kind === "vault" ? "Encrypted (Plasma Vault)" : "Local, not encrypted"
                        font.pixelSize: 11
                        opacity: 0.6
                    }
                }
                Label {
                    visible: row.modelData.active
                    text: "Current"
                    opacity: 0.6
                }
                Button {
                    visible: !row.modelData.active
                    text: "Switch"
                    onClicked: {
                        dialog.close()
                        dialog.backend.switchTo(row.modelData.id)
                    }
                }
                ToolButton {
                    visible: row.modelData.isPrivate
                    icon.name: "edit-rename"
                    display: AbstractButton.IconOnly
                    ToolTip.visible: hovered
                    ToolTip.text: "Rename"
                    onClicked: dialog.startRename(row.modelData.id, row.modelData.name)
                }
                ToolButton {
                    visible: row.modelData.isPrivate && !row.modelData.active
                    icon.name: "edit-delete"
                    display: AbstractButton.IconOnly
                    ToolTip.visible: hovered
                    ToolTip.text: row.modelData.kind === "vault" ? "Remove" : "Delete"
                    onClicked: {
                        deleteDialog.profileId = row.modelData.id
                        deleteDialog.profileName = row.modelData.name
                        deleteDialog.profileKind = row.modelData.kind
                        deleteDialog.open()
                    }
                }
            }
        }

        // ---- Rename ----------------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            visible: dialog.editing !== "" && dialog.editing !== "create"

            TextField {
                id: renameField
                Layout.fillWidth: true
                placeholderText: "New name"
                maximumLength: 40
                onAccepted: dialog.commitRename()
                onTextChanged: dialog.error = ""
                Keys.onEscapePressed: dialog.editing = ""
            }
            Button {
                text: "Rename"
                highlighted: true
                onClicked: dialog.commitRename()
            }
            Button {
                text: "Cancel"
                onClicked: dialog.editing = ""
            }
        }

        // ---- Create ----------------------------------------------------------
        Kirigami.Separator {
            Layout.fillWidth: true
            visible: dialog.editing === "create"
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: dialog.editing === "create"
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                level: 4
                text: "New private profile"
            }

            // Without Plasma Vault the local kind is the only one: say why and how to get encryption
            Label {
                Layout.fillWidth: true
                visible: dialog.backend !== null && !dialog.backend.vaultAvailable
                wrapMode: Text.WordWrap
                text: dialog.backend && dialog.backend.inSandbox
                      ? "Encrypted profiles aren't available in the Flatpak version of Tetia: the sandbox can't reach KDE Plasma Vaults. You can make a local private profile: its data is kept separate from General, but it is not encrypted."
                      : "Encrypted profiles need KDE Plasma Vaults, which isn't available here (" + (dialog.backend ? dialog.backend.vaultUnavailableReason : "") + ")\n\nInstall Plasma Vaults (the plasma-vault package) and gocryptfs or CryFS to keep a private profile encrypted. Until then you can make a local private profile: its data is kept separate from General, but it is not encrypted."
            }

            ComboBox {
                id: kindBox
                Layout.fillWidth: true
                visible: dialog.backend !== null && dialog.backend.vaultAvailable
                model: ["Encrypted — stored in a Plasma Vault", "Local — separate folder, not encrypted"]
            }

            RowLayout {
                Layout.fillWidth: true
                visible: dialog.useVault

                ComboBox {
                    id: vaultBox
                    Layout.fillWidth: true
                    model: dialog.backend ? dialog.backend.vaults : []
                    textRole: "name"
                    displayText: count > 0 ? currentText : "No unused vault yet"
                    onCurrentIndexChanged: {
                        if (currentIndex >= 0 && createName.text === "" && model.length > currentIndex)
                            createName.text = model[currentIndex].name
                    }
                }
                Button {
                    text: "New vault…"
                    icon.name: "list-add"
                    onClicked: dialog.backend.requestNewVault()
                    ToolTip.visible: hovered
                    ToolTip.text: "Opens KDE's vault wizard. The new vault shows up here when it's done."
                }
            }

            Label {
                Layout.fillWidth: true
                visible: dialog.useVault
                wrapMode: Text.WordWrap
                opacity: 0.7
                font.pixelSize: 11
                text: "Pick a vault you've already made in KDE, or make one with “New vault…”. Tetia never sees the vault's password: KDE asks for it."
            }

            RowLayout {
                Layout.fillWidth: true

                TextField {
                    id: createName
                    Layout.fillWidth: true
                    placeholderText: "Profile name"
                    maximumLength: 40
                    onAccepted: dialog.commitCreate()
                    onTextChanged: dialog.error = ""
                    Keys.onEscapePressed: dialog.editing = ""
                }
                Button {
                    text: dialog.useVault ? "Create and unlock" : "Create and switch"
                    highlighted: true
                    onClicked: dialog.commitCreate()
                }
                Button {
                    text: "Cancel"
                    onClicked: dialog.editing = ""
                }
            }
        }

        Label {
            Layout.fillWidth: true
            visible: dialog.error !== ""
            text: dialog.error
            color: Kirigami.Theme.negativeTextColor
            wrapMode: Text.WordWrap
        }

        Button {
            visible: dialog.editing === ""
            icon.name: "list-add"
            text: "New private profile…"
            onClicked: dialog.startCreate()
        }
    }

    Kirigami.PromptDialog {
        id: deleteDialog

        property string profileId: ""
        property string profileName: ""
        property string profileKind: ""

        title: (profileKind === "vault" ? "Remove “" : "Delete “") + profileName + "”?"
        subtitle: profileKind === "vault"
                  ? "This only removes the profile from Tetia. Its library, tags and covers stay inside the vault (in its .tetia folder); delete them there, or delete the vault in KDE's settings, to get rid of them."
                  : "Its library, tags, favorites, covers and thumbnails are permanently deleted. Your files on disk are not touched."
        standardButtons: Kirigami.Dialog.Cancel
        customFooterActions: [
            Kirigami.Action {
                text: deleteDialog.profileKind === "vault" ? "Remove profile" : "Delete profile"
                icon.name: "edit-delete"
                onTriggered: {
                    deleteDialog.close()
                    var failure = dialog.backend.deleteProfile(deleteDialog.profileId)
                    if (failure !== "") dialog.error = failure
                }
            }
        ]
    }
}
