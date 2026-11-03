// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// The search strip under the header: a text field with tag/term suggestions and
// the committed terms as removable chips. It only collects the query; main.qml
// decides what to search and shows the results.
ToolBar {
    id: bar

    // The SearchModel (suggestions)
    property var backend: null
    // Where the search will run, e.g. "all collections" or a folder's name
    property string scopeText: "all collections"
    property bool indexing: false

    // Committed terms, e.g. ["series:starfall", "-chibi"]
    property var chips: []
    property var suggestions: []
    property int current: -1

    // Nothing typed and no terms: back/Esc may close the whole strip
    readonly property bool isEmpty: chips.length === 0 && field.text === ""

    // Emitted with the whole query (chips joined) whenever the terms change
    signal searchRequested(string query)
    signal closeRequested()

    function focusField() {
        field.forceActiveFocus()
        field.selectAll()
    }

    function clearAll() {
        chips = []
        field.text = ""
        suggestions = []
        current = -1
    }

    function commitText() {
        var tokens = backend ? backend.splitTokens(field.text) : []
        if (tokens.length > 0) {
            chips = chips.concat(tokens)
            field.text = ""
        }
        if (chips.length > 0) searchRequested(chips.join(" "))
    }

    function removeChip(i) {
        var next = chips.slice()
        next.splice(i, 1)
        chips = next
        searchRequested(chips.join(" "))
    }

    function accept(suggestion) {
        var words = field.text.split(" ")
        words[words.length - 1] = suggestion.insert
        field.text = words.join(" ")
        // "type:" still wants its value, anything else is a finished term
        if (!suggestion.insert.endsWith(":")) commitText()
        field.forceActiveFocus()
    }

    function refreshSuggestions() {
        var token = field.text.endsWith(" ") ? "" : field.text.split(" ").pop()
        suggestions = (backend && token.length > 0) ? backend.suggest(token) : []
        current = -1
    }

    // ---- Help ------------------------------------------------------------

    readonly property var helpItems: [
        { title: "Searching",
          body: "Type a tag or part of a file name and press Enter. Each term becomes a chip below the box; remove it with its \u00D7, or press Backspace in the empty box. An item must match every term. Example: <b>starfall mira</b>." },
        { title: "Where it looks",
          body: "From the top level it searches every collection, in every category. Inside a folder it searches that folder and its subfolders. The line under the box says which." },
        { title: "Categories",
          body: "Limit a term to one tag category: creator, series, character, genre or content. Example: <b>series:starfall character:mira</b>." },
        { title: "File type",
          body: "<b>type:</b> takes photo, video, manga or ebook. Example: <b>series:starfall type:photo</b>." },
        { title: "Leaving something out",
          body: "Put a minus in front. Example: <b>series:starfall -chibi</b> finds items from Starfall that are not tagged chibi." },
        { title: "Either / or",
          body: "Put a tilde in front of two or more terms to match any of them. Example: <b>~mira ~orin</b>." },
        { title: "Wildcards",
          body: "A star stands for any letters in a tag. Example: <b>star*</b> finds starfall." },
        { title: "File names",
          body: "A word that isn't a tag is matched against file names. For a phrase, use quotes, like <b>\"episode 1\"</b>, or <b>name:</b> to be explicit." },
        { title: "Favorites",
          body: "<b>is:favorite</b> shows only your favorites. Example: <b>series:starfall is:favorite</b>." },
        { title: "Rating",
          body: "Levels are general, suggestive, mature and explicit; unrated means you haven't rated it yet. Example: <b>rating:general</b>. Use &gt;= or &lt; to compare, like <b>rating:&lt;=suggestive</b>. A minus works too: <b>-rating:explicit</b> keeps unrated items." },
        { title: "Suggestions",
          body: "Matching tags and prefixes pop up as you type. Click one, or use the arrow keys and Enter (Tab takes the first)." }
    ]

    Popup {
        id: helpPopup
        parent: bar
        x: Math.max(Kirigami.Units.largeSpacing, bar.width - width - Kirigami.Units.largeSpacing)
        y: bar.height
        width: Math.min(bar.width - Kirigami.Units.largeSpacing * 2, Kirigami.Units.gridUnit * 28)
        padding: Kirigami.Units.largeSpacing
        modal: true          // a click outside just closes it
        dim: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: Kirigami.Theme.backgroundColor
            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.3)
            radius: 6
        }

        contentItem: ScrollView {
            id: helpScroll
            implicitHeight: Math.min(helpColumn.implicitHeight, Kirigami.Units.gridUnit * 22)
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                id: helpColumn
                width: helpScroll.availableWidth
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Heading {
                    level: 3
                    text: "How search works"
                    Layout.fillWidth: true
                }

                Repeater {
                    model: bar.helpItems

                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 2

                        Label {
                            text: parent.modelData.title
                            font.weight: Font.DemiBold
                            color: Kirigami.Theme.textColor
                        }
                        Label {
                            text: parent.modelData.body
                            textFormat: Text.StyledText
                            wrapMode: Text.WordWrap
                            color: Kirigami.Theme.textColor
                            opacity: 0.85
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Kirigami.Icon {
                source: "system-search"
                Layout.preferredWidth: 20
                Layout.preferredHeight: 20
            }

            TextField {
                id: field
                Layout.fillWidth: true
                placeholderText: "Search tags and file names"
                selectByMouse: true

                onTextChanged: bar.refreshSuggestions()

                Keys.onDownPressed: if (bar.suggestions.length > 0)
                    bar.current = Math.min(bar.current + 1, bar.suggestions.length - 1)
                Keys.onUpPressed: if (bar.suggestions.length > 0)
                    bar.current = Math.max(bar.current - 1, -1)
                Keys.onTabPressed: if (bar.suggestions.length > 0)
                    bar.accept(bar.suggestions[Math.max(bar.current, 0)])
                Keys.onReturnPressed: {
                    if (bar.current >= 0) bar.accept(bar.suggestions[bar.current])
                    else bar.commitText()
                }
                Keys.onEnterPressed: Keys.returnPressed(event)
                Keys.onEscapePressed: {
                    if (bar.suggestions.length > 0) bar.suggestions = []
                    else bar.closeRequested()
                }
                Keys.onPressed: function(event) {
                    // Backspace in an empty field takes back the last term
                    if (event.key === Qt.Key_Backspace && text === "" && bar.chips.length > 0) {
                        bar.removeChip(bar.chips.length - 1)
                        event.accepted = true
                    }
                }

                Popup {
                    y: field.height + 2
                    width: field.width
                    padding: 0
                    focus: false
                    closePolicy: Popup.NoAutoClose
                    visible: bar.suggestions.length > 0 && field.activeFocus

                    contentItem: ListView {
                        implicitHeight: contentHeight
                        model: bar.suggestions
                        clip: true

                        delegate: ItemDelegate {
                            width: ListView.view.width
                            highlighted: index === bar.current
                            text: modelData.label
                            onClicked: bar.accept(modelData)

                            contentItem: RowLayout {
                                Label {
                                    text: modelData.label
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                                Label {
                                    text: modelData.category === "meta" ? "" : modelData.category
                                    opacity: 0.6
                                    font.pixelSize: 11
                                }
                            }
                        }
                    }
                }
            }

            ToolButton {
                icon.name: "help-about-symbolic"
                display: AbstractButton.IconOnly
                hoverEnabled: true
                Accessible.name: "How search works"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "How search works"
                onClicked: helpPopup.open()
            }

            ToolButton {
                icon.name: "window-close"
                display: AbstractButton.IconOnly
                onClicked: bar.closeRequested()
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 6
            visible: bar.chips.length > 0

            Repeater {
                model: bar.chips

                Rectangle {
                    readonly property bool negative: modelData.charAt(0) === "-"
                    height: chipLabel.implicitHeight + 8
                    width: chipLabel.implicitWidth + closeText.implicitWidth + 22
                    radius: height / 2
                    color: negative ? Qt.alpha(Kirigami.Theme.negativeTextColor, 0.2)
                                    : Qt.alpha(Kirigami.Theme.highlightColor, 0.22)

                    Label {
                        id: chipLabel
                        x: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                    }
                    Label {
                        id: closeText
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: "×"
                        opacity: chipClose.containsMouse ? 1.0 : 0.6
                    }
                    MouseArea {
                        id: chipClose
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: closeText.implicitWidth + 16
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bar.removeChip(index)
                    }
                }
            }
        }

        Label {
            text: "Searching " + bar.scopeText + (bar.indexing ? "  ·  indexing your library… results may be incomplete" : "")
            opacity: 0.6
            font.pixelSize: 11
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
    }
}
