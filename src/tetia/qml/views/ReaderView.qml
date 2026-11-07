// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami 2.20 as Kirigami
import Tetia 1.0
import "readerWidth.js" as ReaderWidth

// The page reader for comics, PDFs and picture EPUBs. Two layouts share one position (page + how far down it):
// "paged" shows a page at a time, "strip" stacks every page in one long column. All the facts (pages, sizes,
// chapters, remembered settings) come from the ReaderSession; this file only draws and listens.
Kirigami.Page {
    id: page

    readonly property bool isReader: true
    objectName: "readerPage"

    // Where to read: a file path or file:// address. Set when the page is pushed.
    property string location: ""
    property bool fullscreen: false

    signal leaveRequested()
    signal fullscreenToggled()
    signal openSystemRequested(string location)

    title: book.title
    padding: 0

    // ---- state ----
    property int current: 0                  // the page being read
    property real currentOffset: 0           // how far down it, 0..1
    property bool atEnd: false               // paged: past the last page; shows the end card
    property bool atStart: false             // paged: before the first page; shows the previous chapter
    property real zoom: 1                    // paged: on top of the fit
    property real stripZoom: 1               // strip: 1 is the default width (see stripDefault)
    onStripChanged: { zoom = 1; stripZoom = 1; autoScroll = false }
    function zoomBy(clicks, from, low, high) { return Math.max(low, Math.min(high, from * Math.pow(1.15, clicks))) }
    // Zooming out of the strip stops where about two pages (at a typical 2:3 page) fill the window,
    // so a long chapter cannot ask for hundreds of pictures at once
    readonly property real stripMinZoom: stripLoader.item ? stripLoader.item.minZoom
                                                           : Math.max(0.15, Math.min(1, stage.height / (3 * Math.max(1, stage.width))))
    // The strip opens as wide as a page fitted to the window's height would be (what the paged layout does).
    // A typical page is 2:3; wider pages (landscape scans) open at their own shape. Webtoon pieces are much taller
    // than any page, so they count as 2:3 too, or they would always fill the whole width.
    property real pageRatio: 1.5             // typical page height / width of this book
    readonly property real stripDefault: stripLoader.item ? stripLoader.item.defaultZoom
                                                          : Math.max(stripMinZoom, Math.min(1, stage.height / (Math.min(pageRatio, 1.5) * Math.max(1, stage.width))))
    readonly property bool zoomed: strip ? Math.abs(stripZoom - 1) > 0.01 : Math.abs(zoom - 1) > 0.01
    function resetZoom() {
        if (strip) zoomAtPoint(stage.width / 2, stage.height / 2, stripDefault)
        else if (pagedLoader.item) pagedLoader.item.zoomAt(stage.width / 2, stage.height / 2, 1)
    }
    function medianRatio() {
        var ratios = []
        for (var i = 0; i < Math.min(book.pageCount, 10); i++) {
            var size = book.pageSize(i)
            if (size[0] > 0) ratios.push(size[1] / size[0])
        }
        ratios.sort(function(a, b) { return a - b })
        return ratios.length > 0 ? ratios[ratios.length >> 1] : 1.5
    }
    function zoomAtPoint(x, y, target) {
        if (strip && stripLoader.item) stripLoader.item.zoomTo(Math.max(stripMinZoom, Math.min(3, target)), x, y)
        else if (strip) stripZoom = Math.max(stripMinZoom, Math.min(3, target)) / stripDefault
        else if (pagedLoader.item) pagedLoader.item.zoomAt(x, y, Math.max(0.5, Math.min(5, target)))
    }
    property bool chromeVisible: true
    property string sidePanel: ""            // "", "reader" or "info"
    onSidePanelChanged: forceActiveFocus()
    readonly property bool strip: book.layout === "strip"
    readonly property bool rtl: book.direction === "rtl"
    readonly property int lastPage: Math.max(0, book.pageCount - 1)

    ReaderSession { id: book }

    function open(where, fromEnd) {
        autoScroll = false
        atEnd = false
        atStart = false
        zoom = 1
        book.loadFrom(where, fromEnd === true)
    }
    Component.onCompleted: if (location !== "") open(location)
    Component.onDestruction: {
        saveNow()
        book.close()
    }

    Connections {
        target: book
        function onStateChanged() {
            if (book.ready && !page.initialised) page.initialise()
            if (!book.ready) page.initialised = false
        }
    }
    property bool initialised: false

    // Auto-scroll (strip only): the strip drifts on its own at a speed of 1 to 10. Any click, drag, wheel or key
    // stops it; it also stops by itself at the end of the chapter.
    property bool autoScroll: false
    property int autoLevel: 3
    property double autoLast: 0
    function setAutoScroll(on) {
        autoScroll = on && strip && book.ready && stripLoader.item !== null
        if (autoScroll) { autoLast = Date.now(); zonesShown = true; zoneHint = 0 }
    }
    function pauseAuto() { if (autoScroll) autoScroll = false }
    Timer {
        running: page.autoScroll
        repeat: true
        interval: 16
        onTriggered: {
            var view = stripLoader.item
            var now = Date.now()
            var seconds = Math.min(0.1, (now - page.autoLast) / 1000)     // a stalled frame does not leap
            page.autoLast = now
            if (!view || page.atEnd) { page.autoScroll = false; return }
            var max = view.contentHeight - view.height
            var y = view.contentY + page.autoLevel * 30 * seconds
            if (y >= max) { view.contentY = max; page.autoScroll = false }
            else view.contentY = y
        }
    }

    // The click zones are invisible, so a book shows them once when it is opened: tinted for a second, then faded out
    property bool zonesShown: false
    property real zoneHint: 0
    function showZoneHint() {
        zonesShown = true
        zoneHintFade.stop()
        zoneHint = 1
        zoneHintFade.start()
    }
    SequentialAnimation {
        id: zoneHintFade
        PauseAnimation { duration: 1000 }
        NumberAnimation { target: page; property: "zoneHint"; to: 0; duration: 700; easing.type: Easing.InOutQuad }
    }
    function initialise() {
        initialised = true
        pageRatio = medianRatio()
        stripZoom = 1
        current = book.startPage
        currentOffset = book.startOffset
        atEnd = false
        atStart = false
        zoom = 1
        // the strip may have been built before these were known
        if (strip && stripLoader.item) stripLoader.item.showPage(current, currentOffset)
        forceActiveFocus()
        if (!zonesShown) showZoneHint()
    }

    // ---- remembering the position ----
    Timer {
        id: saveTimer
        interval: 700
        onTriggered: page.saveNow()
    }
    function saveNow() {
        saveTimer.stop()
        if (!book.ready) return
        var finished = atEnd || (current >= lastPage && (!strip || (stripLoader.item && stripLoader.item.atBottom)))
        book.savePosition(current, currentOffset, finished)
    }
    function touched() { saveTimer.restart() }

    // ---- moving around ----
    function goTo(n) {
        n = Math.max(0, Math.min(n, lastPage))
        atEnd = false
        atStart = false
        zoom = 1
        current = n
        currentOffset = 0
        if (strip && stripLoader.item) stripLoader.item.showPage(n, 0)
        else if (pagedLoader.item) pagedLoader.item.resetScroll()
        touched()
    }
    // one page on, or back: past the last page is the end card
    function turn(direction) {
        if (direction > 0) {
            if (atStart) atStart = false
            else if (current >= lastPage) { atEnd = true; touched() }
            else goTo(current + 1)
        } else {
            if (atEnd) { atEnd = false; touched() }
            else if (current > 0) goTo(current - 1)
            else if (book.previousPath !== "") atStart = true
        }
    }
    function forward() {
        if (strip) {
            if (stripLoader.item) stripLoader.item.scrollScreen(1)
            return
        }
        if (atEnd) return
        if (!atStart && pagedLoader.item && pagedLoader.item.scrollScreen(1)) return
        turn(1)
    }
    function backward() {
        if (strip) {
            if (stripLoader.item) stripLoader.item.scrollScreen(-1)
            return
        }
        if (atStart) return
        if (!atEnd && pagedLoader.item && pagedLoader.item.scrollScreen(-1)) return
        turn(-1)
    }
    // left/right arrows and the left/right thirds: which way is "forward" depends on the direction
    function step(side) { // side: -1 left, +1 right
        if (strip || !rtl) { if (side > 0) forward(); else backward() }
        else { if (side < 0) forward(); else backward() }
    }
    // going back opens the chapter on its last page, as turning back a page would
    function toggleHelp() {
        if (sidePanel === "reader" && readerPanel.tab === "help") { sidePanel = ""; return }
        readerPanel.tab = "help"
        sidePanel = "reader"
    }
    function openChapter(path, fromEnd) {
        if (path === "") return
        saveNow()
        open(path, fromEnd === true)
    }

    // ---- the picture ----
    Rectangle {
        anchors.fill: parent
        color: "black"
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Item {
            id: stage
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            // Paged layout: one page at a time, fitted, zoomable
            Loader {
                id: pagedLoader
                anchors.fill: parent
                active: book.ready && !page.strip
                sourceComponent: Flickable {
                    id: flick
                    objectName: "readerFlick"
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true

                    readonly property var size: book.pageSize(page.current)
                    readonly property real pw: Math.max(1, size[0])
                    readonly property real ph: Math.max(1, size[1])
                    readonly property real fitScale: book.fit === "width" ? width / pw
                                                    : book.fit === "original" ? 1
                                                    : Math.min(height / ph, width / pw)
                    readonly property real shownW: pw * fitScale * page.zoom
                    readonly property real shownH: ph * fitScale * page.zoom
                    readonly property var chunks: book.chunksOf(page.current)

                    contentWidth: Math.max(width, shownW)
                    contentHeight: Math.max(height, shownH)
                    interactive: contentWidth > width + 1 || contentHeight > height + 1

                    function resetScroll() {
                        contentX = 0
                        contentY = 0
                    }
                    // true if it scrolled (the page is bigger than the window and not at its edge yet)
                    function scrollScreen(dir) {
                        var max = contentHeight - height
                        if (max <= 1) return false
                        if (dir > 0 && contentY >= max - 1) return false
                        if (dir < 0 && contentY <= 1) return false
                        pagedScroll.to = Math.max(0, Math.min(max, contentY + dir * height * 0.9))
                        pagedScroll.restart()
                        return true
                    }
                    function zoomAt(px, py, target) {
                        var before = page.zoom
                        page.zoom = target
                        var ratio = target / before
                        contentX = Math.max(0, Math.min(contentWidth - width, (contentX + px) * ratio - px))
                        contentY = Math.max(0, Math.min(contentHeight - height, (contentY + py) * ratio - py))
                    }
                    NumberAnimation { id: pagedScroll; target: flick; property: "contentY"; duration: 160; easing.type: Easing.OutCubic }
                    onContentYChanged: if (shownH > 0) {
                        page.currentOffset = Math.max(0, Math.min(1, contentY / Math.max(1, contentHeight - height)))
                        page.touched()
                    }

                    Column {
                        x: (flick.contentWidth - width) / 2
                        y: (flick.contentHeight - height) / 2
                        Repeater {
                            model: flick.chunks
                            delegate: Image {
                                required property var modelData
                                readonly property real s: flick.shownW / modelData.width
                                width: flick.shownW
                                height: Math.round(modelData.y1 * s) - Math.round(modelData.y0 * s)
                                fillMode: Image.Stretch
                                asynchronous: true
                                cache: false
                                source: "image://readerpage/" + book.token + "/" + page.current + "/" + modelData.chunk
                                sourceSize.width: ReaderWidth.forPixels(Math.round(flick.shownW * Screen.devicePixelRatio))
                            }
                        }
                    }
                }
            }

            // Pictures of the neighbouring pages are fetched ahead of time, so turning is instant
            Repeater {
                model: book.ready && !page.strip ? [page.current + 1, page.current - 1] : []
                delegate: Image {
                    required property int modelData
                    visible: false
                    asynchronous: true
                    cache: false
                    enabled: false
                    readonly property var size: modelData >= 0 && modelData <= page.lastPage ? book.pageSize(modelData) : [0, 0]
                    source: size[0] > 0 ? "image://readerpage/" + book.token + "/" + modelData + "/0" : ""
                    sourceSize.width: size[0] > 0 ? ReaderWidth.forPixels(Math.round(size[0] * Math.min(stage.height / size[1], stage.width / size[0]) * Screen.devicePixelRatio)) : 0
                }
            }

            // Strip layout: every page in one column, pieces laid edge to edge.
            // A Flickable with every piece placed at an exactly computed height, not a ListView (whose
            // content height is only an estimate while the pieces are of different heights, which made
            // scrolling to the end land anywhere). A piece only loads its picture while it is near the window.
            Loader {
                id: stripLoader
                anchors.fill: parent
                active: book.ready && page.strip
                onLoaded: item.showPage(page.current, page.currentOffset)
                sourceComponent: Flickable {
                    id: list
                    objectName: "readerList"
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    flickableDirection: Flickable.AutoFlickDirection
                    property bool relayout: false
                    // Everything below depends on this one item's own size, never on another item's that resizes
                    // a moment apart (the strip's geometry would flicker, and the position with it)
                    // The width is ONE calculation from this item's own size: a chain of bindings (width -> default ->
                    // strip width) is evaluated in steps, and for an instant the strip had a wrong width, which moved
                    // the scroll position whenever the window changed size (opening the panel)
                    function minWidth() { return Math.max(0.15 * width, Math.min(width, height / 3)) }
                    function defaultWidth() { return Math.max(minWidth(), Math.min(width, height / Math.min(page.pageRatio, 1.5))) }
                    readonly property real stripW: defaultWidth() * page.stripZoom
                    readonly property real minZoom: width > 0 ? minWidth() / width : 0.15
                    readonly property real defaultZoom: width > 0 ? defaultWidth() / width : 1
                    property bool settling: false      // the strip's height has just changed
                    property bool pinnedEnd: false     // the window was at the very end
                    property bool resizing: false
                    // a window that was at the very end stays there while it is resized
                    function layoutChanged() {
                        resizing = true
                        Qt.callLater(function() {
                            if (list.pinnedEnd) list.contentY = list.clampY(list.contentHeight)
                            list.resizing = false
                        })
                    }
                    onHeightChanged: layoutChanged()
                    onWidthChanged: layoutChanged()
                    readonly property real rowW: Math.max(width, stripW)
                    readonly property real imageLeft: (rowW - stripW) / 2
                    // room above the first piece for the card of the previous chapter
                    readonly property real headH: book.previousPath !== "" ? Math.max(height * 0.9, startInStrip.implicitHeight + Kirigami.Units.gridUnit * 4) : 0
                    readonly property real footerH: Math.max(height * 0.9, endInStrip.implicitHeight + Kirigami.Units.gridUnit * 4)

                    // where each piece starts, and where they all end
                    readonly property var geometry: {
                        var tops = [], y = headH
                        var pieces = book.pieces
                        for (var i = 0; i < pieces.length; i++) {
                            var p = pieces[i], s = stripW / p.width
                            tops.push(y)
                            y += Math.round(p.y1 * s) - Math.round(p.y0 * s)
                        }
                        return { tops: tops, total: y }
                    }
                    readonly property real total: geometry.total
                    contentWidth: rowW
                    contentHeight: total + footerH
                    // the last piece has been reached
                    readonly property bool atBottom: contentY + height >= total - 2

                    function pieceHeight(i) {
                        var tops = geometry.tops
                        return (i + 1 < tops.length ? tops[i + 1] : total) - tops[i]
                    }
                    // the piece shown at a content height (binary search)
                    function pieceAt(y) {
                        var tops = geometry.tops, lo = 0, hi = tops.length - 1
                        while (lo < hi) {
                            var mid = (lo + hi + 1) >> 1
                            if (tops[mid] <= y) lo = mid; else hi = mid - 1
                        }
                        return lo
                    }
                    function clampY(y) { return Math.max(0, Math.min(contentHeight - height, y)) }
                    function clampX(x) { return Math.max(0, Math.min(contentWidth - width, x)) }

                    function showPage(n, offset) {
                        var first = book.firstPiece(n)
                        var y = geometry.tops[first]
                        if (n === page.lastPage && offset >= 0.999) {
                            // the very end: the last piece's bottom at the bottom of the window
                            y = total - height
                        } else if (offset > 0) {
                            // walk the page's pieces to the one holding this fraction of its height
                            var chunks = book.chunksOf(n)
                            var row = offset * chunks[chunks.length - 1].y1
                            for (var i = 0; i < chunks.length; i++) {
                                if (row <= chunks[i].y1 || i === chunks.length - 1) {
                                    var within = (row - chunks[i].y0) / Math.max(1, chunks[i].y1 - chunks[i].y0)
                                    y = geometry.tops[first + i] + Math.max(0, Math.min(1, within)) * pieceHeight(first + i)
                                    break
                                }
                            }
                        }
                        contentY = clampY(y)
                    }
                    // where a page starts and ends in the strip
                    function pageTop(n) { return geometry.tops[book.firstPiece(n)] }
                    function pageBottom(n) { return n >= page.lastPage ? total : pageTop(n + 1) }
                    // A page about as tall as the window moves a page at a time and lands exactly on the page, so that
                    // repeated presses never drift to a spot between two pages. Anything taller (webtoon pieces, a
                    // zoomed-in page) scrolls most of a screen, as one continuous column.
                    function scrollScreen(dir) {
                        var current = book.pieces[pieceAt(contentY + 1)].page
                        var top = pageTop(current)
                        var target = contentY + dir * height * 0.9
                        if (pageBottom(current) - top <= height * 1.15) {
                            if (dir > 0) target = current >= page.lastPage ? contentHeight : pageTop(current + 1)
                            else target = contentY > top + 2 ? top : (current === 0 ? 0 : pageTop(current - 1))
                        }
                        stripScroll.to = clampY(target)
                        if (stripScroll.to !== contentY) stripScroll.restart()
                    }
                    NumberAnimation { id: stripScroll; target: list; property: "contentY"; duration: 160; easing.type: Easing.OutCubic }

                    // Zoom so that the point under (px, py) of the window stays where it is
                    function zoomTo(target, px, py) {
                        stripScroll.stop()
                        var i = pieceAt(contentY + py)
                        var frac = (contentY + py - geometry.tops[i]) / Math.max(1, pieceHeight(i))
                        var xFrac = (contentX + px - imageLeft) / stripW
                        relayout = true
                        page.stripZoom = target / defaultZoom          // the geometry above is recomputed at once
                        contentY = clampY(geometry.tops[i] + frac * pieceHeight(i) - py)
                        contentX = clampX(imageLeft + xFrac * stripW - px)
                        relayout = false
                        followScroll()
                    }
                    // a new width without a pointer (panel opened, window resized): stay on the same spot
                    property real lastW: 0
                    onStripWChanged: {
                        if (relayout) return
                        var ratio = lastW > 0 ? stripW / lastW : 1
                        lastW = stripW
                        relayout = true
                        var centre = contentX + width / 2
                        if (pinnedEnd) contentY = clampY(contentHeight)
                        else showPage(page.current, page.currentOffset)
                        contentX = clampX(centre * ratio - width / 2)
                        relayout = false
                    }

                    function followScroll() {
                        // while the layout is changing the old position is kept: what the window shows is not it
                        if (relayout || settling || geometry.tops.length === 0) return
                        if (!resizing) pinnedEnd = contentY >= contentHeight - height - 1
                        var index = pieceAt(contentY + 1)
                        var piece = book.pieces[index]
                        var fraction = Math.max(0, Math.min(1, (contentY - geometry.tops[index]) / Math.max(1, pieceHeight(index))))
                        var pageHeight = book.pageSize(piece.page)[1]
                        page.current = piece.page
                        page.currentOffset = pageHeight > 0 ? Math.min(1, (piece.y0 + fraction * (piece.y1 - piece.y0)) / pageHeight) : 0
                        page.touched()
                    }
                    onContentYChanged: followScroll()
                    Component.onCompleted: lastW = stripW
                    // Whatever the window shows right after the height changed is a side effect of that (the
                    // scroll is clamped to the new height), not where the reader went: do not follow it
                    onTotalChanged: {
                        settling = true
                        Qt.callLater(function() { list.settling = false })
                    }

                    Repeater {
                        model: book.pieces
                        delegate: Item {
                            id: row
                            required property var modelData
                            required property int index
                            x: list.imageLeft
                            y: list.geometry.tops[index]
                            width: list.stripW
                            height: list.pieceHeight(index)
                            readonly property bool near: y + height > list.contentY - list.height * 1.5
                                                         && y < list.contentY + list.height * 2.5
                            Image {
                                anchors.fill: parent
                                fillMode: Image.Stretch
                                asynchronous: true
                                cache: false
                                source: row.near ? "image://readerpage/" + book.token + "/" + row.modelData.page + "/" + row.modelData.chunk : ""
                                sourceSize.width: ReaderWidth.forPixels(Math.round(list.stripW * Screen.devicePixelRatio))
                            }
                        }
                    }
                }
            }

            // Before the first piece: the chapter that came before (scroll up past the top to reach it)
            Item {
                objectName: "stripStart"
                z: 1
                visible: page.strip && stripLoader.item !== null && book.ready && book.previousPath !== ""
                width: stage.width
                y: stripLoader.item ? -stripLoader.item.contentY : 0
                height: stripLoader.item ? stripLoader.item.headH : 0
                ReaderStartCard {
                    id: startInStrip
                    anchors.centerIn: parent
                    previousName: book.previousName
                    onOpenPrevious: page.openChapter(book.previousPath, true)
                }
            }

            // After the last piece: the end of the chapter. Above the click layer, or its buttons could not be clicked.
            Item {
                objectName: "stripEnd"
                z: 1
                visible: page.strip && stripLoader.item !== null && book.ready
                width: stage.width
                y: stripLoader.item ? stripLoader.item.total - stripLoader.item.contentY : 0
                height: stripLoader.item ? stripLoader.item.footerH : 0
                ReaderEndCard {
                    id: endInStrip
                    anchors.centerIn: parent
                    title: book.title
                    nextName: book.nextName
                    onOpenNext: page.openChapter(book.nextPath)
                    onBack: page.leaveRequested()
                }
            }

            // Before the first page of a paged book
            Rectangle {
                z: 1
                anchors.fill: parent
                visible: page.atStart && !page.strip
                color: Qt.rgba(0, 0, 0, 0.6)
                MouseArea { anchors.fill: parent }
                ReaderStartCard {
                    anchors.centerIn: parent
                    previousName: book.previousName
                    onOpenPrevious: page.openChapter(book.previousPath, true)
                }
            }

            // End of a paged book
            Rectangle {
                z: 1
                anchors.fill: parent
                visible: page.atEnd && !page.strip
                color: Qt.rgba(0, 0, 0, 0.6)
                ReaderEndCard {
                    anchors.centerIn: parent
                    title: book.title
                    nextName: book.nextName
                    onOpenNext: page.openChapter(book.nextPath)
                    onBack: page.leaveRequested()
                }
            }

            // Click zones: thirds. Sides turn the page; the middle toggles the controls, or zooms on a double click.
            // A layer of its own above the pictures: a zoomed page is a Flickable, which would keep the clicks from a handler on the stage
            Item {
                id: tapLayer
                anchors.fill: parent
                HoverHandler { id: pointer }

                // the strip scrolls with the wheel by itself; this only notices it
                WheelHandler { enabled: page.strip; blocking: false; onWheel: page.pauseAuto() }

                // The wheel turns pages of the paged layout. A page that is bigger than the window (zoomed, or fitted
                // to its width) scrolls first, and turns only when pushed again at its edge.
                WheelHandler {
                    id: wheelTurn
                    objectName: "wheelTurn"
                    enabled: book.ready && !page.strip
                    acceptedModifiers: Qt.NoModifier
                    property real pushed: 0
                    onWheel: function(event) {
                        var dy = event.angleDelta.y
                        if (dy === 0) return
                        if (page.atEnd) {
                            if (dy > 0) { page.atEnd = false; page.touched() }
                            return
                        }
                        if (page.atStart) {
                            if (dy < 0) page.atStart = false
                            return
                        }
                        var view = pagedLoader.item
                        var max = view ? view.contentHeight - view.height : 0
                        if (max > 1) {
                            var atEdge = (dy < 0 && view.contentY >= max - 1) || (dy > 0 && view.contentY <= 1)
                            if (!atEdge) {
                                view.contentY = Math.max(0, Math.min(max, view.contentY - dy))
                                pushed = 0
                                return
                            }
                        }
                        pushed += dy
                        pushReset.restart()
                        if (Math.abs(pushed) >= (max > 1 ? 240 : 120)) {
                            var direction = pushed < 0 ? 1 : -1
                            pushed = 0
                            page.turn(direction)
                        }
                    }
                }
                Timer { id: pushReset; interval: 500; onTriggered: wheelTurn.pushed = 0 }

                // Dragging pans whatever is shown: a zoomed page, or the strip
                DragHandler {
                    id: pan
                    enabled: book.ready && !page.atEnd && !page.atStart
                    target: null
                    acceptedButtons: Qt.LeftButton
                    property point last: Qt.point(0, 0)
                    onActiveChanged: if (active) { last = Qt.point(0, 0); page.pauseAuto() }
                    onTranslationChanged: {
                        var view = page.strip ? stripLoader.item : pagedLoader.item
                        if (!view || !active) return
                        view.contentX = Math.max(0, Math.min(view.contentWidth - view.width, view.contentX - (translation.x - last.x)))
                        view.contentY = Math.max(0, Math.min(view.contentHeight - view.height, view.contentY - (translation.y - last.y)))
                        last = translation
                    }
                }

                // Any press on the page stops the auto-scroll
                TapHandler { acceptedButtons: Qt.AllButtons; gesturePolicy: TapHandler.ReleaseWithinBounds; onPressedChanged: if (pressed) page.pauseAuto() }

                // Clicks: the sides turn the page (unless zoomed), the middle shows or hides the controls,
                // and a double click zooms in or back out. Which third counts is where the press was.
                TapHandler {
                    id: taps
                    enabled: book.ready && !page.atEnd && !page.atStart
                    acceptedButtons: Qt.LeftButton
                    gesturePolicy: TapHandler.DragThreshold
                    onTapped: function(point) {
                        var third = tapLayer.width / 3
                        var x = point.pressPosition.x
                        var side = page.zoomed ? 0 : (x < third ? -1 : (x > 2 * third ? 1 : 0))
                        if (side !== 0) { middleTimer.stop(); page.step(side) }
                        else if (middleTimer.running) {
                            middleTimer.stop()
                            page.zoomAtPoint(point.pressPosition.x, point.pressPosition.y,
                                             page.zoomed ? (page.strip ? page.stripDefault : 1) : (page.strip ? page.stripDefault * 2 : 2.5))
                        } else {
                            middleTimer.start()
                        }
                    }
                }
            }
            // The hint for the click zones: left and right thirds, which only look, never take a click
            Repeater {
                model: [-1, 1]
                delegate: Rectangle {
                    required property int modelData
                    z: 1
                    visible: page.zoneHint > 0 && !page.atEnd && !page.atStart
                    opacity: page.zoneHint
                    enabled: false
                    x: modelData < 0 ? 0 : stage.width * 2 / 3
                    width: stage.width / 3
                    height: stage.height
                    color: Qt.alpha(page.palette.highlight, 0.35)
                    border.width: 1
                    border.color: Qt.alpha(page.palette.highlight, 0.7)
                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: Kirigami.Units.iconSizes.large
                        height: width
                        color: Qt.lighter(page.palette.highlight, 1.6)
                        isMask: true
                        // the arrows point to the side they are on (which of them is "forward" depends on the direction)
                        source: modelData < 0 ? "go-previous" : "go-next"
                    }
                }
            }

            Timer {
                id: middleTimer
                interval: Qt.styleHints.mouseDoubleClickInterval
                onTriggered: page.chromeVisible = !page.chromeVisible
            }

            // Ctrl + wheel zooms (see WheelZoom: a WheelHandler misses some wheels)
            WheelZoom {
                target: page.Window.window
                enabled: page.isCurrentPage && book.ready
                onStepped: function(delta) {
                    page.pauseAuto()
                    page.zoomAtPoint(pointer.point.position.x, pointer.point.position.y,
                                     (page.strip ? page.stripZoom * page.stripDefault : page.zoom) * Math.pow(1.15, delta))
                }
            }

            // Shown while the strip scrolls by itself
            Rectangle {
                objectName: "autoScrollNote"
                z: 2
                visible: page.autoScroll
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: Kirigami.Units.smallSpacing
                radius: 6
                color: Qt.rgba(0, 0, 0, 0.55)
                width: noteLabel.implicitWidth + Kirigami.Units.largeSpacing * 2
                height: noteLabel.implicitHeight + Kirigami.Units.smallSpacing * 2
                Label {
                    id: noteLabel
                    anchors.centerIn: parent
                    color: "white"
                    text: "Auto-scrolling \u2014 click or press A to stop"
                }
            }

            BusyIndicator {
                anchors.centerIn: parent
                running: book.loading
                visible: running
            }

            // Could not open
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 24)
                visible: !book.loading && !book.ready && book.error !== ""
                spacing: Kirigami.Units.largeSpacing
                Kirigami.Icon {
                    source: "dialog-warning"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: Kirigami.Units.iconSizes.large
                    Layout.preferredHeight: Kirigami.Units.iconSizes.large
                }
                Label {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    color: "white"
                    text: book.error
                }
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    Button {
                        text: "Open with the system app"
                        icon.name: "document-open"
                        onClicked: page.openSystemRequested(book.path)
                    }
                    Button {
                        text: "Back"
                        onClicked: page.leaveRequested()
                    }
                }
            }

            // ---- the controls ----
            // top right: details, reader settings
            Rectangle {
                id: topBar
                z: 2
                visible: page.chromeVisible && book.ready
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: Kirigami.Units.smallSpacing
                radius: 6
                color: Qt.rgba(0, 0, 0, 0.55)
                implicitWidth: topRow.implicitWidth + Kirigami.Units.smallSpacing * 2
                implicitHeight: topRow.implicitHeight + Kirigami.Units.smallSpacing * 2
                width: implicitWidth
                height: implicitHeight
                Row {
                    id: topRow
                    anchors.centerIn: parent
                    ToolButton {
                        objectName: "infoButton"
                        focusPolicy: Qt.NoFocus
                        visible: book.mediaId >= 0
                        icon.name: "help-about-symbolic"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        checkable: true
                        checked: page.sidePanel === "info"
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Details (I)"
                        onClicked: page.sidePanel = page.sidePanel === "info" ? "" : "info"
                    }
                    ToolButton {
                        objectName: "settingsButton"
                        focusPolicy: Qt.NoFocus
                        icon.name: "configure"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        checkable: true
                        checked: page.sidePanel === "reader" && readerPanel.tab !== "help"
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Reader settings"
                        onClicked: {
                            if (page.sidePanel === "reader" && readerPanel.tab !== "help") page.sidePanel = ""
                            else { if (readerPanel.tab === "help") readerPanel.tab = "reader"; page.sidePanel = "reader" }
                        }
                    }
                }
            }

            // bottom: step buttons and the page slider
            Rectangle {
                id: bottomBar
                z: 2
                visible: page.chromeVisible && book.ready && !page.atEnd
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: Kirigami.Units.smallSpacing
                height: Kirigami.Units.gridUnit * 2.6
                radius: 6
                color: Qt.rgba(0, 0, 0, 0.55)

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Kirigami.Units.largeSpacing
                    anchors.rightMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                  // the page controls follow the reading direction; the fullscreen button stays at the right end
                  RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: Kirigami.Units.smallSpacing
                    LayoutMirroring.enabled: !page.strip && page.rtl
                    LayoutMirroring.childrenInherit: false

                    ToolButton {
                        objectName: "backButton"
                        focusPolicy: Qt.NoFocus
                        icon.name: page.strip || !page.rtl ? "go-previous" : "go-next"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        enabled: page.current > 0 || page.atEnd
                        onClicked: page.backward()
                    }
                    Slider {
                        objectName: "pageSlider"
                        focusPolicy: Qt.NoFocus
                        LayoutMirroring.enabled: !page.strip && page.rtl
                        LayoutMirroring.childrenInherit: true
                        Layout.fillWidth: true
                        from: 0
                        to: Math.max(1, page.lastPage)
                        stepSize: 1
                        snapMode: Slider.SnapAlways
                        value: page.current
                        enabled: page.lastPage > 0
                        onMoved: page.goTo(Math.round(value))
                    }
                    ToolButton {
                        objectName: "resetZoomButton"
                        focusPolicy: Qt.NoFocus
                        visible: page.zoomed
                        text: "Reset zoom"
                        contentItem: Label {
                            text: parent.text
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Back to the default zoom (Ctrl+0, or double-click)"
                        onClicked: page.resetZoom()
                    }
                    Label {
                        objectName: "pageChip"
                        color: "white"
                        text: (page.current + 1) + " / " + book.pageCount
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 3.5
                        horizontalAlignment: Text.AlignHCenter
                    }
                    ToolButton {
                        objectName: "forwardButton"
                        focusPolicy: Qt.NoFocus
                        icon.name: page.strip || !page.rtl ? "go-next" : "go-previous"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        onClicked: page.forward()
                    }
                  }

                    ToolButton {
                        objectName: "fullscreenButton"
                        focusPolicy: Qt.NoFocus
                        icon.name: page.fullscreen ? "view-restore" : "view-fullscreen"
                        icon.color: "white"
                        display: AbstractButton.IconOnly
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: page.fullscreen ? "Leave fullscreen (F11)" : "Fullscreen (F11)"
                        onClicked: page.fullscreenToggled()
                    }
                }
            }
        }

        ReaderPanel {
            id: readerPanel
            objectName: "readerPanel"
            Layout.fillHeight: true
            Layout.preferredWidth: implicitWidth
            visible: page.sidePanel === "reader"
            session: book
            currentPage: page.current
            onCloseRequested: page.sidePanel = ""
            onChapterChosen: function(path) { page.openChapter(path) }
            autoAvailable: page.strip
            autoScroll: page.autoScroll
            autoLevel: page.autoLevel
            onAutoScrollRequested: function(on) { page.setAutoScroll(on) }
            onAutoLevelRequested: function(level) { page.autoLevel = level }
        }

        MetadataPanel {
            objectName: "readerInfo"
            Layout.fillHeight: true
            Layout.preferredWidth: implicitWidth
            visible: page.sidePanel === "info" && book.mediaId >= 0
            mediaId: visible ? book.mediaId : -1
            onCloseRequested: page.sidePanel = ""
        }
    }

    // ---- keys ----
    Keys.onShortcutOverride: function(event) {
        if (event.key === Qt.Key_Escape && event.modifiers === Qt.NoModifier) event.accepted = true
    }
    Keys.onPressed: function(event) {
        if (event.key !== Qt.Key_A) pauseAuto()
        if ((event.modifiers & Qt.ControlModifier) && !(event.modifiers & (Qt.AltModifier | Qt.MetaModifier))) {
            var cur = strip ? stripZoom * stripDefault : zoom
            if (event.key === Qt.Key_0) { resetZoom(); event.accepted = true }
            else if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) { zoomAtPoint(stage.width / 2, stage.height / 2, cur * 1.15); event.accepted = true }
            else if (event.key === Qt.Key_Minus) { zoomAtPoint(stage.width / 2, stage.height / 2, cur / 1.15); event.accepted = true }
            return
        }
        if (event.modifiers & (Qt.AltModifier | Qt.MetaModifier)) return
        var shift = (event.modifiers & Qt.ShiftModifier) !== 0
        var handled = true
        switch (event.key) {
        case Qt.Key_Left: step(-1); break
        case Qt.Key_Right: step(1); break
        case Qt.Key_Space: if (shift) backward(); else forward(); break
        case Qt.Key_PageDown: forward(); break
        case Qt.Key_PageUp: backward(); break
        case Qt.Key_Down: nudge(1); break
        case Qt.Key_Up: nudge(-1); break
        case Qt.Key_Home: goTo(0); break
        case Qt.Key_End: goTo(lastPage); break
        case Qt.Key_F11: fullscreenToggled(); break
        case Qt.Key_F1: toggleHelp(); break
        case Qt.Key_A: if (strip) setAutoScroll(!autoScroll); break
        case Qt.Key_I: if (book.mediaId >= 0) sidePanel = sidePanel === "info" ? "" : "info"; break
        case Qt.Key_BracketRight: openChapter(book.nextPath); break
        case Qt.Key_BracketLeft: openChapter(book.previousPath, true); break
        case Qt.Key_Escape:
            if (fullscreen) fullscreenToggled()
            else if (sidePanel !== "") sidePanel = ""
            else leaveRequested()
            break
        default: handled = false
        }
        event.accepted = handled
    }
    function nudge(dir) {
        var item = strip ? stripLoader.item : pagedLoader.item
        if (!item) return
        var max = item.contentHeight - item.height
        item.contentY = Math.max(0, Math.min(max, item.contentY + dir * 120))
    }
}
