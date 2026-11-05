# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pages of a comic, EPUB or PDF, for choosing a cover by hand.

Pages are read straight out of the archive into memory; nothing is unpacked to disk.
A page is named by a `ref`: the member name inside a .cbz or EPUB, the page number
in a PDF. cbr, cb7 and cbt are not opened (they need an external tool).
"""
import logging
import posixpath
import threading
import uuid
import zipfile
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from tetia.models import bookcovers, covers

logger = logging.getLogger(__name__)

PAGE_LIMIT = 150           # how many pages the picker offers (the cover is near the front)
GRID_EDGE = 220            # size of a page in the picker's grid
CHOSEN_EDGE = 1024         # the picked page is kept at most this big


def list_pages(path: str):
    """([refs], message): the pages that can be offered, and why there are none ('' if there are)."""
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".cbz":
            if not zipfile.is_zipfile(path):
                return [], "This archive cannot be opened."
            with zipfile.ZipFile(path) as archive:
                names = [i.filename for i in archive.infolist()
                         if not i.is_dir() and i.filename.lower().endswith(bookcovers.PAGE_SUFFIXES)
                         and not i.filename.startswith("__MACOSX")
                         and not posixpath.basename(i.filename).startswith(".")]
            names.sort(key=covers.natural_key)
            return names[:PAGE_LIMIT], "" if names else "There are no pictures in this archive."
        if suffix == ".epub":
            refs = bookcovers._epub_candidates(path)[:PAGE_LIMIT]
            return refs, "" if refs else "There are no pictures in this book."
        if suffix == ".pdf":
            from PySide6.QtPdf import QPdfDocument
            document = QPdfDocument()
            try:
                if document.load(path) != QPdfDocument.Error.None_:
                    return [], "The PDF could not be read."
                count = document.pageCount()
            finally:
                document.close()
            return [str(i) for i in range(min(count, PAGE_LIMIT))], "" if count else "The PDF has no pages."
    except (zipfile.BadZipFile, OSError, KeyError, StopIteration, ImportError, RuntimeError) as e:
        logger.warning("Could not list the pages of %s: %s", path, e)
        return [], "The file could not be read."
    return [], "Choosing a cover page works for .cbz, EPUB and PDF files."


def read_page(path: str, ref: str, edge: int) -> QImage:
    """One page, no bigger than `edge` pixels on its longer side (null if it cannot be read)."""
    suffix = Path(path).suffix.lower()
    try:
        if suffix in (".cbz", ".epub"):
            with zipfile.ZipFile(path) as archive:
                if archive.getinfo(ref).file_size > bookcovers.MAX_PAGE_BYTES:
                    return QImage()
                return bookcovers.decode(archive.read(ref), edge)
        if suffix == ".pdf":
            pages = bookcovers._pdf_pages_at(path, [int(ref)], edge)
            return pages[0] if pages else QImage()
    except (zipfile.BadZipFile, OSError, KeyError, ValueError, RuntimeError) as e:
        logger.warning("Could not read page %s of %s: %s", ref, path, e)
    return QImage()


# ---- The picker's grid asks for pages through an image provider ----------------------

_open_books = {}            # token -> (path, refs)
_lock = threading.Lock()


def register(path: str, refs: list) -> str:
    """Make a book's pages available to the image provider; returns the token to use in the URL."""
    token = uuid.uuid4().hex[:12]
    with _lock:
        _open_books[token] = (path, list(refs))
    return token


def unregister(token: str):
    with _lock:
        _open_books.pop(token, None)


class BookPageProvider(QQuickImageProvider):
    """image://bookpage/<token>/<index>: one page of the book being picked from."""

    def __init__(self):
        super().__init__(QQuickImageProvider.Image)

    def requestImage(self, id_string: str, requested_size: QSize, size: QSize):
        token, _, index = id_string.partition("/")
        with _lock:
            entry = _open_books.get(token)
        image = QImage()
        if entry and index.isdigit() and int(index) < len(entry[1]):
            image = read_page(entry[0], entry[1][int(index)], GRID_EDGE)
        if not image.isNull():
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image
