// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

// Downloads with gallery-dl (DownloadService): an address, the folder to save into (the one you are in, unless
// you choose another), and the queue with what each download has saved so far. Opened from the header's button.
Popup {
    id: panel

    property var service: null
    property string folder: ""              // where the next download goes (a path or a file:// address)
    signal problem(string text)

    width: 380
    padding: Kirigami.Units.largeSpacing
    modal: false
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    function folderName(path) {
        var parts = String(path).replace(/\/+$/, "").split("/")
        var last = parts[parts.length - 1] || String(path)
        if (String(path).indexOf("file://") === 0) {
            try { last = decodeURIComponent(last) } catch (e) {}
        }
        return last
    }
    function siteOf(url) {
        var match = String(url).match(/^[a-z]+:\/\/([^\/]+)(.*)$/i)
        return match ? match[1].replace(/^www\./, "") + match[2] : url
    }

    FilePicker {
        id: destination
        onFolderSelected: function(selected) { panel.folder = selected }
        onFolderRejected: function(text) { panel.problem(text) }
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            level: 4
            text: "Download"
        }
        TextField {
            id: address
            objectName: "downloadAddress"
            Layout.fillWidth: true
            placeholderText: "Address of a post, gallery or search"
            onAccepted: start.clicked()
        }
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                elide: Text.ElideMiddle
                text: panel.folder !== "" ? "Into: " + panel.folderName(panel.folder) : "Choose a folder to save into"
                opacity: panel.folder !== "" ? 1 : 0.7
                ToolTip.visible: folderHover.hovered && panel.folder !== ""
                ToolTip.text: panel.folder
                HoverHandler { id: folderHover }
            }
            Button {
                text: "Change…"
                icon.name: "folder-open"
                flat: true
                onClicked: destination.openFolderDialog()
            }
        }
        Button {
            id: start
            objectName: "downloadStart"
            Layout.alignment: Qt.AlignRight
            text: "Download"
            icon.name: "download"
            enabled: panel.service !== null && address.text.trim() !== "" && panel.folder !== ""
            onClicked: {
                if (!enabled) return
                if (panel.service.add(address.text.trim(), panel.folder) > 0) address.text = ""
                else panel.problem("That download could not be started")
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
            visible: queue.count > 0
        }
        ListView {
            id: queue
            objectName: "downloadQueue"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, 300)
            clip: true
            visible: count > 0
            model: panel.service ? panel.service.jobs : []
            delegate: RowLayout {
                required property var modelData
                width: ListView.view.width
                spacing: Kirigami.Units.smallSpacing
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Label {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        text: panel.siteOf(modelData.url)
                    }
                    Label {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        opacity: 0.7
                        font.pixelSize: 12
                        readonly property string count: modelData.files === 1 ? "1 file" : modelData.files + " files"
                        text: {
                            var into = " · " + panel.folderName(modelData.folder)
                            switch (modelData.state) {
                            case "waiting": return "Waiting" + into
                            case "downloading": return (modelData.files > 0 ? count : "Starting") + into
                            case "done": return "Done: " + count + into
                            case "cancelled": return "Cancelled" + (modelData.files > 0 ? ": " + count : "") + into
                            default: return (modelData.message || "Failed") + into
                            }
                        }
                        color: modelData.state === "failed" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                    }
                }
                ToolButton {
                    icon.name: "dialog-cancel"
                    display: AbstractButton.IconOnly
                    visible: modelData.state === "waiting" || modelData.state === "downloading"
                    ToolTip.visible: hovered
                    ToolTip.text: "Cancel"
                    onClicked: panel.service.cancel(modelData.id)
                }
            }
        }
        Button {
            Layout.alignment: Qt.AlignRight
            flat: true
            text: "Clear finished"
            visible: panel.service !== null && queue.count > 0
                     && panel.service.jobs.some(function(j) { return j.state !== "waiting" && j.state !== "downloading" })
            onClicked: panel.service.clearFinished()
        }
    }
}
