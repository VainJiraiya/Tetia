# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The reader's state for QML: one open book, how it is laid out, where you are, your bookmarks.

Opening reads the archive and measures every page on a worker thread, so the window never waits.
Pages themselves reach QML through ReaderPageProvider (image://readerpage/<token>/<page>/<chunk>),
drawn at the width the screen asks for.
"""
import logging
import os
import threading
import uuid

from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, Property, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import QQuickImageProvider

from tetia.models import covers, reader
from tetia.models.database import get_database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

# ---- Pages for the image provider ----------------------------------------------------------

_books = {}                       # token -> Book
_books_lock = threading.Lock()


def _register(book) -> str:
    token = uuid.uuid4().hex[:12]
    with _books_lock:
        _books[token] = book
    return token


def _unregister(token: str):
    with _books_lock:
        _books.pop(token, None)


class ReaderPageProvider(QQuickImageProvider):
    """image://readerpage/<token>/<page>/<chunk>, drawn as wide as the screen asked (never enlarged)."""

    def __init__(self):
        super().__init__(QQuickImageProvider.Image)

    def requestImage(self, id_string: str, requested_size: QSize, size: QSize):
        parts = id_string.split("/")
        image = QImage()
        if len(parts) == 3 and parts[1].lstrip("-").isdigit() and parts[2].lstrip("-").isdigit():
            with _books_lock:
                book = _books.get(parts[0])
            if book is not None:
                width = requested_size.width() if requested_size.isValid() and requested_size.width() > 0 else reader.DEFAULT_WIDTH
                try:
                    image = book.render(int(parts[1]), width, int(parts[2]))
                except Exception as e:      # noqa: BLE001 - a bad page must not take the reader down
                    logger.warning("Could not draw page %s: %s", id_string, e)
        if not image.isNull():
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image


# ---- Opening on a worker thread ----------------------------------------------------------------

class _Opened(QObject):
    done = Signal(int, object, str)       # request, book (or None), error text


class _OpenJob(QRunnable):
    def __init__(self, request: int, path: str, opened: _Opened):
        super().__init__()
        self._request, self._path, self._opened = request, path, opened

    def run(self):
        book, error = None, ""
        try:
            book = reader.open_book(self._path)
            book.scan_sizes()
        except reader.ReaderError as e:
            error = str(e)
        except Exception as e:          # noqa: BLE001 - never let a worker die silently
            logger.warning("Could not open %s: %s", self._path, e)
            error = "The file could not be read."
        self._opened.done.emit(self._request, book, error)


# ---- The session ----------------------------------------------------------------------------------

@QmlElement
class ReaderSession(QObject):
    stateChanged = Signal()
    settingsChanged = Signal()
    bookmarksChanged = Signal()
    chaptersChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._opened = _Opened(self)
        self._opened.done.connect(self._on_opened)
        self._request = 0
        self._reset()

    def _reset(self):
        self._path = ""
        self._book = None
        self._token = ""
        self._loading = False
        self._error = ""
        self._pieces = []
        self._layout, self._direction, self._fit = "paged", "ltr", "height"
        self._remember = True
        self._media_id = None
        self._scope = ""
        self._context = None
        self._start_page, self._start_offset = 0, 0.0
        self._from_end = False
        self._bookmarks = []
        self._chapters = []
        self._page, self._offset = 0, 0.0

    # ---- what QML reads ------------------------------------------------------------------------

    @Property(bool, notify=stateChanged)
    def loading(self): return self._loading

    @Property(bool, notify=stateChanged)
    def ready(self): return self._book is not None

    @Property(str, notify=stateChanged)
    def error(self): return self._error

    @Property(str, notify=stateChanged)
    def title(self): return os.path.splitext(os.path.basename(self._path))[0]

    @Property(str, notify=stateChanged)
    def path(self): return self._path

    @Property(int, notify=stateChanged)
    def mediaId(self): return -1 if self._media_id is None else self._media_id

    @Property(str, notify=stateChanged)
    def kind(self): return self._book.kind if self._book else ""

    @Property(int, notify=stateChanged)
    def pageCount(self): return len(self._book.refs) if self._book else 0

    @Property(str, notify=stateChanged)
    def token(self): return self._token

    @Property(list, notify=stateChanged)
    def pieces(self): return self._pieces

    @Property(int, notify=stateChanged)
    def startPage(self): return self._start_page

    @Property(float, notify=stateChanged)
    def startOffset(self): return self._start_offset

    @Property(list, notify=bookmarksChanged)
    def bookmarks(self): return list(self._bookmarks)

    @Property(list, notify=chaptersChanged)
    def chapters(self): return self._chapters

    def _neighbour(self, step: int) -> str:
        if not self._context:
            return ""
        paths = [os.path.normpath(c) for c in self._context["chapters"]]
        try:
            index = paths.index(os.path.normpath(self._path)) + step
        except ValueError:
            return ""
        return self._context["chapters"][index] if 0 <= index < len(paths) else ""

    @Property(str, notify=stateChanged)
    def nextPath(self): return self._neighbour(1)

    @Property(str, notify=stateChanged)
    def previousPath(self): return self._neighbour(-1)

    @Property(str, notify=stateChanged)
    def previousName(self): return os.path.splitext(os.path.basename(self._neighbour(-1)))[0]

    @Property(str, notify=stateChanged)
    def nextName(self): return os.path.splitext(os.path.basename(self._neighbour(1)))[0]

    # ---- layout, direction and fit: remembered per series (or per book) -----------------------------------

    def _set_setting(self, attribute: str, value: str, allowed: tuple):
        if value not in allowed or getattr(self, attribute) == value:
            return
        setattr(self, attribute, value)
        self._save_settings()
        self.settingsChanged.emit()

    def _save_settings(self):
        if self._remember and self._scope:
            reader.save_settings(self._db, self._scope, {"layout": self._layout, "direction": self._direction, "fit": self._fit})

    def _get_layout(self): return self._layout
    def _put_layout(self, value): self._set_setting("_layout", value, reader.LAYOUTS)
    layout = Property(str, _get_layout, _put_layout, notify=settingsChanged)

    def _get_direction(self): return self._direction
    def _put_direction(self, value): self._set_setting("_direction", value, reader.DIRECTIONS)
    direction = Property(str, _get_direction, _put_direction, notify=settingsChanged)

    def _get_fit(self): return self._fit
    def _put_fit(self, value): self._set_setting("_fit", value, reader.FITS)
    fit = Property(str, _get_fit, _put_fit, notify=settingsChanged)

    def _get_remember(self): return self._remember

    def _put_remember(self, value):
        value = bool(value)
        if value == self._remember:
            return
        self._remember = value
        if self._scope:
            if value:
                self._save_settings()
            else:
                reader.forget_settings(self._db, self._scope)
        self.settingsChanged.emit()
    remember = Property(bool, _get_remember, _put_remember, notify=settingsChanged)

    # ---- opening and closing --------------------------------------------------------------------------

    @Slot(str, result=bool)
    def canRead(self, location: str) -> bool:
        """Whether the reader handles this file: a comic, a PDF, or an EPUB made of page pictures
        (an EPUB of text is left to the system app)."""
        path = covers.folder_key(location)
        if not reader.is_readable(path):
            return False
        return reader.is_image_epub(path) if path.lower().endswith(".epub") else True

    @Slot(str)
    def load(self, location: str):
        """Open a book (a file path or a file:// address). Progress, bookmarks and chapters come with it."""
        self.loadFrom(location, False)

    @Slot(str, bool)
    def loadFrom(self, location: str, fromEnd: bool):
        """Like load, but with `fromEnd` the book opens on its last page, as when going back a chapter."""
        self.close()
        self._from_end = fromEnd
        self._request += 1
        self._path = covers.folder_key(location)
        self._loading = True
        self.stateChanged.emit()
        QThreadPool.globalInstance().start(_OpenJob(self._request, self._path, self._opened))

    @Slot()
    def close(self):
        """Close the open book (cancelling a load that is still running)."""
        self._request += 1                      # a load still running is now stale
        if self._token:
            _unregister(self._token)
        if self._book is not None:
            self._book.close()
        path = self._path
        self._reset()
        self._path = path
        self.stateChanged.emit()
        self.bookmarksChanged.emit()
        self.chaptersChanged.emit()

    def _on_opened(self, request: int, book, error: str):
        if request != self._request:
            if book is not None:
                book.close()
            return
        self._loading = False
        if book is None:
            self._error = error
            self.stateChanged.emit()
            return
        self._book = book
        self._token = _register(book)
        self._pieces = reader.pieces_for(book.sizes)
        real = os.path.realpath(self._path)
        found = self._db.get_media_by_path(real)
        self._media_id = found[0] if found else None
        self._context = reader.series_context(self._db, self._path)
        self._scope = reader.settings_scope(self._context, self._media_id, real)
        stored = reader.load_settings(self._db, self._scope)
        self._layout = stored.get("layout") or reader.suggest_layout(book.sizes)
        self._direction = stored.get("direction") or reader.suggest_direction(book.manga)
        self._fit = stored.get("fit") or ("width" if self._layout == "strip" else "height")
        self._remember = True
        progress = self._db.get_progress(self._media_id) if self._media_id is not None else None
        count = len(book.refs)
        # a book read to the end opens from the start again; a half-read one where it was left
        if progress and progress["finished"]:
            progress = None
        self._start_page = min(progress["page"], count - 1) if progress else 0
        self._start_offset = progress["offset"] if progress else 0.0
        if self._from_end:
            self._start_page, self._start_offset = count - 1, 1.0
        self._page, self._offset = self._start_page, self._start_offset
        self._bookmarks = self._db.get_bookmarks(self._media_id) if self._media_id is not None else []
        if self._context:                         # the series tile resumes at the chapter opened last
            self._db.set_collection_last_read(self._context["folder"], self._context["chapters"][
                [os.path.normpath(c) for c in self._context["chapters"]].index(os.path.normpath(self._path))])
        self._build_chapters()
        self.stateChanged.emit()
        self.settingsChanged.emit()
        self.bookmarksChanged.emit()

    # ---- where you are ----------------------------------------------------------------------------------

    @Slot(int, float, bool)
    def savePosition(self, page: int, offset: float, finished: bool):
        """Remember the page (and how far down it) the reader is on."""
        if self._book is None:
            return
        self._page = max(0, min(int(page), len(self._book.refs) - 1))
        self._offset = max(0.0, min(float(offset), 1.0))
        if self._media_id is not None:
            self._db.set_progress(self._media_id, self._page, self._offset, len(self._book.refs), finished)
            if finished:
                self._build_chapters()

    @Slot(int, result=list)
    def pageSize(self, page: int) -> list:
        if self._book and 0 <= page < len(self._book.sizes):
            return list(self._book.sizes[page])
        return [0, 0]

    @Slot(int, result=int)
    def firstPiece(self, page: int) -> int:
        """The index in `pieces` where a page starts."""
        for index, piece in enumerate(self._pieces):
            if piece["page"] == page:
                return index
        return 0

    @Slot(int, result=list)
    def chunksOf(self, page: int) -> list:
        """The chunks of one page, [{chunk, y0, y1, width}], for the paged layout."""
        return [p for p in self._pieces if p["page"] == page]

    # ---- bookmarks -----------------------------------------------------------------------------------------

    @Slot(int, result=bool)
    def isBookmarked(self, page: int) -> bool:
        return page in self._bookmarks

    @Slot(int)
    def toggleBookmark(self, page: int):
        """Star or unstar a page."""
        if self._media_id is None or self._book is None or not 0 <= page < len(self._book.refs):
            return
        if page in self._bookmarks:
            self._db.remove_bookmark(self._media_id, page)
        else:
            self._db.add_bookmark(self._media_id, page)
        self._bookmarks = self._db.get_bookmarks(self._media_id)
        self.bookmarksChanged.emit()

    # ---- the chapters of a series ----------------------------------------------------------------------------

    def _build_chapters(self):
        chapters = []
        if self._context:
            ids = {}
            for chapter in self._context["chapters"]:
                found = self._db.get_media_by_path(os.path.realpath(chapter))
                if found:
                    ids[chapter] = found[0]
            progress = self._db.get_progress_many(ids.values())
            for chapter in self._context["chapters"]:
                row = progress.get(ids.get(chapter))
                current = os.path.normpath(chapter) == os.path.normpath(self._path)
                state = "read" if row and row["finished"] else "current" if current else "reading" if row and row["page"] > 0 else "unread"
                chapters.append({"path": chapter, "name": os.path.splitext(os.path.basename(chapter))[0], "state": state,
                                 "page": row["page"] if row else 0, "total": row["total"] if row else 0,
                                 "isCurrent": current})
        self._chapters = chapters
        self.chaptersChanged.emit()
