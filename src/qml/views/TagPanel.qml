import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami

Rectangle {
    id: root

    width: 320
    height: parent ? parent.height : 0
    color: Kirigami.Theme.alternateBackgroundColor

    property var mediaIds: []
    property var tagModel: null
    property var mediaModel: null
    property int currentMediaId: -1

    signal deleteRequested()

    function getSelectedCount() {
        return root.mediaIds.length
    }

    function isSingleItem() {
        return root.mediaIds.length === 1
    }

    function getFirstMediaId() {
        if (root.mediaIds.length > 0) return root.mediaIds[0]
        return -1
    }

    Component.onCompleted: {
        if (isSingleItem()) {
            _loadTags()
        }
    }

    onMediaIdsChanged: _loadTags()
    onCurrentMediaIdChanged: _loadTags()

    function _loadTags() {
        if (!root.tagModel) return
        if (!isSingleItem()) {
            _tagList.clear()
            return
        }
        var tags = root.tagModel.tagsFor(root.getFirstMediaId())
        _tagList.clear()
        for (var i = 0; i < tags.length; i++) {
            _tagList.append({
                tagId: tags[i].id,
                name: tags[i].name,
                mediaId: tags[i].mediaId || root.getFirstMediaId()
            })
        }
    }

    function _addTag() {
        if (!root.tagModel || !inputField.text.trim()) return

            var name = inputField.text.trim().toLowerCase()
            if (name.length === 0) return

                if (root.isSingleItem()) {
                    root.tagModel.addTag(root.getFirstMediaId(), name, "content")
                } else {
                    root.tagModel.addTagsToMedia(root.mediaIds, name, "content")
                }
                inputField.text = ""
                _suggestions.clear()
                _loadTags()
    }

    function _removeTag(mediaId, tagId) {
        if (root.mediaIds.length > 1) {
            root.tagModel.removeTagsFromMedia(root.mediaIds, tagId)
        } else {
            root.tagModel.removeTag(mediaId, tagId)
        }
        _loadTags()
    }

    ListModel {
        id: _tagList
    }

    ListModel {
        id: _suggestions
    }

    function _updateSuggestions() {
        if (!root.tagModel) return
            var text = inputField.text.trim()
            if (text.length === 0) {
                return
            }
            var suggestions = root.tagModel.suggest(text)
            _suggestions.clear()
            for (var i = 0; i < suggestions.length; i++) {
                _suggestions.append({
                    id: suggestions[i].id,
                    name: suggestions[i].name,
                    category: suggestions[i].category
                })
            }
            console.log("suggestions:", _suggestions.count)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        // Header
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label {
                text: root.isSingleItem() ? "Tags" : (root.getSelectedCount() + " items selected")
                font.pixelSize: 16
                font.weight: Font.Bold
                color: Kirigami.Theme.textColor
            }

            Item {
                Layout.fillWidth: true
            }

            Label {
                visible: root.isSingleItem()
                text: "Tags: " + (_tagList.count || 0)
                font.pixelSize: 12
                color: Kirigami.Theme.textColor
            }
        }

        // Tag list
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: tagFlow.implicitHeight

            Flow {
                id: tagFlow
                width: parent.width
                spacing: 6

                Repeater {
                    model: _tagList
                    delegate: Kirigami.Chip {
                        text: model.name
                        closable: true
                        onRemoved: _removeTag(model.mediaId || root.getFirstMediaId(), model.tagId)
                    }
                }
            }
        }

        // Add tag input
        Column {
            Layout.fillWidth: true
            spacing: 4
            z: 1

            TextField {
                id: inputField
                width: parent.width
                placeholderText: "Add tag..."
                placeholderTextColor: Kirigami.Theme.textColor
                color: Kirigami.Theme.textColor
                focus: true
                onTextChanged: _updateSuggestions()
                onAccepted: _addTag()

                Keys.onDownPressed: {
                    if (_suggestions.count > 0) {
                        suggestionList.positionViewAtIndex(0, ListView.Beginning)
                        suggestionList.currentIndex = 0
                    }
                }

                Item {
                    y: inputField.height
                    width: inputField.width
                    z: 100
                    visible: _suggestions.count > 0
                    height: _suggestions.count > 0 ? Math.min(suggestionList.contentHeight, 5 * 28) + 8 : 0

                    Rectangle {
                        anchors.fill: parent
                        color: Kirigami.Theme.backgroundColor
                        border.color: Kirigami.Theme.highlightColor
                        radius: 4
                    }

                    ListView {
                        id: suggestionList
                        anchors.fill: parent
                        model: _suggestions
                        currentIndex: -1
                        clip: true

                        delegate: ItemDelegate {
                            width: suggestionList.width
                            text: model.name
                            highlighted: suggestionList.currentIndex === index

                            onClicked: {
                                inputField.text = model.name
                                _addTag()
                            }

                            Keys.onDownPressed: suggestionList.currentIndex = Math.min(suggestionList.currentIndex + 1, _suggestions.count - 1)
                            Keys.onUpPressed: suggestionList.currentIndex = Math.max(suggestionList.currentIndex - 1, 0)
                        }
                    }
                }
            }
        }

        // Rating section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            Label {
                text: "Rating"
                font.pixelSize: 13
                font.weight: Font.Medium
                color: Kirigami.Theme.textColor
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 4

                RadioButton {
                    text: "General"
                    font.pixelSize: 11
                    checked: true
                    onClicked: {
                        if (root.isSingleItem()) {
                            root.mediaModel.setRating(root.getFirstMediaId(), 0)
                        }
                    }
                }

                RadioButton {
                    text: "SFW"
                    font.pixelSize: 11
                    onClicked: {
                        if (root.isSingleItem()) {
                            root.mediaModel.setRating(root.getFirstMediaId(), 1)
                        }
                    }
                }

                RadioButton {
                    text: "Explicit"
                    font.pixelSize: 11
                    onClicked: {
                        if (root.isSingleItem()) {
                            root.mediaModel.setRating(root.getFirstMediaId(), 2)
                        }
                    }
                }

                RadioButton {
                    text: "NSFW"
                    font.pixelSize: 11
                    onClicked: {
                        if (root.isSingleItem()) {
                            root.mediaModel.setRating(root.getFirstMediaId(), 3)
                        }
                    }
                }

                RadioButton {
                    text: "Unrated"
                    font.pixelSize: 11
                    onClicked: {
                        if (root.isSingleItem()) {
                            root.mediaModel.setRating(root.getFirstMediaId(), -1)
                        }
                    }
                }
            }
        }

        // Favorite button
        Button {
            Layout.fillWidth: true
            text: "Favorite"
            icon.name: "favorite"
            flat: true
            hoverEnabled: true

            onClicked: {
                if (root.isSingleItem()) {
                    var isFav = root.mediaModel.getFavorite(root.getFirstMediaId())
                    root.mediaModel.setFavorite(root.getFirstMediaId(), !isFav)
                }
            }
        }

        // Spacer
        Item {
            Layout.fillHeight: true
        }

        // Delete button
        Button {
            Layout.fillWidth: true
            text: "Delete"
            flat: true
            hoverEnabled: true
            contentItem: Label {
                text: parent.text
                color: Kirigami.Theme.negativeTextColor
                font.pixelSize: 13
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            onClicked: root.deleteRequested()
        }
    }
}
