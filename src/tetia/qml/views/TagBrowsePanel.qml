// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

// Side panel for browsing by tag: every tag of the items on the page (and only those), with how many items
// have it, drawn like the tag editor draws them (a coloured category title, then chips). Tags that only one
// item has are left out. A click asks the host to show the items with that tag. It is docked and styled like
// the other panels; the host gives it the media model whose items are on the page and a TagModel.
Rectangle {
    id: root

    property var mediaBackend: null
    // the folder tiles of the page: the tags they carry count for the folder
    property var subfolderBackend: null
    property var tagBackend: null

    // Which edge touches the content, so the divider line is drawn on it.
    property bool dockedRight: true

    // The tags already chosen, [{category, name}]: they leave the list above and wait at the bottom with a remove button
    property var selected: []

    // [{category, tags: [{id, name, count}]}], as the TagModel gives them
    property var groups: []
    // Tags shown per category before "N more"
    readonly property int shown: 12
    property var expanded: ({})

    signal closeRequested()
    signal tagChosen(string category, string name)
    // the "-" on a tag: show the items without it (a booru's exclude)
    signal tagExcluded(string category, string name)
    signal tagRemoved(string category, string name)

    implicitWidth: 320
    height: parent ? parent.height : implicitHeight
    color: Kirigami.Theme.alternateBackgroundColor

    property bool wholeFolders: false     // the tags of everything below the page's folders (not only what is shown)

    function refresh() {
        if (!mediaBackend || !tagBackend) {
            groups = []
            return
        }
        // a page of folders: everything below them (a folder tile's files too, not only what is in view)
        var scope = subfolderBackend ? subfolderBackend.browseScope() : ({})
        wholeFolders = scope.ids !== undefined
        if (wholeFolders) groups = tagBackend.browse(scope.ids, scope.series)
        else groups = tagBackend.browse(mediaBackend.visibleIds(), subfolderBackend ? subfolderBackend.folderKeys() : [])
    }

    // The same colours and titles as the tag editor (TagPanel.qml), so a category looks the same in both
    function categoryColor(category) {
        switch (category) {
        case "creator":   return Kirigami.Theme.negativeTextColor
        case "series":    return Kirigami.Theme.visitedLinkColor
        case "character": return Kirigami.Theme.positiveTextColor
        case "genre":     return Kirigami.Theme.neutralTextColor
        default:          return Kirigami.Theme.linkColor
        }
    }

    function categoryTitle(category) {
        if (!category) return "Other"
        return category.charAt(0).toUpperCase() + category.slice(1)
    }

    function isSelected(category, name) {
        for (var i = 0; i < selected.length; i++) {
            if (selected[i].category === category && selected[i].name === name) return true
        }
        return false
    }

    // what is left to choose from: the tags of the page that are not chosen yet
    readonly property var choices: {
        var out = []
        for (var i = 0; i < groups.length; i++) {
            var tags = groups[i].tags.filter(function(t) { return !root.isSelected(groups[i].category, t.name) })
            if (tags.length > 0) out.push({ category: groups[i].category, tags: tags })
        }
        return out
    }

    onVisibleChanged: if (visible) refresh()
    Component.onCompleted: refresh()
    // the items on the page changed (another folder, a move, a Trash)
    Connections {
        target: root.mediaBackend
        function onModelReset() { if (root.visible) root.refresh() }
    }
    Connections {
        target: root.subfolderBackend
        function onModelReset() { if (root.visible) root.refresh() }
    }

    // A tag to click: the editor's chip (a pill tinted with its category's colour) with the number of items
    // after the name, in place of the editor's remove button
    component BrowseChip: Rectangle {
        id: chip
        property string label
        property int count: 0
        property color accent: Kirigami.Theme.highlightColor
        signal clicked()
        signal excluded()

        implicitHeight: Kirigami.Units.gridUnit + Kirigami.Units.largeSpacing
        implicitWidth: chipRow.implicitWidth + Kirigami.Units.largeSpacing * 2
        radius: height / 2
        color: Qt.alpha(accent, area.containsMouse ? 0.3 : 0.16)
        border.width: 1
        border.color: Qt.alpha(accent, 0.65)

        RowLayout {
            id: chipRow
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.largeSpacing
            anchors.rightMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            Label {
                text: chip.label
                color: Kirigami.Theme.textColor
                elide: Text.ElideRight
                Layout.maximumWidth: Kirigami.Units.gridUnit * 11
            }
            Label {
                text: chip.count
                font: Kirigami.Theme.smallFont
                color: Kirigami.Theme.textColor
                opacity: 0.65
            }
            // room for the exclude mark, kept so the chip does not change size on hover
            Item {
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
        }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: chip.clicked()
        }
        Kirigami.Icon {
            id: excludeMark
            anchors.right: parent.right
            anchors.rightMargin: Kirigami.Units.largeSpacing
            anchors.verticalCenter: parent.verticalCenter
            width: Kirigami.Units.iconSizes.small
            height: width
            source: "list-remove"
            opacity: excludeArea.containsMouse ? 1 : (area.containsMouse ? 0.6 : 0.25)
            MouseArea {
                id: excludeArea
                anchors.fill: parent
                anchors.margins: -3
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: chip.excluded()
            }
        }
        ToolTip.visible: area.containsMouse || excludeArea.containsMouse
        ToolTip.delay: 600
        ToolTip.text: excludeArea.containsMouse ? "Leave out the items with this tag" : "Show the items with this tag"
    }

    // A chosen tag: the tag editor's chip, with its remove button
    component SelectedChip: Rectangle {
        id: chosen
        property string label
        property color accent: Kirigami.Theme.highlightColor
        signal removeRequested()

        implicitHeight: Kirigami.Units.gridUnit + Kirigami.Units.largeSpacing
        implicitWidth: chosenRow.implicitWidth + Kirigami.Units.largeSpacing + 2
        radius: height / 2
        color: Qt.alpha(accent, 0.16)
        border.width: 1
        border.color: Qt.alpha(accent, 0.65)

        RowLayout {
            id: chosenRow
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.largeSpacing
            anchors.rightMargin: 3
            spacing: Kirigami.Units.smallSpacing

            Label {
                text: chosen.label
                color: Kirigami.Theme.textColor
                elide: Text.ElideRight
                Layout.maximumWidth: Kirigami.Units.gridUnit * 11
            }
            AbstractButton {
                id: removeButton
                implicitWidth: Kirigami.Units.gridUnit
                implicitHeight: Kirigami.Units.gridUnit
                hoverEnabled: true
                Accessible.name: "Stop showing only " + chosen.label
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Remove this tag from the selection"
                onClicked: chosen.removeRequested()

                background: Rectangle {
                    radius: width / 2
                    color: Qt.alpha(Kirigami.Theme.textColor, removeButton.pressed ? 0.25 : (removeButton.hovered ? 0.14 : 0))
                }
                contentItem: Kirigami.Icon {
                    source: "window-close-symbolic"
                    isMask: true
                    color: Kirigami.Theme.textColor
                }
            }
        }
    }

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

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                source: "tag"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
            Kirigami.Heading {
                level: 3
                text: "Browse tags"
                Layout.fillWidth: true
            }
            ToolButton {
                icon.name: "window-close-symbolic"
                display: AbstractButton.IconOnly
                implicitWidth: Kirigami.Units.gridUnit * 1.8
                implicitHeight: implicitWidth
                Accessible.name: "Close"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Close (T)"
                onClicked: root.closeRequested()
            }
        }

        // The tags, grouped by category (as in the tag editor)
        Flickable {
            id: scroll
            objectName: "tagScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: groupColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            Column {
                id: groupColumn
                width: scroll.width - Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                Repeater {
                    model: root.choices

                    delegate: Column {
                        id: group
                        required property var modelData
                        width: groupColumn.width
                        spacing: Kirigami.Units.smallSpacing
                        readonly property bool open: root.expanded[modelData.category] === true
                        readonly property int hidden: Math.max(0, modelData.tags.length - root.shown)

                        Label {
                            text: root.categoryTitle(group.modelData.category)
                            font.weight: Font.DemiBold
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            color: root.categoryColor(group.modelData.category)
                        }

                        Flow {
                            width: group.width
                            spacing: Kirigami.Units.smallSpacing + 2

                            Repeater {
                                model: group.open ? group.modelData.tags : group.modelData.tags.slice(0, root.shown)
                                delegate: BrowseChip {
                                    required property var modelData
                                    label: modelData.name
                                    count: modelData.count
                                    accent: root.categoryColor(group.modelData.category)
                                    onClicked: root.tagChosen(group.modelData.category, modelData.name)
                                    onExcluded: root.tagExcluded(group.modelData.category, modelData.name)
                                }
                            }
                        }

                        Label {
                            visible: group.hidden > 0
                            text: group.open ? "Show fewer" : group.hidden + " more"
                            font: Kirigami.Theme.smallFont
                            color: Kirigami.Theme.linkColor
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    var next = Object.assign({}, root.expanded)
                                    next[group.modelData.category] = !group.open
                                    root.expanded = next
                                }
                            }
                        }
                    }
                }

                Label {
                    visible: root.choices.length === 0
                    width: groupColumn.width
                    wrapMode: Text.WordWrap
                    color: Kirigami.Theme.textColor
                    opacity: 0.65
                    text: root.selected.length > 0
                          ? "No other tag is shared by two of these items."
                          : "No tag is shared by two items on this page yet. Tags that only one item has are not listed."
                }

                // The chosen tags, straight under the ones still to choose from, behind a separator: each with a
                // remove button, like the chips of the tag editor
                Kirigami.Separator {
                    objectName: "selectedSeparator"
                    width: groupColumn.width
                    visible: root.selected.length > 0
                }
                Flow {
                    id: selectedFlow
                    objectName: "selectedTags"
                    width: groupColumn.width
                    visible: root.selected.length > 0
                    spacing: Kirigami.Units.smallSpacing + 2

                    Repeater {
                        model: root.selected
                        delegate: SelectedChip {
                            required property var modelData
                            label: modelData.name
                            accent: root.categoryColor(modelData.category)
                            onRemoveRequested: root.tagRemoved(modelData.category, modelData.name)
                        }
                    }
                }

            }
        }

        Label {
            Layout.fillWidth: true
            visible: root.groups.length > 0
            wrapMode: Text.WordWrap
            opacity: 0.55
            font: Kirigami.Theme.smallFont
            text: (root.wholeFolders ? "Everything in these folders counts" : "Only the items on this page count")
                  + ". Tags on a single item are hidden."
        }
    }
}
