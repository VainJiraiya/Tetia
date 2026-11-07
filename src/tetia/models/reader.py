# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading a comic, PDF or image-only EPUB page by page: what the reader needs, with no Qt Quick.

A Book knows its pages, their sizes, and how to draw one at a given width. A page taller than
MAX_CHUNK source pixels is cut into equal chunks (webtoons that were not already cut), and the
cuts are rounded from shared boundaries, so stacked chunks meet exactly with no gap or overlap.
Pages are never merged into one big picture: that would hit the GPU's texture limit.
"""
import json
import logging
import os
import posixpath
import re
import statistics
import threading
import zipfile
from collections import OrderedDict
from urllib.parse import unquote
from xml.etree import ElementTree

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QImage, QImageReader

from tetia.models import archive, bookcovers, covers, series
from tetia.models.metadata import MAX_XML_BYTES, _local, _read_member

logger = logging.getLogger(__name__)

MAX_CHUNK = 4096          # source pixels: a taller page is cut into chunks no taller than this
STRIP_RATIO = 2.5         # a book whose pages are typically taller than 2.5 x their width is a webtoon strip
SAMPLE_PAGES = 10         # how many pages are looked at to decide that
DEFAULT_WIDTH = 1200      # how wide to draw a page when nothing says
# The page loader draws a page at the width the screen asked for, rounded UP to one of these, so zooming or resizing
# the window does not decode the whole page again for every pixel of difference (the cache is keyed by the width).
# The same list is in qml/views/readerWidth.js, which rounds before asking; a test keeps the two equal.
WIDTH_STEPS = (600, 800, 1000, 1200, 1600, 2000, 2400, 3000, 3600, 4400)
MAX_PIXELS = 36_000_000   # no page is drawn with more pixels than this (about 144 MB), however far it is zoomed


def step_width(width: int) -> int:
    """The smallest of WIDTH_STEPS that is at least `width` (the biggest one for anything wider)."""
    for step in WIDTH_STEPS:
        if width <= step:
            return step
    return WIDTH_STEPS[-1]


def within_budget(width: int, source_width: int, source_height: int) -> int:
    """`width`, made smaller if drawing the page that wide would take more than MAX_PIXELS."""
    if source_width <= 0 or source_height <= 0:
        return width
    return max(1, min(width, int((MAX_PIXELS * source_width / source_height) ** 0.5)))
READABLE_SUFFIXES = bookcovers.COMIC_SUFFIXES + (".pdf", ".epub")

LAYOUTS = ("paged", "strip")
DIRECTIONS = ("rtl", "ltr")
FITS = ("height", "width", "original")


class ReaderError(Exception):
    """The book cannot be read; str() is a sentence fit to show the user."""


# ---- Pure helpers ---------------------------------------------------------------------

def chunk_boundaries(height: int, max_chunk: int = 0) -> list:
    """The cut points [0, ..., height] that split a page into equal chunks of at most max_chunk
    (MAX_CHUNK unless given)."""
    count = max(1, -(-int(height) // (max_chunk or MAX_CHUNK)))
    return [round(i * height / count) for i in range(count + 1)]


def suggest_layout(sizes: list) -> str:
    """'strip' if the first pages are typically much taller than wide (a webtoon), else 'paged'."""
    ratios = [h / w for w, h in sizes[:SAMPLE_PAGES] if w > 0 and h > 0]
    return "strip" if ratios and statistics.median(ratios) > STRIP_RATIO else "paged"


# What kind of series a folder is. It says how the reader opens it when nothing was remembered for the series:
# a webtoon is one long strip; manga (and doujin, oneshots) read right to left; the rest left to right. The page
# shapes still decide paged or strip for the others.
FORMATS = ("manga", "manhwa", "manhua", "webtoon", "doujin", "oneshot", "artbook")
FORMAT_NAMES = {"manga": "Manga", "manhwa": "Manhwa", "manhua": "Manhua", "webtoon": "Webtoon", "doujin": "Doujin",
                "oneshot": "Oneshot", "artbook": "Artbook"}


def format_defaults(fmt: str) -> dict:
    """{layout?, direction?} a series of this format opens with (empty for no format)."""
    if fmt == "webtoon":
        return {"layout": "strip", "direction": "ltr"}
    if fmt in ("manga", "doujin", "oneshot"):
        return {"direction": "rtl"}
    if fmt in ("manhwa", "manhua", "artbook"):
        return {"direction": "ltr"}
    return {}


def suggest_direction(manga: str) -> str:
    """ComicInfo's Manga field says YesAndRightToLeft for a book read from right to left."""
    return "rtl" if (manga or "").strip().lower() == "yesandrighttoleft" else "ltr"


def is_readable(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in READABLE_SUFFIXES


def _open_reader(data: bytes):
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    return QImageReader(buffer), buffer          # the buffer must outlive the reader


def _image_size(data: bytes):
    reader, _buffer = _open_reader(data)
    size = reader.size()
    return size.width(), size.height()


# ---- Books -----------------------------------------------------------------------------

class Book:
    """The pages of one file. `refs` name them, `sizes` (source pixels) are filled in by scan_sizes()."""
    kind = ""

    def __init__(self, path: str):
        self.path = path
        self.refs = []
        self.sizes = []
        self.manga = ""                  # ComicInfo's Manga field, if the book has one
        self._lock = threading.RLock()   # archives and PDF documents are not safe to read from two threads

    def scan_sizes(self) -> list:
        raise NotImplementedError

    def render(self, index: int, width: int, chunk: int = 0) -> QImage:
        """Page `index` drawn `width` pixels wide (never enlarged), or just its chunk `chunk`. Null if unreadable."""
        raise NotImplementedError

    def close(self):
        pass


class RasterBook(Book):
    """A book whose pages are picture files."""
    CACHE_PAGES = 3          # a chunked page is decoded once, then cut for each chunk asked for

    def __init__(self, path: str):
        super().__init__(path)
        self._cache = OrderedDict()

    def read(self, ref: str) -> bytes:
        raise NotImplementedError

    def scan_sizes(self) -> list:
        sizes = []
        for ref in self.refs:
            try:
                width, height = _image_size(self.read(ref))
            except ReaderError:
                width = height = 0
            sizes.append((width, height) if width > 0 and height > 0 else (1000, 1500))   # a placeholder for a broken page
        self.sizes = sizes
        return sizes

    def render(self, index: int, width: int, chunk: int = 0) -> QImage:
        if not 0 <= index < len(self.refs):
            return QImage()
        width = max(1, int(width))
        with self._lock:
            key = (index, width)
            cached = self._cache.get(key)
            if cached is None:
                try:
                    data = self.read(self.refs[index])
                except ReaderError:
                    return QImage()
                reader, _buffer = _open_reader(data)
                size = reader.size()
                source_width, source_height = size.width(), size.height()
                width = within_budget(width, source_width, source_height)
                if source_width > 0 and width < source_width:           # draw smaller, never larger
                    reader.setScaledSize(QSize(width, max(1, round(source_height * width / source_width))))
                image = reader.read()
                if image.isNull():
                    return QImage()
                cached = (image, source_height)
                self._cache[key] = cached
                while len(self._cache) > self.CACHE_PAGES:
                    self._cache.popitem(last=False)
            else:
                self._cache.move_to_end(key)
        image, source_height = cached
        bounds = chunk_boundaries(source_height)
        if len(bounds) == 2:
            return image if chunk == 0 else QImage()
        if not 0 <= chunk < len(bounds) - 1:
            return QImage()
        cuts = [round(b * image.height() / source_height) for b in bounds]       # shared edges: no gap, no overlap
        return image.copy(0, cuts[chunk], image.width(), cuts[chunk + 1] - cuts[chunk])


class ArchiveBook(RasterBook):
    """A comic: a zip, tar, RAR or 7z of pictures (see archive.py), in natural file-name order."""
    kind = "comic"

    def __init__(self, path: str):
        super().__init__(path)
        try:
            self._archive = archive.open_archive(path)
        except archive.ArchiveError as e:
            raise ReaderError(str(e)) from e
        self.refs = self._archive.image_names()
        if not self.refs:
            self._archive.close()
            raise ReaderError("There are no pictures in this archive.")
        if isinstance(self._archive, archive.ToolArchive):
            self._archive.prefetch(self.refs)            # one unpacking for the whole book
        self.manga = self._find_manga()

    def _find_manga(self) -> str:
        info = next((n for n in self._archive.names() if n.rsplit("/", 1)[-1].lower() == "comicinfo.xml"), None)
        if not info:
            return ""
        try:
            root = ElementTree.fromstring(self._archive.read(info, MAX_XML_BYTES))
        except (archive.ArchiveError, ElementTree.ParseError):
            return ""
        return next(((el.text or "").strip() for el in root if _local(el.tag) == "Manga"), "")

    def read(self, ref: str) -> bytes:
        with self._lock:
            try:
                return self._archive.read(ref, bookcovers.MAX_PAGE_BYTES)
            except archive.ArchiveError as e:
                raise ReaderError(str(e)) from e

    def close(self):
        with self._lock:
            self._archive.close()


def epub_page_images(path: str) -> list:
    """[(picture member or None, characters of text)] for each page of an EPUB, in reading order."""
    with zipfile.ZipFile(path) as package:
        container = ElementTree.fromstring(_read_member(package, "META-INF/container.xml"))
        rootfile = next(el.get("full-path") for el in container.iter() if _local(el.tag) == "rootfile")
        opf = ElementTree.fromstring(_read_member(package, rootfile))
        names = set(package.namelist())
        base = posixpath.dirname(rootfile)
        manifest = {el.get("id"): el.get("href") for el in opf.iter()
                    if _local(el.tag) == "item" and el.get("id") and el.get("href")}
        spine = [el.get("idref") for el in opf.iter() if _local(el.tag) == "itemref"]
        pages = []
        for idref in spine:
            href = manifest.get(idref)
            document = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0]))) if href else ""
            if document not in names:
                continue
            html = _read_member(package, document).decode("utf-8", "replace")
            match = re.search(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)""", html, re.I | re.S) \
                or re.search(r"""<image\b[^>]*?\bhref\s*=\s*["']([^"']+)""", html, re.I | re.S)
            member = ""
            if match:
                member = posixpath.normpath(posixpath.join(posixpath.dirname(document), unquote(match.group(1).split("#")[0])))
            text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style)\b.*?</\1>", "", html)))
            pages.append((member if member in names else None, len(text)))
        return pages


def is_comic_epub(pages: list) -> bool:
    """Whether an EPUB is made of page pictures (a comic) and not text to be reflowed, which the reader cannot show."""
    if len(pages) < 3:
        return False
    with_picture = [p for p in pages if p[0]]
    return len(with_picture) >= 0.8 * len(pages) and statistics.median(p[1] for p in pages) <= 300


_epub_verdicts = {}


def is_image_epub(path: str) -> bool:
    """Whether an EPUB is a comic the reader can show (False for text, or a file that cannot be read).
    Remembered per file version, since opening asks it again."""
    try:
        info = os.stat(path)
        key = (path, info.st_mtime_ns, info.st_size)
    except OSError:
        return False
    if key not in _epub_verdicts:
        try:
            _epub_verdicts[key] = is_comic_epub(epub_page_images(path))
        except (zipfile.BadZipFile, OSError, KeyError, StopIteration, ElementTree.ParseError):
            _epub_verdicts[key] = False
    return _epub_verdicts[key]


class EpubBook(RasterBook):
    kind = "epub"

    def __init__(self, path: str):
        super().__init__(path)
        try:
            pages = epub_page_images(path)
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError, KeyError, StopIteration, ElementTree.ParseError) as e:
            raise ReaderError("The EPUB could not be read.") from e
        if not is_comic_epub(pages):
            self._zip.close()
            raise ReaderError("This EPUB is text, not page pictures: open it with the system app.")
        self.refs = [member for member, _ in pages if member]

    def read(self, ref: str) -> bytes:
        with self._lock:
            try:
                if self._zip.getinfo(ref).file_size > bookcovers.MAX_PAGE_BYTES:
                    raise ReaderError("A page is too large to read.")
                return self._zip.read(ref)
            except (KeyError, zipfile.BadZipFile, OSError, RuntimeError) as e:
                raise ReaderError("A page could not be read.") from e

    def close(self):
        with self._lock:
            self._zip.close()


class PdfBook(Book):
    kind = "pdf"

    def __init__(self, path: str):
        super().__init__(path)
        try:
            from PySide6.QtPdf import QPdfDocument
        except ImportError as e:
            raise ReaderError("This Qt has no PDF support.") from e
        document = QPdfDocument()
        try:
            if document.load(path) != QPdfDocument.Error.None_:
                raise ReaderError("The PDF could not be read (it may be encrypted).")
            count = document.pageCount()
            if not count:
                raise ReaderError("The PDF has no pages.")
            # point sizes, doubled so that a page is a few hundred "source pixels"; only the shape matters
            self.sizes = [(max(1, round(document.pagePointSize(i).width() * 2)),
                           max(1, round(document.pagePointSize(i).height() * 2))) for i in range(count)]
        finally:
            document.close()
        self.refs = [str(i) for i in range(count)]
        self._document = None            # opened on first use, in the thread that draws

    def scan_sizes(self) -> list:
        return self.sizes

    def render(self, index: int, width: int, chunk: int = 0) -> QImage:
        if not 0 <= index < len(self.refs) or chunk != 0:
            return QImage()
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPainter
        from PySide6.QtPdf import QPdfDocument
        with self._lock:
            if self._document is None:
                self._document = QPdfDocument()
                if self._document.load(self.path) != QPdfDocument.Error.None_:
                    self._document = None
                    return QImage()
            page_w, page_h = self.sizes[index]
            width = within_budget(max(1, int(width)), page_w, page_h)
            rendered = self._document.render(index, QSize(width, max(1, round(width * page_h / page_w))))
        if rendered.isNull():
            return QImage()
        paper = QImage(rendered.size(), QImage.Format.Format_RGB32)    # pages can come out transparent
        paper.fill(Qt.GlobalColor.white)
        painter = QPainter(paper)
        painter.drawImage(0, 0, rendered)
        painter.end()
        return paper

    def close(self):
        with self._lock:
            if self._document is not None:
                self._document.close()
                self._document = None


def open_book(path: str) -> Book:
    """Open the comic, PDF or image-only EPUB at `path` (ReaderError, with a sentence for the user, if not)."""
    suffix = os.path.splitext(path)[1].lower()
    if suffix in bookcovers.COMIC_SUFFIXES:
        return ArchiveBook(path)
    if suffix == ".pdf":
        return PdfBook(path)
    if suffix == ".epub":
        return EpubBook(path)
    raise ReaderError("The reader does not open this kind of file.")


def pieces_for(sizes: list) -> list:
    """What the strip stacks: one entry per chunk of every page,
    [{page, chunk, width, y0, y1}] with y0 and y1 the chunk's source rows."""
    pieces = []
    for page, (width, height) in enumerate(sizes):
        bounds = chunk_boundaries(height)
        for chunk in range(len(bounds) - 1):
            pieces.append({"page": page, "chunk": chunk, "width": width, "y0": bounds[chunk], "y1": bounds[chunk + 1]})
    return pieces


# ---- Series, remembered settings --------------------------------------------------------

def series_context(db, path: str):
    """{'folder', 'chapters'} if the file is a chapter of a folder shown as a series, else None."""
    folder = covers.folder_key(os.path.dirname(path))
    try:
        if not db.get_collection_meta(folder)["is_series"]:
            return None
    except Exception:       # noqa: BLE001 - a database hiccup must not stop a book from opening
        return None
    chapters = series.chapters(folder)
    normal = os.path.normpath(path)
    return {"folder": folder, "chapters": chapters} if normal in [os.path.normpath(c) for c in chapters] else None


def settings_scope(context, media_id, path: str) -> str:
    """What the layout, direction and fit are remembered for: the whole series, or just this book."""
    if context:
        return "series:" + context["folder"]
    return f"media:{media_id}" if media_id is not None else "path:" + path


def load_settings(db, scope: str) -> dict:
    try:
        stored = json.loads(db.get_setting("reader:" + scope, "") or "{}")
    except (ValueError, TypeError):
        return {}
    return {k: v for k, v in stored.items()
            if (k == "layout" and v in LAYOUTS) or (k == "direction" and v in DIRECTIONS) or (k == "fit" and v in FITS)}


def save_settings(db, scope: str, settings: dict):
    db.set_setting("reader:" + scope, json.dumps({k: settings[k] for k in ("layout", "direction", "fit") if k in settings}))


def forget_settings(db, scope: str):
    db.delete_setting("reader:" + scope)
