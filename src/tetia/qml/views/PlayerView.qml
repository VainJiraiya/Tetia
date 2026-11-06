// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0

// The video playback. libmpv draws the picture (the Player), everything on top is here.
//
// Two modes share all of it. In a series (a show's episodes) the arrows seek and there are previous / next episode
// buttons; anywhere else (a folder of videos, shown as a gallery) the arrows go to the previous / next video like the
// photo viewer, with its edge buttons and its "3 / 48" chip, and a video shorter than `clipSeconds` loops.
Kirigami.Page {
    id: page

    // Treated like the reader by the window: no tabs or search here, and in fullscreen no header
    readonly property bool isReader: true
    readonly property bool isPlayer: true
    objectName: "playerPage"

    // [{uri, name}] to step through, and the one playing. `series` marks a show (then `showTitle` and `showPath` say which).
    property var playlist: []
    property int index: 0
    property bool series: false
    property string showTitle: ""
    property string showPath: ""
    property bool fullscreen: false

    // A video shorter than this loops when browsing; a longer one (a film, an episode) stops at the end
    readonly property real clipSeconds: 15 * 60

    signal leaveRequested()
    signal fullscreenToggled()
    signal openSystemRequested(string location)
    signal episodeStarted(string uri)

    readonly property int count: playlist.length
    readonly property bool hasPrevious: index > 0
    readonly property bool hasNext: index < count - 1
    readonly property bool browsing: !series && count > 1

    title: series ? (playback.title !== "" ? showTitle + " · " + playback.title : showTitle) : playback.title
    padding: 0

    // ---- the controls' state ----
    property bool controlsVisible: true
    property bool autoNext: false
    property bool scrubbing: false
    property real scrubTo: 0
    readonly property bool barHeld: barHover.hovered || scrubbing || menuOpen
    property bool menuOpen: subtitleMenu.visible || audioMenu.visible || speedMenu.visible

    Player { id: playback }

    function formatTime(seconds) {
        var s = Math.max(0, Math.floor(seconds))
        var h = Math.floor(s / 3600)
        var m = Math.floor((s % 3600) / 60)
        var r = s % 60
        var two = function(n) { return (n < 10 ? "0" : "") + n }
        return h > 0 ? h + ":" + two(m) + ":" + two(r) : m + ":" + two(r)
    }

    function showControls() {
        controlsVisible = true
        hideTimer.restart()
    }

    function openAt(i) {
        if (i < 0 || i >= count) return
        index = i
        loopApplied = -1
        var item = playlist[i]
        playback.load(item.uri, 0)
        if (series) page.episodeStarted(item.uri)
        showControls()
    }
    function goNext() { if (hasNext) openAt(index + 1) }
    function goPrevious() { if (hasPrevious) openAt(index - 1) }

    // A short clip loops while browsing; decided once the length is known
    property int loopApplied: -1
    Connections {
        target: playback
        function onStateChanged() {
            if (playback.loaded && page.loopApplied !== page.index) {
                page.loopApplied = page.index
                playback.setLoop(!page.series && playback.duration < page.clipSeconds)
            }
        }
        function onEndReached() {
            // an episode is followed by the next at once; browsing, the next file only if autoplay is on
            if (page.hasNext && (page.series || page.autoNext)) page.goNext()
        }
    }

    Component.onCompleted: {
        openAt(Math.max(0, Math.min(index, count - 1)))
        forceActiveFocus()
    }
    Component.onDestruction: playback.shutdown()
    onVisibleChanged: {
        if (!visible) playback.setPaused(true)
        else forceActiveFocus()
    }

    Timer {
        id: hideTimer
        interval: 3000
        onTriggered: if (!playback.paused && !page.barHeld && !playback.ended) page.controlsVisible = false
    }

    // ---- the stage ----
    Rectangle {
        id: stage
        anchors.fill: parent
        color: "black"

        MpvVideo {
            anchors.fill: parent
            player: playback
        }

        BusyIndicator {
            anchors.centerIn: parent
            running: !playback.loaded && playback.error === ""
            visible: running
        }

        Label {
            anchors.centerIn: parent
            visible: playback.error !== ""
            color: "white"
            text: playback.error + "\n" + (page.count > 0 ? page.playlist[page.index].name : "")
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            width: Math.min(parent.width - 48, 520)
        }

        // Clicks: one anywhere plays or pauses (after a short wait, in case it is the first of two); two on the left
        // or right third skip 10 seconds, two in the middle go fullscreen. Space pauses at once (see the keys).
        MouseArea {
            id: clicks
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: page.controlsVisible || playback.paused ? Qt.ArrowCursor : Qt.BlankCursor
            property double lastDouble: 0
            onPositionChanged: page.showControls()
            onClicked: {
                if (Date.now() - lastDouble < 400) return        // the release that ends a double click
                page.showControls()
                clickTimer.restart()
            }
            onDoubleClicked: function(mouse) {
                lastDouble = Date.now()
                clickTimer.stop()
                var third = mouse.x / width
                if (third < 1 / 3) playback.seek(-10)
                else if (third > 2 / 3) playback.seek(10)
                else page.fullscreenToggled()
                page.showControls()
            }
        }
        Timer {
            id: clickTimer
            interval: 250
            onTriggered: playback.togglePause()
        }

        // ---- browse mode: previous / next video, like the photo viewer ----
        RoundButton {
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            visible: page.browsing
            icon.name: "go-previous"
            focusPolicy: Qt.NoFocus
            hoverEnabled: true
            opacity: (page.controlsVisible && page.hasPrevious) ? 0.85 : 0
            enabled: opacity > 0.05
            Behavior on opacity { NumberAnimation { duration: 150 } }
            onHoveredChanged: if (hovered) { page.controlsVisible = true; hideTimer.stop() } else hideTimer.restart()
            onClicked: page.goPrevious()
        }
        RoundButton {
            anchors.right: parent.right
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            visible: page.browsing
            icon.name: "go-next"
            focusPolicy: Qt.NoFocus
            hoverEnabled: true
            opacity: (page.controlsVisible && page.hasNext) ? 0.85 : 0
            enabled: opacity > 0.05
            Behavior on opacity { NumberAnimation { duration: 150 } }
            onHoveredChanged: if (hovered) { page.controlsVisible = true; hideTimer.stop() } else hideTimer.restart()
            onClicked: page.goNext()
        }

        // the title, when the window's own header is gone (fullscreen)
        Rectangle {
            visible: page.fullscreen && page.controlsVisible
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: fullTitle.implicitHeight + Kirigami.Units.largeSpacing * 2
            color: Qt.rgba(0, 0, 0, 0.55)
            Label {
                id: fullTitle
                anchors.fill: parent
                anchors.margins: Kirigami.Units.largeSpacing
                color: "white"
                elide: Text.ElideRight
                text: page.title
                font.weight: Font.DemiBold
                verticalAlignment: Text.AlignVCenter
            }
        }

        // "3 / 48", above the bar
        Rectangle {
            visible: page.browsing
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: bar.top
            anchors.bottomMargin: Kirigami.Units.largeSpacing
            width: chipLabel.implicitWidth + 24
            height: chipLabel.implicitHeight + 12
            radius: height / 2
            color: Qt.rgba(0, 0, 0, 0.65)
            opacity: page.controlsVisible ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 250 } }
            Label {
                id: chipLabel
                anchors.centerIn: parent
                text: (page.index + 1) + " / " + page.count
                color: "white"
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
        }

        // ---- the bar ----
        Rectangle {
            id: bar
            z: 2
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            // flush with the window's edges; floating in fullscreen
            anchors.margins: page.fullscreen ? Kirigami.Units.smallSpacing : 0
            radius: page.fullscreen ? 6 : 0
            color: Qt.rgba(0, 0, 0, 0.6)
            opacity: page.controlsVisible || page.barHeld ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 200 } }
            implicitHeight: barColumn.implicitHeight + Kirigami.Units.smallSpacing * 2
            height: implicitHeight

            HoverHandler { id: barHover }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton }    // clicks on the bar are not the video's

            ColumnLayout {
                id: barColumn
                anchors.fill: parent
                anchors.margins: Kirigami.Units.smallSpacing
                spacing: 0

                // the seek bar
                Item {
                    id: seek
                    Layout.fillWidth: true
                    Layout.preferredHeight: Kirigami.Units.gridUnit * 1.2
                    readonly property real fraction: playback.duration > 0
                        ? Math.max(0, Math.min(1, (page.scrubbing ? page.scrubTo : playback.position) / playback.duration)) : 0
                    function timeAt(x) { return playback.duration * Math.max(0, Math.min(1, x / width)) }

                    Rectangle {
                        id: track
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        height: seekMouse.containsMouse || page.scrubbing ? 6 : 4
                        radius: height / 2
                        color: Qt.rgba(1, 1, 1, 0.25)
                        Rectangle {
                            width: parent.width * seek.fraction
                            height: parent.height
                            radius: parent.radius
                            color: Kirigami.Theme.highlightColor
                        }
                    }
                    Rectangle {
                        x: track.width * seek.fraction - width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        width: 12
                        height: 12
                        radius: 6
                        color: "white"
                        visible: seekMouse.containsMouse || page.scrubbing
                    }
                    MouseArea {
                        id: seekMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: playback.duration > 0
                        onPressed: function(mouse) { page.scrubbing = true; page.scrubTo = seek.timeAt(mouse.x) }
                        onPositionChanged: function(mouse) { if (pressed) page.scrubTo = seek.timeAt(mouse.x) }
                        onReleased: { playback.seekTo(page.scrubTo); page.scrubbing = false }
                    }
                    // the time under the pointer
                    Rectangle {
                        visible: seekMouse.containsMouse || page.scrubbing
                        x: Math.max(0, Math.min(seek.width - width, seekMouse.mouseX - width / 2))
                        y: -height - 2
                        width: hoverLabel.implicitWidth + 12
                        height: hoverLabel.implicitHeight + 6
                        radius: 4
                        color: Qt.rgba(0, 0, 0, 0.85)
                        Label {
                            id: hoverLabel
                            anchors.centerIn: parent
                            color: "white"
                            font.pixelSize: 12
                            text: page.formatTime(page.scrubbing ? page.scrubTo : seek.timeAt(seekMouse.mouseX))
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    ToolButton {
                        icon.name: playback.paused || playback.ended ? "media-playback-start" : "media-playback-pause"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: playback.paused ? "Play (Space)" : "Pause (Space)"
                        onClicked: playback.paused || playback.ended ? playback.setPaused(false) : playback.setPaused(true)
                    }
                    ToolButton {
                        visible: page.series
                        enabled: page.hasPrevious
                        icon.name: "media-skip-backward"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Previous episode (Page Up)"
                        onClicked: page.goPrevious()
                    }
                    ToolButton {
                        visible: page.series
                        enabled: page.hasNext
                        icon.name: "media-skip-forward"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Next episode (Page Down)"
                        onClicked: page.goNext()
                    }
                    ToolButton {
                        icon.name: playback.muted || playback.volume === 0 ? "audio-volume-muted" : "audio-volume-high"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Mute (M)"
                        onClicked: playback.toggleMute()
                    }
                    Slider {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                        from: 0
                        to: 100
                        value: playback.muted ? 0 : playback.volume
                        focusPolicy: Qt.NoFocus
                        onMoved: { if (playback.muted) playback.toggleMute(); playback.setVolume(value) }
                    }
                    Label {
                        Layout.leftMargin: Kirigami.Units.largeSpacing
                        color: "white"
                        font.pixelSize: 13
                        text: page.formatTime(page.scrubbing ? page.scrubTo : playback.position) + " / " + page.formatTime(playback.duration)
                    }
                    Item { Layout.fillWidth: true }

                    ToolButton {
                        visible: page.browsing
                        checkable: true
                        checked: page.autoNext
                        icon.source: Qt.resolvedUrl("icons/autoplay-next.svg")
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Play the next file when this one ends"
                        onClicked: page.autoNext = checked
                    }
                    ToolButton {
                        id: subtitleButton
                        property double closedAt: 0       // a click that closes the menu is also a click on this button
                        icon.source: Qt.resolvedUrl("icons/subtitles.svg")
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered && !subtitleMenu.visible
                        ToolTip.delay: 500
                        ToolTip.text: "Subtitles"
                        onClicked: if (Date.now() - closedAt > 250) subtitleMenu.open()

                        Menu {
                            id: subtitleMenu
                            onClosed: subtitleButton.closedAt = Date.now()
                            y: -height          // above the button, whatever the menu holds now
                            MenuItem {
                                text: "Off"
                                checkable: true
                                checked: !playback.subtitleTracks.some(function(t) { return t.selected })
                                onTriggered: playback.setSubtitleTrack(0)
                            }
                            MenuSeparator {}
                            Instantiator {
                                model: playback.subtitleTracks
                                delegate: MenuItem {
                                    required property var modelData
                                    text: modelData.label
                                    checkable: true
                                    checked: modelData.selected
                                    onTriggered: playback.setSubtitleTrack(modelData.id)
                                }
                                onObjectAdded: function(i, item) { subtitleMenu.insertItem(i + 2, item) }
                                onObjectRemoved: function(i, item) { subtitleMenu.removeItem(item) }
                            }
                            MenuSeparator {}
                            MenuItem {
                                text: "Add subtitle file…"
                                icon.name: "document-open"
                                onTriggered: subtitleDialog.open()
                            }
                        }
                    }
                    ToolButton {
                        id: audioButton
                        property double closedAt: 0
                        icon.source: Qt.resolvedUrl("icons/audio-track.svg")     // our own: no theme has a good one
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        visible: playback.audioTracks.length > 0
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered && !audioMenu.visible
                        ToolTip.delay: 500
                        ToolTip.text: "Audio track"
                        onClicked: if (Date.now() - closedAt > 250) audioMenu.open()

                        Menu {
                            id: audioMenu
                            onClosed: audioButton.closedAt = Date.now()
                            y: -height          // above the button, whatever the menu holds now
                            Instantiator {
                                model: playback.audioTracks
                                delegate: MenuItem {
                                    required property var modelData
                                    text: modelData.label
                                    checkable: true
                                    checked: modelData.selected
                                    onTriggered: playback.setAudioTrack(modelData.id)
                                }
                                onObjectAdded: function(i, item) { audioMenu.insertItem(i, item) }
                                onObjectRemoved: function(i, item) { audioMenu.removeItem(item) }
                            }
                        }
                    }
                    ToolButton {
                        id: speedButton
                        property double closedAt: 0
                        text: (Math.round(playback.speed * 100) / 100) + "×"
                        font.pixelSize: 13
                        icon.color: "white"
                        palette.buttonText: "white"
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered && !speedMenu.visible
                        ToolTip.delay: 500
                        ToolTip.text: "Speed"
                        onClicked: if (Date.now() - closedAt > 250) speedMenu.open()

                        Menu {
                            id: speedMenu
                            onClosed: speedButton.closedAt = Date.now()
                            y: -height          // above the button, whatever the menu holds now
                            Repeater {
                                model: [0.5, 0.75, 1, 1.25, 1.5, 2]
                                delegate: MenuItem {
                                    required property real modelData
                                    text: modelData + "×"
                                    checkable: true
                                    checked: Math.abs(playback.speed - modelData) < 0.01
                                    onTriggered: playback.setSpeed(modelData)
                                }
                            }
                        }
                    }
                    ToolButton {
                        icon.name: page.fullscreen ? "view-restore" : "view-fullscreen"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        focusPolicy: Qt.NoFocus
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Fullscreen (F)"
                        onClicked: page.fullscreenToggled()
                    }
                }
            }
        }
    }

    FileDialog {
        id: subtitleDialog
        title: "Add subtitles"
        nameFilters: ["Subtitles (*.srt *.ass *.ssa *.vtt *.sub)", "All files (*)"]
        onAccepted: playback.addSubtitleFile(selectedFile.toString())
    }

    // ---- keys ----
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Escape && event.modifiers === Qt.NoModifier) event.accepted = true
    }
    Keys.onPressed: function(event) {
        if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return
        var shift = (event.modifiers & Qt.ShiftModifier) !== 0
        var handled = true
        showControls()
        switch (event.key) {
        case Qt.Key_Space: playback.togglePause(); break                    // at once: only a click on the picture waits
        case Qt.Key_Left:
            if (series || shift) playback.seek(shift ? -10 : -5); else goPrevious()
            break
        case Qt.Key_Right:
            if (series || shift) playback.seek(shift ? 10 : 5); else goNext()
            break
        case Qt.Key_J: playback.seek(-10); break
        case Qt.Key_L: playback.seek(10); break
        case Qt.Key_PageUp: goPrevious(); break
        case Qt.Key_PageDown: goNext(); break
        case Qt.Key_Up: playback.setVolume(playback.volume + 5); break
        case Qt.Key_Down: playback.setVolume(playback.volume - 5); break
        case Qt.Key_M: playback.toggleMute(); break
        case Qt.Key_F: page.fullscreenToggled(); break
        case Qt.Key_Escape:
            if (fullscreen) page.fullscreenToggled(); else page.leaveRequested()
            break
        default: handled = false
        }
        event.accepted = handled
    }
}
