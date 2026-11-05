// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// The reader's side panel, docked and styled like the tag and metadata panels: how the book is laid out,
// and the chapters of its series. The host gives it the ReaderSession.
Rectangle {
    id: root

    property var session: null
    property int currentPage: 0
    property string tab: "reader"        // "reader" or "chapters"

    signal closeRequested()
    signal chapterChosen(string path)
    signal autoScrollRequested(bool on)
    signal autoLevelRequested(int level)

    property bool autoAvailable: false
    property bool autoScroll: false
    property int autoLevel: 3

    implicitWidth: 320
    height: parent ? parent.height : implicitHeight
    color: Kirigami.Theme.alternateBackgroundColor

    readonly property bool hasChapters: session !== null && session.chapters.length > 0
    readonly property bool paged: session !== null && session.layout === "paged"

    // a row of mutually exclusive choices
    component Choice: RowLayout {
        id: choice
        property var options: []         // [{value, label}]
        property string current: ""
        property bool active: true
        signal picked(string value)
        spacing: 0
        ButtonGroup { id: group }
        Repeater {
            model: choice.options
            delegate: Button {
                focusPolicy: Qt.NoFocus
                required property var modelData
                required property int index
                Layout.fillWidth: true
                text: modelData.label
                checkable: true
                checked: choice.current === modelData.value
                enabled: choice.active
                ButtonGroup.group: group
                onClicked: choice.picked(modelData.value)
            }
        }
    }

    Kirigami.Separator {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                source: "configure"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
            Kirigami.Heading {
                level: 3
                text: "Reader"
                Layout.fillWidth: true
            }
            ToolButton {
                focusPolicy: Qt.NoFocus
                icon.name: "window-close-symbolic"
                display: AbstractButton.IconOnly
                implicitWidth: Kirigami.Units.gridUnit * 1.8
                implicitHeight: implicitWidth
                Accessible.name: "Close"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Close"
                onClicked: root.closeRequested()
            }
        }

        TabBar {
            id: tabs
            Layout.fillWidth: true
            // positions are by order, a hidden Chapters tab keeps its place
            currentIndex: root.tab === "chapters" ? 1 : root.tab === "help" ? 2 : 0
            TabButton { focusPolicy: Qt.NoFocus; text: "Reader"; onClicked: root.tab = "reader" }
            TabButton {
                focusPolicy: Qt.NoFocus
                visible: root.hasChapters
                width: visible ? implicitWidth : 0
                text: "Chapters"
                onClicked: root.tab = "chapters"
            }
            TabButton { focusPolicy: Qt.NoFocus; text: "Help"; onClicked: root.tab = "help" }
        }

        // ---- Reader ----
        ColumnLayout {
            visible: root.tab === "reader"
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Label { text: "Layout"; font.weight: Font.DemiBold }
            Choice {
                Layout.fillWidth: true
                options: [{ value: "paged", label: "Paged" }, { value: "strip", label: "Strip" }]
                current: root.session ? root.session.layout : ""
                onPicked: function(value) { root.session.layout = value }
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.65
                text: "Strip scrolls the pages as one long column, for webtoons."
            }

            Label { text: "Direction"; font.weight: Font.DemiBold; Layout.topMargin: Kirigami.Units.smallSpacing }
            Choice {
                Layout.fillWidth: true
                active: root.paged
                options: [{ value: "rtl", label: "Right to left" }, { value: "ltr", label: "Left to right" }]
                current: root.session ? root.session.direction : ""
                onPicked: function(value) { root.session.direction = value }
            }

            Label { text: "Fit"; font.weight: Font.DemiBold; Layout.topMargin: Kirigami.Units.smallSpacing }
            Choice {
                Layout.fillWidth: true
                active: root.paged
                options: [{ value: "height", label: "Height" }, { value: "width", label: "Width" }, { value: "original", label: "Original" }]
                current: root.session ? root.session.fit : ""
                onPicked: function(value) { root.session.fit = value }
            }

            CheckBox {
                focusPolicy: Qt.NoFocus
                Layout.topMargin: Kirigami.Units.largeSpacing
                text: root.session && root.session.chapters.length > 0 ? "Remember for this series" : "Remember for this book"
                checked: root.session ? root.session.remember : true
                onToggled: root.session.remember = checked
            }

            // Auto-scroll (strip)
            Label { text: "Auto-scroll"; font.weight: Font.DemiBold; Layout.topMargin: Kirigami.Units.largeSpacing }
            Button {
                Layout.fillWidth: true
                focusPolicy: Qt.NoFocus
                enabled: root.autoAvailable
                icon.name: root.autoScroll ? "media-playback-pause" : "media-playback-start"
                text: root.autoScroll ? "Stop (A)" : "Start (A)"
                onClicked: root.autoScrollRequested(!root.autoScroll)
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Slow"; font: Kirigami.Theme.smallFont; opacity: 0.7 }
                Slider {
                    Layout.fillWidth: true
                    focusPolicy: Qt.NoFocus
                    from: 1
                    to: 10
                    stepSize: 1
                    snapMode: Slider.SnapAlways
                    value: root.autoLevel
                    enabled: root.autoAvailable
                    onMoved: root.autoLevelRequested(Math.round(value))
                }
                Label { text: "Fast"; font: Kirigami.Theme.smallFont; opacity: 0.7 }
            }
            Label {
                visible: !root.autoAvailable
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                opacity: 0.65
                text: "Auto-scroll is for the strip layout."
            }
            Item { Layout.fillHeight: true }
        }

        // ---- Chapters ----
        ListView {
            id: chapterList
            visible: root.tab === "chapters"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.session ? root.session.chapters : []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            onVisibleChanged: if (visible) positionAtCurrent()
            onCountChanged: positionAtCurrent()
            function positionAtCurrent() {
                for (var i = 0; i < count; i++) {
                    if (model[i].isCurrent) { positionViewAtIndex(i, ListView.Center); return }
                }
            }
            delegate: ItemDelegate {
                focusPolicy: Qt.NoFocus
                id: chapterRow
                required property var modelData
                width: chapterList.width - Kirigami.Units.largeSpacing
                highlighted: modelData.isCurrent
                onClicked: if (!modelData.isCurrent) root.chapterChosen(modelData.path)
                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing
                    Label {
                        Layout.preferredWidth: Kirigami.Units.gridUnit
                        horizontalAlignment: Text.AlignHCenter
                        text: chapterRow.modelData.state === "read" ? "✓"
                              : chapterRow.modelData.state === "current" ? "▸"
                              : chapterRow.modelData.state === "reading" ? "•" : ""
                        color: chapterRow.modelData.state === "read" ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.textColor
                    }
                    Label {
                        Layout.fillWidth: true
                        text: chapterRow.modelData.name
                        elide: Text.ElideMiddle
                        opacity: chapterRow.modelData.state === "read" ? 0.65 : 1
                    }
                    Label {
                        visible: chapterRow.modelData.total > 0 && chapterRow.modelData.state !== "read"
                        text: "page " + (chapterRow.modelData.page + 1) + " of " + chapterRow.modelData.total
                        font: Kirigami.Theme.smallFont
                        opacity: 0.65
                    }
                }
            }
        }


        // ---- Help ----
        ScrollView {
            id: help
            visible: root.tab === "help"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            component Topic: Label {
                Layout.fillWidth: true
                font.weight: Font.DemiBold
                Layout.topMargin: Kirigami.Units.smallSpacing
            }
            component Line: Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                textFormat: Text.StyledText
                font: Kirigami.Theme.smallFont
            }

            ColumnLayout {
                width: help.availableWidth
                spacing: Kirigami.Units.smallSpacing

                Topic { text: "Turning pages" }
                Line { text: "Click the <b>left</b> or <b>right third</b> of the page. In a right-to-left book the sides swap. The <b>middle</b> shows or hides the controls." }
                Line { text: "<b>\u2190 \u2192</b> arrows, <b>Space</b> / <b>PageDown</b> forward, <b>Shift+Space</b> / <b>PageUp</b> back, <b>Home</b> / <b>End</b> first and last page." }
                Line { text: "<b>Mouse wheel</b> turns pages (a page bigger than the window scrolls first). In the strip it scrolls." }

                Topic { text: "Zoom" }
                Line { text: "<b>Double-click</b> to zoom in and again to zoom out. <b>Ctrl + scroll</b> zooms around the pointer, <b>Ctrl+0</b> goes back to the default, <b>Ctrl +</b> and <b>Ctrl \u2212</b> step." }
                Line { text: "<b>Drag</b> to pan. While zoomed, clicking the sides does not turn the page." }

                Topic { text: "Auto-scroll" }
                Line { text: "In the strip, <b>A</b> (or the Reader tab) starts the strip scrolling by itself, with a speed slider. Any click, key or wheel stops it, and it stops at the end of the chapter." }

                Topic { text: "Chapters" }
                Line { text: "A <b>card after the last page</b> offers the next chapter. A <b>card before the first page</b> offers the previous one: in the strip, scroll up past the top; in paged mode, go back from page 1." }
                Line { text: "<b>]</b> opens the next chapter and <b>[</b> the previous one. A chapter you finished starts from page 1 again; one you stopped in the middle opens where you left off." }

                Topic { text: "Everything else" }
                Line { text: "<b>F11</b> fullscreen, <b>I</b> details, <b>F1</b> this help, <b>Esc</b> closes the panel, leaves fullscreen, then leaves the book." }
            }
        }
    }
}
