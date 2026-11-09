// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

// Downloads with gallery-dl and yt-dlp (DownloadService): an address, the folder to save into (the one you are in,
// unless you choose another), and the queue with what each download has saved so far. With both tools installed,
// which one is chosen by the address unless you pick it. Opened from the header's button.
Popup {
    id: panel

    property var service: null
    property var boards: null               // BoardService (the boards a download can go on)
    property string tab: ""                 // the tab the panel was opened on (a new board belongs to it)
    property string folder: ""              // where the next download goes (a path or a file:// address)
    property var boardList: []
    property var sites: []                  // the sites gallery-dl's config has a section for (names only)
    property bool configOpen: false
    signal problem(string text)

    readonly property var heights: [0, 2160, 1440, 1080, 720, 480]
    onOpened: {
        boardList = boards ? boards.boards(tab) : []
        sites = service ? service.gallerySites() : []
    }

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
        // a new folder for this download, inside the one above
        RowLayout {
            Layout.fillWidth: true
            CheckBox {
                id: inNewFolder
                text: "In a new folder:"
            }
            TextField {
                id: newFolderName
                objectName: "downloadSubfolder"
                Layout.fillWidth: true
                enabled: inNewFolder.checked
                placeholderText: "Folder name"
            }
        }
        // ...and on a board (one of this tab's, or a new one)
        RowLayout {
            Layout.fillWidth: true
            CheckBox {
                id: onBoard
                text: "Add to a board:"
            }
            ComboBox {
                id: boardChoice
                Layout.fillWidth: true
                enabled: onBoard.checked
                textRole: "name"
                model: [{ id: 0, name: "New board\u2026" }].concat(panel.boardList)
            }
        }
        TextField {
            id: newBoardName
            Layout.fillWidth: true
            visible: onBoard.checked && boardChoice.currentIndex === 0
            placeholderText: "New board's name"
        }
        // only some of the results (both empty: all)
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Files: from" }
            TextField {
                id: firstFile
                Layout.preferredWidth: 64
                validator: IntValidator { bottom: 1 }
                placeholderText: "1"
            }
            Label { text: "to" }
            TextField {
                id: lastFile
                Layout.preferredWidth: 64
                validator: IntValidator { bottom: 1 }
                placeholderText: "all"
            }
            Item { Layout.fillWidth: true }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: panel.service !== null && panel.service.tools.indexOf("yt-dlp") >= 0
            Label { text: "Videos up to:" }
            ComboBox {
                id: heightChoice
                model: ["Best", "2160p", "1440p", "1080p", "720p", "480p"]
                currentIndex: panel.service ? Math.max(0, panel.heights.indexOf(panel.service.maxHeight)) : 0
                onActivated: function(index) { panel.service.maxHeight = panel.heights[index] }
            }
            Item { Layout.fillWidth: true }
        }

        RowLayout {
            Layout.fillWidth: true
            // with both tools: chosen by the address (videos to yt-dlp), or the one picked here
            ComboBox {
                id: toolChoice
                objectName: "downloadTool"
                visible: panel.service !== null && panel.service.tools.length > 1
                model: panel.service ? ["Automatic"].concat(panel.service.tools) : []
            }
            Item { Layout.fillWidth: true }
            Button {
                id: start
                objectName: "downloadStart"
                text: "Download"
                icon.name: "download"
                enabled: panel.service !== null && address.text.trim() !== "" && panel.folder !== ""
                         && (!inNewFolder.checked || newFolderName.text.trim() !== "")
                         && (!onBoard.checked || boardChoice.currentIndex > 0 || newBoardName.text.trim() !== "")
                onClicked: {
                    if (!enabled) return
                    var tool = toolChoice.visible && toolChoice.currentIndex > 0 ? toolChoice.currentText : ""
                    var options = { tab: panel.tab, first: parseInt(firstFile.text) || 0, last: parseInt(lastFile.text) || 0 }
                    if (inNewFolder.checked) options.subfolder = newFolderName.text.trim()
                    if (onBoard.checked) {
                        if (boardChoice.currentIndex > 0) options.board = panel.boardList[boardChoice.currentIndex - 1].id
                        else options.boardName = newBoardName.text.trim()
                    }
                    if (panel.service.download(address.text.trim(), panel.folder, tool, options) > 0) {
                        address.text = ""
                        firstFile.text = ""
                        lastFile.text = ""
                    } else {
                        panel.problem("That download could not be started")
                    }
                }
            }
        }

        // where logins, API keys and site settings live: each tool's own config, opened in the text editor
        ToolButton {
            text: "Logins and site settings"
            icon.name: panel.configOpen ? "arrow-down" : "arrow-right"
            flat: true
            onClicked: panel.configOpen = !panel.configOpen
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: panel.configOpen
            spacing: Kirigami.Units.smallSpacing
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                opacity: 0.7
                font.pixelSize: 12
                text: "Logins, API keys, cookies and file names are set in each tool's own configuration, which Tetia " +
                      "opens but never reads (only the names of the sites gallery-dl has settings for)."
            }
            Repeater {
                model: panel.service ? panel.service.tools : []
                delegate: RowLayout {
                    required property string modelData
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        text: modelData + ": " + (!panel.service.hasConfig(modelData) ? "no configuration yet"
                              : modelData === "gallery-dl" ? (panel.sites.length > 0 ? panel.sites.join(", ") : "no sites set up yet")
                              : "has a configuration")
                    }
                    Button {
                        text: "Open"
                        icon.name: "document-edit"
                        flat: true
                        onClicked: panel.service.openConfig(modelData)
                    }
                }
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
                        ToolTip.visible: siteHover.hovered
                        ToolTip.text: modelData.url + "\n(" + modelData.tool + ")"
                        HoverHandler { id: siteHover }
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
