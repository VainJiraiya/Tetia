import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// Shown while a vault is being unlocked or locked (see ProfileModel). It can't
// be dismissed: it ends by itself, or the buttons decide what happens.
Kirigami.Dialog {
    id: dialog

    // The ProfileModel
    property var backend: null

    readonly property string stage: backend ? backend.busyStage : ""

    title: stage === "blocked" ? "Couldn't lock the vault"
         : (stage === "locking" ? "Locking vault" : "Unlocking vault")
    preferredWidth: Kirigami.Units.gridUnit * 24
    padding: Kirigami.Units.largeSpacing
    closePolicy: Popup.NoAutoClose
    showCloseButton: false

    Connections {
        target: dialog.backend
        function onBusyChanged() {
            if (dialog.backend.busy) dialog.open()
            else dialog.close()
        }
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            spacing: Kirigami.Units.largeSpacing
            Layout.fillWidth: true

            BusyIndicator {
                running: dialog.stage === "unlocking" || dialog.stage === "locking"
                visible: running
            }
            Kirigami.Icon {
                visible: dialog.stage === "blocked"
                source: "dialog-warning"
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: dialog.backend ? dialog.backend.busyText : ""
            }
        }

        Label {
            visible: dialog.stage === "blocked"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            opacity: 0.8
            text: "Close whatever is using it, then try again. If you carry on without locking, the vault stays unlocked until you lock it yourself."
        }

        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: Kirigami.Units.smallSpacing

            Button {
                visible: dialog.stage === "unlocking"
                text: "Cancel"
                onClicked: dialog.backend.cancelBusy()
            }
            Button {
                visible: dialog.stage === "blocked"
                text: "Continue without locking"
                onClicked: dialog.backend.continueWithoutLock()
            }
            Button {
                visible: dialog.stage === "blocked"
                text: "Try again"
                highlighted: true
                onClicked: dialog.backend.retryLock()
            }
        }
    }
}
