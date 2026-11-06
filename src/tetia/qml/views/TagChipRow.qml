// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// One row of tag chips for a single item, as many as fit in `available` pixels, then a "+N" chip that opens a
// popup with all of them grouped by category. Used in the image viewer's header. The tags come ordered
// (creator, series, character, genre, content), so the first chips are the most telling.
Item {
    id: root

    // [{id, name, category}]
    property var tags: []
    // the width the row may use
    property real available: 0

    signal tagClicked(string category, string name)

    readonly property int gap: Kirigami.Units.smallSpacing
    readonly property int chipPadding: Kirigami.Units.largeSpacing
    readonly property real chipHeight: Kirigami.Units.gridUnit + Kirigami.Units.smallSpacing * 2

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
    function categoryTitle(category) {
        return category ? category.charAt(0).toUpperCase() + category.slice(1) : "Other"
    }

    // The width of each chip, measured by hidden labels that hold the same text (reading a TextMetrics that the
    // calculation itself sets would loop). `measured` ticks whenever they are rebuilt.
    property int measured: 0
    Repeater {
        id: meter
        model: root.tags
        delegate: Label {
            required property var modelData
            visible: false
            text: modelData.name
            font: Kirigami.Theme.smallFont
        }
        onItemAdded: root.measured++
        onItemRemoved: root.measured++
    }
    // the widest "+N" chip there can be
    Label {
        id: plusMeter
        visible: false
        text: "+" + root.tags.length
        font: Kirigami.Theme.smallFont
    }
    function chipWidthAt(i) {
        var item = meter.itemAt(i)
        return (item ? Math.ceil(item.implicitWidth) : 0) + 2 * chipPadding
    }

    // how many chips fit, leaving room for the "+N" chip when some do not
    readonly property int shown: {
        var ticked = measured          // look again when the measuring labels change
        var count = tags.length
        var used = 0
        var n = 0
        var plus = Math.ceil(plusMeter.implicitWidth) + 2 * chipPadding + gap
        for (var i = 0; i < count; i++) {
            var extra = (n > 0 ? gap : 0) + chipWidthAt(i)
            var needPlus = i < count - 1 ? plus : 0
            if (used + extra + needPlus > available) break
            used += extra
            n++
        }
        return n
    }
    readonly property int hiddenCount: tags.length - shown

    implicitHeight: chipHeight
    implicitWidth: row.implicitWidth

    // a chip: the tag editor's pill, in a smaller size
    component Chip: Rectangle {
        id: chip
        property string label
        property color accent: Kirigami.Theme.highlightColor
        property string hint: ""
        signal clicked()

        implicitHeight: root.chipHeight
        implicitWidth: chipText.implicitWidth + 2 * root.chipPadding
        radius: height / 2
        color: Qt.alpha(accent, area.containsMouse ? 0.3 : 0.16)
        border.width: 1
        border.color: Qt.alpha(accent, 0.65)

        Label {
            id: chipText
            anchors.centerIn: parent
            text: chip.label
            font: Kirigami.Theme.smallFont
            color: Kirigami.Theme.textColor
        }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: chip.clicked()
        }
        ToolTip.visible: area.containsMouse && chip.hint !== ""
        ToolTip.delay: 500
        ToolTip.text: chip.hint
    }

    Row {
        id: row
        spacing: root.gap

        Repeater {
            model: root.tags.slice(0, root.shown)
            delegate: Chip {
                required property var modelData
                label: modelData.name
                accent: root.categoryColor(modelData.category)
                hint: root.categoryTitle(modelData.category) + ": show the items with this tag"
                onClicked: root.tagClicked(modelData.category, modelData.name)
            }
        }

        Chip {
            id: more
            visible: root.hiddenCount > 0
            label: root.shown === 0 ? root.hiddenCount + (root.hiddenCount === 1 ? " tag" : " tags") : "+" + root.hiddenCount
            hint: "All the tags of this item"
            onClicked: allTags.opened ? allTags.close() : allTags.open()
        }
    }

    // every tag of the item, grouped by category
    Popup {
        id: allTags
        y: root.chipHeight + Kirigami.Units.smallSpacing
        x: 0
        width: Kirigami.Units.gridUnit * 22
        padding: Kirigami.Units.largeSpacing
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        contentItem: Column {
            spacing: Kirigami.Units.largeSpacing

            Repeater {
                model: {
                    var groups = []
                    for (var i = 0; i < root.tags.length; i++) {
                        var t = root.tags[i]
                        if (groups.length === 0 || groups[groups.length - 1].category !== t.category) {
                            groups.push({ category: t.category, tags: [] })
                        }
                        groups[groups.length - 1].tags.push(t)
                    }
                    return groups
                }
                delegate: Column {
                    id: group
                    required property var modelData
                    width: parent.width
                    spacing: Kirigami.Units.smallSpacing

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
                            model: group.modelData.tags
                            delegate: Chip {
                                required property var modelData
                                label: modelData.name
                                accent: root.categoryColor(group.modelData.category)
                                onClicked: {
                                    allTags.close()
                                    root.tagClicked(group.modelData.category, modelData.name)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
