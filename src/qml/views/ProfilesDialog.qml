import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// Lists the profiles and lets you switch, create, rename and delete them.
// Switching (and creating, which switches into the new profile) relaunches
// the app, which the ProfileModel does by itself.
Kirigami.Dialog {
    id: dialog

    // The ProfileModel
    property var backend: null

    // What the inline name field is doing: "" (hidden), "create" or a profile id (rename)
    property string editing: ""
    property string error: ""

    title: "Profiles"
    preferredWidth: Kirigami.Units.gridUnit * 30
    padding: Kirigami.Units.largeSpacing
    showCloseButton: true

    onClosed: {
        editing = ""
        error = ""
    }

    function startEditing(mode, currentName) {
        error = ""
        editing = mode
        nameField.text = currentName
        nameField.forceActiveFocus()
        nameField.selectAll()
    }

    function commitName() {
        var mode = dialog.editing
        var text = nameField.text
        var problem = backend.nameError(text, mode === "create" ? "" : mode)
        if (problem !== "") {
            dialog.error = problem
            return
        }
        if (mode === "create") {
            var id = backend.createProfile(text)
            if (id === "") {
                dialog.error = "Couldn't create the profile."
                return
            }
            dialog.editing = ""
            backend.switchTo(id)   // relaunches into the new profile
        } else {
            var failure = backend.renameProfile(mode, text)
            if (failure !== "") {
                dialog.error = failure
                return
            }
            dialog.editing = ""
        }
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.8
            text: "General is your normal library. A private profile has its own library, tags, favorites, covers and thumbnails, kept apart from everything else. Switching restarts Tetia."
        }

        Repeater {
            model: dialog.backend ? dialog.backend.profiles : []

            delegate: RowLayout {
                id: row
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: row.modelData.isPrivate ? "lock" : "user-home"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                }
                Label {
                    text: row.modelData.name
                    font.weight: row.modelData.active ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
                Label {
                    visible: row.modelData.active
                    text: "Current"
                    opacity: 0.6
                }
                Button {
                    visible: !row.modelData.active
                    text: "Switch"
                    onClicked: dialog.backend.switchTo(row.modelData.id)
                }
                ToolButton {
                    visible: row.modelData.isPrivate
                    icon.name: "edit-rename"
                    display: AbstractButton.IconOnly
                    ToolTip.visible: hovered
                    ToolTip.text: "Rename"
                    onClicked: dialog.startEditing(row.modelData.id, row.modelData.name)
                }
                ToolButton {
                    visible: row.modelData.isPrivate && !row.modelData.active
                    icon.name: "edit-delete"
                    display: AbstractButton.IconOnly
                    ToolTip.visible: hovered
                    ToolTip.text: "Delete"
                    onClicked: {
                        deleteDialog.profileId = row.modelData.id
                        deleteDialog.profileName = row.modelData.name
                        deleteDialog.open()
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: dialog.editing !== ""

            TextField {
                id: nameField
                Layout.fillWidth: true
                placeholderText: dialog.editing === "create" ? "Name of the new private profile" : "New name"
                maximumLength: 40
                onAccepted: dialog.commitName()
                onTextChanged: dialog.error = ""
                Keys.onEscapePressed: dialog.editing = ""
            }
            Button {
                text: dialog.editing === "create" ? "Create and switch" : "Rename"
                highlighted: true
                onClicked: dialog.commitName()
            }
            Button {
                text: "Cancel"
                onClicked: dialog.editing = ""
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
            onClicked: dialog.startEditing("create", "")
        }
    }

    Kirigami.PromptDialog {
        id: deleteDialog

        property string profileId: ""
        property string profileName: ""

        title: "Delete “" + profileName + "”?"
        subtitle: "Its library, tags, favorites, covers and thumbnails are permanently deleted. Your files on disk are not touched."
        standardButtons: Kirigami.Dialog.Cancel
        customFooterActions: [
            Kirigami.Action {
                text: "Delete profile"
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
