import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

// Side panel for tagging, rating and favoriting one or many media items.
//
// Host contract (unchanged): set mediaIds (or currentMediaId), tagModel and
// mediaModel. The host sizes the panel (Layout / anchors); by default it is
// 320 px wide and as tall as its parent. Listen to deleteRequested().
Rectangle {
    id: root

    // ---- Public API ------------------------------------------------------
    property var mediaIds: []
    property var tagModel: null
    property var mediaModel: null
    property int currentMediaId: -1

    // Tag categories offered in the picker, in display order. Must match the
    // names seeded in tag_category.
    property var categoryList: ["creator", "series", "character", "genre", "content"]
    property string defaultCategory: "content"

    // Hosts that don't implement deletion can hide the button.
    property bool showDelete: true

    // Which edge touches the content, so the divider line is drawn on it.
    property bool dockedRight: true

    signal deleteRequested()

    // Focus the tag input (e.g. when the host opens the panel from a shortcut).
    function focusInput() {
        inputField.forceActiveFocus()
    }

    // Re-read everything from the models (call after changing data elsewhere).
    function refresh() {
        _loadTags()
        _loadRating()
        _loadFavorite()
    }

    // Kept for hosts that used the old helpers.
    function getSelectedCount() { return root.targetCount }
    function isSingleItem() { return root.isSingle }
    function getFirstMediaId() { return root.targetCount > 0 ? root.targetIds[0] : -1 }

    // ---- Derived state ---------------------------------------------------

    // The items being edited. A multi-selection wins; otherwise currentMediaId
    // (the image viewer follows the visible image with it) overrides mediaIds.
    readonly property var targetIds: {
        var ids = root.mediaIds ? root.mediaIds : []
        if (ids.length > 1) return ids
        if (root.currentMediaId >= 0) return [root.currentMediaId]
        return ids
    }
    readonly property int targetCount: targetIds.length
    readonly property bool isSingle: targetCount === 1

    property var _groups: []          // [{category, tags: [{tagId, name, count}]}]
    property var _tagCounts: ({})     // tagId -> how many selected items carry it
    property int _tagTotal: 0
    property int _rating: -1          // -1 unrated, 0..3, -2 items disagree
    property int _favState: 0         // 0 none, 1 some, 2 all
    property var _suggestionData: []
    property string _error: ""

    readonly property var _ratingDefs: [
        { value: 0, label: "General" },
        { value: 1, label: "SFW" },
        { value: 2, label: "Explicit" },
        { value: 3, label: "NSFW" }
    ]

    implicitWidth: 320
    height: parent ? parent.height : implicitHeight
    color: Kirigami.Theme.alternateBackgroundColor

    onTargetIdsChanged: refresh()
    onTagModelChanged: refresh()
    onMediaModelChanged: refresh()
    Component.onCompleted: refresh()

    // ---- Presentation helpers -------------------------------------------

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

    function ratingColor(value) {
        switch (value) {
        case 0:  return Kirigami.Theme.positiveTextColor
        case 1:  return Kirigami.Theme.linkColor
        case 2:  return Kirigami.Theme.neutralTextColor
        default: return Kirigami.Theme.negativeTextColor
        }
    }

    // ---- Loading ---------------------------------------------------------

    function _loadTags() {
        var ids = root.targetIds
        var byId = {}
        if (root.tagModel) {
            for (var i = 0; i < ids.length; i++) {
                var list = root.tagModel.tagsFor(ids[i]) || []
                for (var j = 0; j < list.length; j++) {
                    var t = list[j]
                    if (!byId[t.id]) {
                        byId[t.id] = { tagId: t.id, name: t.name, category: t.category || "", count: 0 }
                    }
                    byId[t.id].count++
                }
            }
        }

        var counts = {}
        var perCategory = {}
        var total = 0
        for (var key in byId) {
            var entry = byId[key]
            counts[entry.tagId] = entry.count
            var cat = root.categoryList.indexOf(entry.category) >= 0 ? entry.category : ""
            if (!perCategory[cat]) perCategory[cat] = []
            perCategory[cat].push(entry)
            total++
        }

        var order = root.categoryList.concat([""])
        var groups = []
        for (var c = 0; c < order.length; c++) {
            var tags = perCategory[order[c]]
            if (!tags) continue
            tags.sort(function(a, b) {
                // Tags on every selected item first, then alphabetical
                if (a.count !== b.count) return b.count - a.count
                return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0)
            })
            groups.push({ category: order[c], tags: tags })
        }

        root._tagCounts = counts
        root._groups = groups
        root._tagTotal = total
    }

    function _readRating(id) {
        var r = root.mediaModel ? root.mediaModel.getRating(id) : -1
        if (r === undefined || r === null || isNaN(r) || r < 0 || r > 3) return -1
        return r
    }

    function _loadRating() {
        var ids = root.targetIds
        if (ids.length === 0 || !root.mediaModel) {
            root._rating = -1
            return
        }
        var first = _readRating(ids[0])
        for (var i = 1; i < ids.length; i++) {
            if (_readRating(ids[i]) !== first) {
                root._rating = -2
                return
            }
        }
        root._rating = first
    }

    function _loadFavorite() {
        var ids = root.targetIds
        if (ids.length === 0 || !root.mediaModel) {
            root._favState = 0
            return
        }
        var n = 0
        for (var i = 0; i < ids.length; i++) {
            if (root.mediaModel.getFavorite(ids[i])) n++
        }
        root._favState = n === 0 ? 0 : (n === ids.length ? 2 : 1)
    }

    // ---- Actions ---------------------------------------------------------

    // Clicking the active rating clears it (Unrated).
    function _setRating(value) {
        if (!root.mediaModel) return
        var newValue = (root._rating === value) ? -1 : value
        for (var i = 0; i < root.targetIds.length; i++) {
            root.mediaModel.setRating(root.targetIds[i], newValue)
        }
        _loadRating()   // re-read so the UI always shows what was really stored
    }

    function _toggleFavorite() {
        if (!root.mediaModel) return
        var makeFavorite = root._favState !== 2
        for (var i = 0; i < root.targetIds.length; i++) {
            root.mediaModel.setFavorite(root.targetIds[i], makeFavorite)
        }
        _loadFavorite()
    }

    function _removeTag(tagId) {
        if (!root.tagModel) return
        if (root.targetCount > 1) {
            root.tagModel.removeTagsFromMedia(root.targetIds, tagId)
        } else if (root.targetCount === 1) {
            root.tagModel.removeTag(root.targetIds[0], tagId)
        }
        _loadTags()
    }

    // Mirrors normalize_tag() in tagModel.py. Returns an error message or "".
    function _validate(name) {
        if (name.length === 0) return "Type a tag name first."
        if (/[,:*~]/.test(name)) return "Tags can't contain , : * or ~"
        if (name.charAt(0) === "-") return "Tags can't start with -"
        return ""
    }

    // "creator: Foo Bar, sci fi" -> [{name:"foo bar", category:"creator"}, {name:"sci fi", category:""}]
    function _parseEntries(text) {
        var entries = []
        var parts = text.split(",")
        var prefixRe = new RegExp("^(" + root.categoryList.join("|") + ")\\s*:\\s*(.*)$", "i")
        for (var i = 0; i < parts.length; i++) {
            var part = parts[i].trim()
            if (part.length === 0) continue
            var category = ""
            var m = part.match(prefixRe)
            if (m) {
                category = m[1].toLowerCase()
                part = m[2].trim()
            }
            entries.push({ name: part.toLowerCase().replace(/\s+/g, "_"), category: category })
        }
        return entries
    }

    // An existing tag keeps its category; only brand-new tags use the picker.
    function _categoryFor(name) {
        var found = root.tagModel ? (root.tagModel.suggest(name) || []) : []
        for (var i = 0; i < found.length; i++) {
            if (found[i].name === name) return found[i].category
        }
        return categoryBox.currentValue
    }

    function _commit(entries) {
        if (!root.tagModel || root.targetCount === 0) return
        if (entries.length === 0) {
            root._error = _validate("")
            return
        }
        // Validate everything first so a typo doesn't leave half the tags added.
        for (var i = 0; i < entries.length; i++) {
            var err = _validate(entries[i].name)
            if (err) {
                root._error = err
                return
            }
        }

        var failed = []
        for (var j = 0; j < entries.length; j++) {
            var e = entries[j]
            var category = e.category !== "" ? e.category : _categoryFor(e.name)
            var ok = root.isSingle
                ? root.tagModel.addTag(root.targetIds[0], e.name, category)
                : root.tagModel.addTagsToMedia(root.targetIds, e.name, category)
            if (ok === false) failed.push(e.name)
        }

        inputField.text = ""          // clears suggestions and any old error
        if (failed.length > 0) {
            root._error = "Couldn't add: " + failed.join(", ")
        }
        _loadTags()
    }

    function _acceptSuggestion(index) {
        var s = root._suggestionData[index]
        if (!s) return
        var head = inputField.text.substring(0, inputField.text.lastIndexOf(","))
        var entries = _parseEntries(head)
        entries.push({ name: s.name, category: s.category })
        _commit(entries)
    }

    function _updateSuggestions() {
        // Only the fragment after the last comma is being typed.
        var text = inputField.text
        var fragment = text.substring(text.lastIndexOf(",") + 1).trim().toLowerCase()
        var prefixRe = new RegExp("^(" + root.categoryList.join("|") + ")\\s*:\\s*", "i")
        fragment = fragment.replace(prefixRe, "")

        var shown = []
        if (root.tagModel && fragment.length > 0 && root.targetCount > 0) {
            var found = root.tagModel.suggest(fragment) || []
            for (var i = 0; i < found.length && shown.length < 8; i++) {
                // Skip tags every selected item already has
                if (root._tagCounts[found[i].id] === root.targetCount) continue
                shown.push(found[i])
            }
        }
        root._suggestionData = shown
        suggestionList.currentIndex = -1
        if (shown.length > 0 && inputField.activeFocus) suggestionPopup.open()
        else suggestionPopup.close()
    }

    // ---- Inline components -----------------------------------------------

    component TagChip: Rectangle {
        id: chip
        property string label
        property color accent: Kirigami.Theme.highlightColor
        property int count: 1
        property int total: 1
        readonly property bool partial: total > 1 && count < total
        signal removeRequested()

        implicitHeight: Kirigami.Units.gridUnit + Kirigami.Units.largeSpacing
        implicitWidth: chipRow.implicitWidth + Kirigami.Units.largeSpacing + 2
        radius: height / 2
        color: Qt.alpha(accent, partial ? 0.06 : 0.16)
        border.width: 1
        border.color: Qt.alpha(accent, partial ? 0.35 : 0.65)

        RowLayout {
            id: chipRow
            anchors.fill: parent
            anchors.leftMargin: Kirigami.Units.largeSpacing
            anchors.rightMargin: 3
            spacing: Kirigami.Units.smallSpacing

            Label {
                text: chip.label
                color: Kirigami.Theme.textColor
                elide: Text.ElideRight
                Layout.maximumWidth: Kirigami.Units.gridUnit * 11
            }

            // "2/5": only some of the selected items carry this tag
            Label {
                visible: chip.partial
                text: chip.count + "/" + chip.total
                font: Kirigami.Theme.smallFont
                color: Kirigami.Theme.textColor
                opacity: 0.65
            }

            AbstractButton {
                id: closeButton
                implicitWidth: Kirigami.Units.gridUnit
                implicitHeight: Kirigami.Units.gridUnit
                hoverEnabled: true
                Accessible.name: "Remove tag " + chip.label
                onClicked: chip.removeRequested()

                background: Rectangle {
                    radius: width / 2
                    color: Qt.alpha(Kirigami.Theme.textColor, closeButton.pressed ? 0.25 : (closeButton.hovered ? 0.14 : 0))
                }
                contentItem: Kirigami.Icon {
                    source: "window-close-symbolic"
                    isMask: true
                    color: Kirigami.Theme.textColor
                }
            }
        }
    }

    component RatingSegment: AbstractButton {
        id: seg
        property color accent: Kirigami.Theme.highlightColor
        property bool active: false

        Layout.fillWidth: true
        Layout.preferredWidth: 1          // equal widths whatever the label
        implicitHeight: Kirigami.Units.gridUnit * 2
        hoverEnabled: true

        background: Rectangle {
            radius: 4
            color: seg.active ? Qt.alpha(seg.accent, 0.22)
                              : Qt.alpha(Kirigami.Theme.textColor, seg.hovered ? 0.08 : 0)
            border.width: seg.active || seg.visualFocus ? 2 : 1
            border.color: seg.active ? seg.accent
                         : (seg.visualFocus ? Kirigami.Theme.highlightColor
                                            : Qt.alpha(Kirigami.Theme.textColor, 0.25))
        }
        contentItem: Label {
            text: seg.text
            color: Kirigami.Theme.textColor
            font.weight: seg.active ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    // Fully custom (AbstractButton, not Button) so the desktop style can't
    // paint its own icon/label underneath ours.
    component DangerButton: AbstractButton {
        id: danger
        hoverEnabled: true
        implicitHeight: Kirigami.Units.gridUnit * 2

        background: Rectangle {
            radius: 4
            color: Qt.alpha(Kirigami.Theme.negativeTextColor, danger.pressed ? 0.25 : (danger.hovered ? 0.14 : 0))
            border.width: danger.visualFocus ? 2 : 1
            border.color: danger.visualFocus ? Kirigami.Theme.highlightColor
                                             : Qt.alpha(Kirigami.Theme.negativeTextColor, 0.6)
        }
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Item { Layout.fillWidth: true }
            Kirigami.Icon {
                source: danger.icon.name
                isMask: true
                color: Kirigami.Theme.negativeTextColor
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
            Label {
                text: danger.text
                color: Kirigami.Theme.negativeTextColor
            }
            Item { Layout.fillWidth: true }
        }
    }

    // ---- Help ------------------------------------------------------------

    readonly property var _helpItems: [
        { title: "Adding a tag",
          body: "Type a name in the box at the bottom and press Enter. Add several at once with commas, like <i>blue hair, sci fi</i>. Spaces become underscores." },
        { title: "Categories",
          body: "Every tag has a category: Creator, Series, Character, Genre or Content. New tags use the category in the dropdown, or type it first: <i>creator: some name</i>. A tag that already exists keeps its own category." },
        { title: "Suggestions",
          body: "Matching tags pop up as you type. Click one, or use the arrow keys and Enter." },
        { title: "Several items selected",
          body: "The panel lists every tag found on any selected item. Faded tags with a count like 2/5 are on only some of them. Adding a tag adds it to all selected items. The x removes it from all of them." },
        { title: "Rating",
          body: "General, SFW, Explicit or NSFW. Click the active one again to clear it. Rating is separate from tags." },
        { title: "Favorite and Delete",
          body: "Favorite adds the item to your Favorites tab. Delete moves the file to the system trash." }
    ]

    Popup {
        id: helpPopup
        parent: root
        x: Kirigami.Units.largeSpacing
        y: Kirigami.Units.gridUnit * 3
        width: root.width - Kirigami.Units.largeSpacing * 2
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
            implicitHeight: Math.min(helpColumn.implicitHeight, root.height - Kirigami.Units.gridUnit * 7)
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                id: helpColumn
                width: helpScroll.availableWidth
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Heading {
                    level: 3
                    text: "How tags work"
                    Layout.fillWidth: true
                }

                Repeater {
                    model: root._helpItems

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

    // ---- Layout ----------------------------------------------------------

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

        // Header
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
                text: root.targetCount > 1 ? root.targetCount + " items selected" : "Tags"
                Layout.fillWidth: true
                elide: Text.ElideRight
            }

            Label {
                visible: root.targetCount > 0
                text: root._tagTotal + (root._tagTotal === 1 ? " tag" : " tags")
                font: Kirigami.Theme.smallFont
                color: Kirigami.Theme.textColor
                opacity: 0.65
            }

            ToolButton {
                id: helpButton
                icon.name: "help-about-symbolic"
                display: AbstractButton.IconOnly
                implicitWidth: Kirigami.Units.gridUnit * 1.8
                implicitHeight: implicitWidth
                hoverEnabled: true
                Accessible.name: "How tags work"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "How tags work"
                onClicked: helpPopup.open()
            }
        }

        Label {
            visible: root.targetCount > 1
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            color: Kirigami.Theme.textColor
            opacity: 0.65
            text: "Showing tags on any selected item. Faded tags are on only some of them."
        }

        // Tag list, grouped by category
        Flickable {
            id: tagScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: groupColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            Column {
                id: groupColumn
                width: tagScroll.width - Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                Repeater {
                    model: root._groups

                    delegate: Column {
                        id: groupDelegate
                        required property var modelData
                        width: groupColumn.width
                        spacing: Kirigami.Units.smallSpacing

                        Label {
                            text: root.categoryTitle(groupDelegate.modelData.category)
                            font.weight: Font.DemiBold
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            color: root.categoryColor(groupDelegate.modelData.category)
                        }

                        Flow {
                            width: groupDelegate.width
                            spacing: Kirigami.Units.smallSpacing + 2

                            Repeater {
                                model: groupDelegate.modelData.tags

                                delegate: TagChip {
                                    required property var modelData
                                    label: modelData.name
                                    count: modelData.count
                                    total: root.targetCount
                                    accent: root.categoryColor(groupDelegate.modelData.category)
                                    onRemoveRequested: root._removeTag(modelData.tagId)
                                }
                            }
                        }
                    }
                }

                Label {
                    visible: root._tagTotal === 0
                    width: groupColumn.width
                    wrapMode: Text.WordWrap
                    color: Kirigami.Theme.textColor
                    opacity: 0.65
                    text: root.targetCount === 0
                        ? "Select one or more items to edit their tags."
                        : "No tags yet. Add one below."
                }
            }
        }

        // Add-tag input: [category] [text field]
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            enabled: root.targetCount > 0

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                ComboBox {
                    id: categoryBox
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                    textRole: "text"
                    valueRole: "key"
                    model: {
                        var items = []
                        for (var i = 0; i < root.categoryList.length; i++) {
                            items.push({ key: root.categoryList[i], text: root.categoryTitle(root.categoryList[i]) })
                        }
                        return items
                    }
                    currentIndex: Math.max(0, root.categoryList.indexOf(root.defaultCategory))
                    Accessible.name: "Category for new tags"
                }

                TextField {
                    id: inputField
                    Layout.fillWidth: true
                    placeholderText: "Add tag…"
                    placeholderTextColor: Qt.alpha(Kirigami.Theme.textColor, 0.6)
                    color: Kirigami.Theme.textColor
                    inputMethodHints: Qt.ImhNoPredictiveText

                    onTextChanged: {
                        root._error = ""
                        root._updateSuggestions()
                    }
                    onActiveFocusChanged: {
                        if (!activeFocus) suggestionPopup.close()
                        else root._updateSuggestions()
                    }
                    onAccepted: {
                        if (suggestionPopup.opened && suggestionList.currentIndex >= 0) {
                            root._acceptSuggestion(suggestionList.currentIndex)
                        } else {
                            root._commit(root._parseEntries(inputField.text))
                        }
                    }

                    Keys.onDownPressed: function(event) {
                        if (suggestionPopup.opened) {
                            suggestionList.currentIndex = Math.min(suggestionList.currentIndex + 1, root._suggestionData.length - 1)
                        } else {
                            event.accepted = false
                        }
                    }
                    Keys.onUpPressed: function(event) {
                        if (suggestionPopup.opened) {
                            suggestionList.currentIndex = Math.max(suggestionList.currentIndex - 1, -1)
                        } else {
                            event.accepted = false
                        }
                    }
                    Keys.onEscapePressed: function(event) {
                        if (suggestionPopup.opened) suggestionPopup.close()
                        else event.accepted = false
                    }

                    Popup {
                        id: suggestionPopup
                        y: inputField.height + 2
                        width: inputField.width
                        height: Math.min(suggestionList.contentHeight, Kirigami.Units.gridUnit * 2 * 6) + topPadding + bottomPadding
                        padding: 1
                        focus: false
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

                        background: Rectangle {
                            color: Kirigami.Theme.backgroundColor
                            border.color: Kirigami.Theme.highlightColor
                            radius: 4
                        }

                        contentItem: ListView {
                            id: suggestionList
                            model: root._suggestionData
                            currentIndex: -1
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds

                            delegate: ItemDelegate {
                                id: suggestionRow
                                required property var modelData
                                required property int index
                                width: ListView.view.width
                                height: Kirigami.Units.gridUnit * 2
                                highlighted: ListView.isCurrentItem
                                onClicked: root._acceptSuggestion(index)

                                contentItem: RowLayout {
                                    spacing: Kirigami.Units.smallSpacing

                                    Rectangle {
                                        Layout.preferredWidth: 8
                                        Layout.preferredHeight: 8
                                        radius: 4
                                        color: root.categoryColor(suggestionRow.modelData.category)
                                    }
                                    Label {
                                        text: suggestionRow.modelData.name
                                        color: Kirigami.Theme.textColor
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    Label {
                                        visible: !!suggestionRow.modelData.alias
                                        text: "alias: " + suggestionRow.modelData.alias
                                        font: Kirigami.Theme.smallFont
                                        color: Kirigami.Theme.textColor
                                        opacity: 0.6
                                    }
                                    Label {
                                        text: root.categoryTitle(suggestionRow.modelData.category)
                                        font: Kirigami.Theme.smallFont
                                        color: root.categoryColor(suggestionRow.modelData.category)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font: Kirigami.Theme.smallFont
                color: root._error.length > 0 ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                opacity: root._error.length > 0 ? 1 : 0.6
                text: root._error.length > 0
                    ? root._error
                    : "Separate tags with commas. Start with creator: or series: to set the category."
            }
        }

        // Rating
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            enabled: root.targetCount > 0

            RowLayout {
                Layout.fillWidth: true

                Label {
                    text: "Rating"
                    font.weight: Font.DemiBold
                    color: Kirigami.Theme.textColor
                }
                Label {
                    Layout.fillWidth: true
                    text: root._rating === -2 ? "(items differ)" : (root._rating === -1 ? "(unrated)" : "")
                    font: Kirigami.Theme.smallFont
                    color: Kirigami.Theme.textColor
                    opacity: 0.6
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: root._ratingDefs

                    delegate: RatingSegment {
                        required property var modelData
                        text: modelData.label
                        accent: root.ratingColor(modelData.value)
                        active: root._rating === modelData.value
                        onClicked: root._setRating(modelData.value)
                    }
                }
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        // Favorite / Delete
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            enabled: root.targetCount > 0

            Button {
                id: favButton
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: root._favState === 2 ? "Favorited" : "Favorite"
                icon.name: root._favState === 2 ? "starred-symbolic" : "non-starred-symbolic"
                highlighted: root._favState === 2
                onClicked: root._toggleFavorite()
            }

            DangerButton {
                id: deleteButton
                visible: root.showDelete
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                implicitHeight: favButton.implicitHeight
                text: "Delete"
                icon.name: "edit-delete-symbolic"
                Accessible.name: root.targetCount > 1 ? "Delete " + root.targetCount + " items" : "Delete item"
                onClicked: root.deleteRequested()
            }
        }
    }
}
