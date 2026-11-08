// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0
import "thumbUri.js" as ThumbUri

// The page of a show (a video folder shown as a series): the poster, description and tags on the left, the
// episodes by season on the right.
Kirigami.Page {
    id: page

    // The show's folder, and the models the tag editor works with (named so they differ from main.qml's ids)
    property string location: ""
    property var tagSource: null
    property var folderSource: null

    readonly property bool isShow: true
    signal playRequested(string uri)
    signal tagClicked(string category, string name)

    // The same colours as the tag editor and the tag browser (keep them in step)
    function categoryColor(category) {
        switch (category) {
        case "creator":   return Kirigami.Theme.negativeTextColor
        case "series":    return Kirigami.Theme.visitedLinkColor
        case "character": return Kirigami.Theme.positiveTextColor
        case "genre":     return Kirigami.Theme.neutralTextColor
        default:          return Kirigami.Theme.linkColor
        }
    }

    title: show.title
    padding: 0

    ShowModel { id: show }
    Component.onCompleted: show.load(location)
    // back from the player: Resume follows the episode last played
    onVisibleChanged: if (visible && location !== "") show.load(location)

    // the seasons folded away, by position
    property var collapsed: ({})
    property bool editingDescription: false
    property bool tagsOpen: false
    property var showTags: []

    function refreshTags() {
        showTags = (tagSource && show.folderUri !== "") ? tagSource.tagsForFolder(show.folderUri) : []
    }
    Connections {
        target: page.tagSource
        function onTagsChanged() { page.refreshTags() }
    }
    Connections {
        target: show
        function onChanged() { page.refreshTags() }
    }

    // The list: a header row per season (none when there is only one) and an episode row each
    readonly property var rows: {
        var out = []
        var seasons = show.seasons
        for (var s = 0; s < seasons.length; s++) {
            var folded = collapsed[s] === true
            if (seasons.length > 1) {
                out.push({ header: true, index: s, name: seasons[s].name, count: seasons[s].episodes.length, folded: folded })
            }
            if (folded) continue
            for (var e = 0; e < seasons[s].episodes.length; e++) {
                out.push({ header: false, episode: seasons[s].episodes[e] })
            }
        }
        return out
    }

    function toggleSeason(index) {
        var next = Object.assign({}, collapsed)
        next[index] = !(next[index] === true)
        collapsed = next
    }

    function play(uri) {
        if (uri !== "") page.playRequested(uri)
    }

    Menu {
        id: episodeMenu
        property var episode: null
        function openFor(ep) { episode = ep; popup() }
        MenuItem {
            text: episodeMenu.episode && episodeMenu.episode.finished ? "Mark as unwatched" : "Mark as watched"
            icon.name: episodeMenu.episode && episodeMenu.episode.finished ? "dialog-cancel" : "checkmark"
            onTriggered: show.markWatched(episodeMenu.episode.uri, !episodeMenu.episode.finished)
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---- the show ----------------------------------------------------------------------------
        ScrollView {
            Layout.fillHeight: true
            Layout.preferredWidth: Math.min(Kirigami.Units.gridUnit * 20, page.width * 0.4)
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: parent.width
                spacing: Kirigami.Units.largeSpacing

                Item { Layout.preferredHeight: Kirigami.Units.smallSpacing }

                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 14)
                    Layout.preferredHeight: Layout.preferredWidth * 1.5
                    radius: 6
                    color: Qt.alpha(Kirigami.Theme.textColor, 0.08)
                    clip: true

                    Image {
                        anchors.fill: parent
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        source: show.poster !== "" ? ThumbUri.source(show.poster) : ""
                        // ask for a thumbnail as big as the poster is drawn, in real pixels (it is 2:3 and fills its box)
                        sourceSize: Qt.size(ThumbUri.tierFor(Math.ceil(height * Screen.devicePixelRatio)),
                                            ThumbUri.tierFor(Math.ceil(height * Screen.devicePixelRatio)))
                    }
                }

                Kirigami.Heading {
                    level: 2
                    text: show.title
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.rightMargin: Kirigami.Units.largeSpacing
                }

                Label {
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    text: show.episodeCount + (show.episodeCount === 1 ? " episode" : " episodes")
                    opacity: 0.65
                }

                // description: typed by hand
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.rightMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                    Label {
                        Layout.fillWidth: true
                        visible: !page.editingDescription
                        text: show.description !== "" ? show.description : "No description yet."
                        opacity: show.description !== "" ? 1 : 0.55
                        wrapMode: Text.WordWrap
                    }
                    TextArea {
                        id: descriptionField
                        Layout.fillWidth: true
                        visible: page.editingDescription
                        wrapMode: TextEdit.Wrap
                        placeholderText: "What is this show about?"
                    }
                    RowLayout {
                        Button {
                            text: page.editingDescription ? "Save" : "Edit description"
                            flat: !page.editingDescription
                            onClicked: {
                                if (page.editingDescription) {
                                    show.setDescription(descriptionField.text)
                                    page.editingDescription = false
                                } else {
                                    descriptionField.text = show.description
                                    page.editingDescription = true
                                    descriptionField.forceActiveFocus()
                                }
                            }
                        }
                        Button {
                            text: "Cancel"
                            flat: true
                            visible: page.editingDescription
                            onClicked: page.editingDescription = false
                        }
                    }
                }

                // tags
                Flow {
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.rightMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: page.showTags
                        delegate: Rectangle {
                            required property var modelData
                            readonly property color accent: page.categoryColor(modelData.category)
                            implicitWidth: chipLabel.implicitWidth + Kirigami.Units.largeSpacing * 2
                            implicitHeight: Kirigami.Units.gridUnit + Kirigami.Units.smallSpacing * 2
                            radius: height / 2
                            color: Qt.alpha(accent, 0.18)
                            border.width: 1
                            border.color: Qt.alpha(accent, 0.5)

                            Label {
                                id: chipLabel
                                anchors.centerIn: parent
                                text: modelData.name.replace(/_/g, " ")
                                font: Kirigami.Theme.smallFont
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.tagClicked(modelData.category, modelData.name)
                            }
                        }
                    }
                }

                Button {
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    icon.name: "tag"
                    text: page.tagsOpen ? "Done" : "Edit tags, rating and favorite"
                    flat: true
                    onClicked: page.tagsOpen = !page.tagsOpen
                }

                Item { Layout.fillHeight: true }
            }
        }

        Kirigami.Separator { Layout.fillHeight: true }

        // ---- the episodes ------------------------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                Button {
                    highlighted: true
                    icon.name: "media-playback-start"
                    text: show.resumeTitle !== "" ? "Resume " + show.resumeTitle + (show.resumeAt !== "" ? " \u00B7 " + show.resumeAt : "") : "Play"
                    enabled: show.episodeCount > 0
                    onClicked: page.play(show.play("resume"))
                }
                Button {
                    text: "Play from the start"
                    visible: show.resumeTitle !== ""
                    onClicked: page.play(show.play("first"))
                }
                Item { Layout.fillWidth: true }
            }

            Kirigami.Separator { Layout.fillWidth: true }

            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: page.rows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}

                delegate: Item {
                    id: row
                    required property var modelData
                    // the episode of this row (none for a season header)
                    readonly property var ep: modelData.header ? null : modelData.episode
                    width: list.width
                    height: modelData.header ? Kirigami.Units.gridUnit * 2.2 : Kirigami.Units.gridUnit * 3.4

                    // season header
                    Rectangle {
                        anchors.fill: parent
                        visible: row.modelData.header
                        color: Qt.alpha(Kirigami.Theme.textColor, headerHover.hovered ? 0.07 : 0.03)
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Kirigami.Units.largeSpacing
                            Kirigami.Icon {
                                source: row.modelData.header && !row.modelData.folded ? "arrow-down" : "arrow-right"
                                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                            }
                            Label {
                                text: row.modelData.header ? row.modelData.name : ""
                                font.bold: true
                            }
                            Label {
                                text: row.modelData.header ? row.modelData.count + (row.modelData.count === 1 ? " episode" : " episodes") : ""
                                opacity: 0.6
                                Layout.fillWidth: true
                            }
                        }
                        HoverHandler { id: headerHover }
                        TapHandler { onTapped: page.toggleSeason(row.modelData.index) }
                    }

                    // episode
                    Rectangle {
                        anchors.fill: parent
                        visible: !row.modelData.header
                        color: Qt.alpha(Kirigami.Theme.textColor, episodeHover.hovered ? 0.07 : 0)

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Kirigami.Units.largeSpacing
                            anchors.rightMargin: Kirigami.Units.largeSpacing + Kirigami.Units.gridUnit    // clear of the scrollbar
                            anchors.topMargin: Kirigami.Units.smallSpacing
                            anchors.bottomMargin: Kirigami.Units.smallSpacing
                            spacing: Kirigami.Units.largeSpacing

                            Rectangle {
                                Layout.fillHeight: true
                                Layout.preferredWidth: height * 16 / 9
                                radius: 4
                                color: Qt.alpha(Kirigami.Theme.textColor, 0.08)
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    sourceSize.height: 160
                                    source: row.ep ? ThumbUri.source(row.ep.path) : ""
                                }
                                // how far it was watched
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.bottom: parent.bottom
                                    height: 3
                                    width: row.ep && !row.ep.finished ? parent.width * row.ep.fraction : 0
                                    visible: width > 0
                                    color: Kirigami.Theme.highlightColor
                                }
                                // watched
                                Rectangle {
                                    visible: row.ep !== null && row.ep.finished
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 4
                                    width: Kirigami.Units.iconSizes.small + 4
                                    height: width
                                    radius: width / 2
                                    color: Qt.rgba(0, 0, 0, 0.7)
                                    Kirigami.Icon {
                                        anchors.centerIn: parent
                                        source: "checkmark"
                                        color: "white"
                                        width: Kirigami.Units.iconSizes.small - 2
                                        height: width
                                    }
                                }
                            }
                            Label {
                                text: row.modelData.header ? "" : row.modelData.episode.number
                                opacity: 0.6
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                                horizontalAlignment: Text.AlignRight
                            }
                            Label {
                                Layout.fillWidth: true
                                text: row.ep ? row.ep.title : ""
                                opacity: row.ep && row.ep.finished ? 0.55 : 1
                                elide: Text.ElideRight
                            }
                            Label {
                                text: row.ep ? row.ep.length : ""
                                opacity: 0.6
                                visible: text !== ""
                            }
                        }
                        HoverHandler { id: episodeHover }
                        TapHandler {
                            onTapped: {
                                show.played(row.ep.uri)
                                page.play(row.ep.uri)
                            }
                        }
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: episodeMenu.openFor(row.ep)
                        }
                    }
                }
            }
        }

        // ---- the tag editor ----------------------------------------------------------------------
        TagPanel {
            Layout.fillHeight: true
            Layout.preferredWidth: implicitWidth
            visible: page.tagsOpen
            tagModel: page.tagSource
            folderBackend: page.folderSource
            folderKeys: show.folderUri !== "" ? [show.folderUri] : []
            showTrash: false
        }
    }
}
