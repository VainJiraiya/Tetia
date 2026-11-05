# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cover pictures for comics (.cbz), EPUBs and PDFs.

Nothing here needs more than Python's zipfile and Qt: images are decoded by Qt's
image reader, PDF pages by QtPdf. For a comic or PDF the first few pages are
rendered small and scored, and the first one with real content is the cover, so a
blank page, a black page or a nearly empty one is skipped. A very tall page (a
webtoon strip) is cut to a portrait piece from its top. cbr and cb7 archives need
an external tool and are not read.
"""
import logging
import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter

from tetia.models import covers
from tetia.models.metadata import _local, _read_member

logger = logging.getLogger(__name__)

PAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".jxl", ".heic")
BOOK_SUFFIXES = {".cbz", ".epub", ".pdf"}

SCAN_PAGES = 6               # how many pages are tried before settling for the best one
MAX_PAGE_BYTES = 64 * 1024 * 1024   # a page larger than this is skipped (damaged or hostile archive)

PORTRAIT = 1.4               # cover aspect: height / width
TALL = 2.5                   # a page taller than this (height / width) is a strip, not a page
WIDE = 1.2                   # a page wider than this (width / height) is a double-page spread

BLANK_BELOW = 0.015          # fraction of pixels that differ from the page's background
LOW_BELOW = 0.06
DIFFERENT = 28               # how far (0-255) a pixel must be from the background to count as ink


def is_book(path: str) -> bool:
    return Path(path).suffix.lower() in BOOK_SUFFIXES


# ---- Scoring -------------------------------------------------------------------

def content(image: QImage) -> float:
    """The fraction of the picture that differs from its own background (the median
    colour), 0 for a flat page. A white page with a little text scores a few
    percent; a black page, a white page and a single-colour page all score ~0."""
    small = image.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
    small = small.convertToFormat(QImage.Format.Format_RGB32)
    width, height = small.width(), small.height()
    if not width or not height:
        return 0.0
    data = bytes(small.constBits())
    stride = small.bytesPerLine()
    pixels = [(data[y * stride + x * 4 + 2], data[y * stride + x * 4 + 1], data[y * stride + x * 4])
              for y in range(height) for x in range(width)]
    middle = len(pixels) // 2
    background = tuple(sorted(p[c] for p in pixels)[middle] for c in range(3))
    ink = sum(1 for p in pixels if max(abs(p[c] - background[c]) for c in range(3)) > DIFFERENT)
    return ink / len(pixels)


def choose(images: list) -> int:
    """The index of the page to use as the cover (-1 if there are none): the first one
    that is not blank, nearly empty or a double-page spread; failing that the one with
    the most content; failing that the first."""
    if not images:
        return -1
    scores = [content(image) for image in images]
    wide = [image.width() > WIDE * image.height() for image in images]
    for i, score in enumerate(scores):
        if score >= LOW_BELOW and not wide[i]:
            return i
    ranked = sorted(range(len(images)), key=lambda i: scores[i] * (0.5 if wide[i] else 1.0), reverse=True)
    best = ranked[0]
    return best if scores[best] >= BLANK_BELOW else 0


# ---- Decoding ------------------------------------------------------------------------

def decode(data: bytes, edge: int) -> QImage:
    """Decode an image no bigger than `edge` pixels on its longer side. A very tall
    page keeps its top as a portrait piece of the same height. Null if unreadable."""
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    tall = False
    if size.isValid() and size.width() > 0 and size.height() > 0:
        tall = size.height() > TALL * size.width()
        if tall:
            width = max(1, round(edge / PORTRAIT))
            target = QSize(width, round(size.height() * width / size.width()))
        else:
            target = size.scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio)
        if target.width() < size.width():           # never scale up
            reader.setScaledSize(target)
    image = reader.read()
    if image.isNull():
        return image
    if tall or image.height() > TALL * image.width():
        image = image.copy(0, 0, image.width(), min(image.height(), edge))
    return image


# ---- Sources ---------------------------------------------------------------------------

def _cbz_pages(path: str, edge: int, limit: int) -> list:
    pages = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = [info for info in archive.infolist()
                     if not info.is_dir()
                     and info.filename.lower().endswith(PAGE_SUFFIXES)
                     and not info.filename.startswith("__MACOSX")
                     and not posixpath.basename(info.filename).startswith(".")]
            names.sort(key=lambda info: covers.natural_key(info.filename))
            for info in names[:limit]:
                if info.file_size > MAX_PAGE_BYTES:
                    continue
                image = decode(archive.read(info), edge)
                if not image.isNull():
                    pages.append(image)
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError, NotImplementedError) as e:
        logger.warning("Could not read the pages of %s: %s", path, e)
    return pages


def _epub_candidates(path: str) -> list:
    """Member names of pictures that could be the cover, best first."""
    with zipfile.ZipFile(path) as archive:
        container = ElementTree.fromstring(_read_member(archive, "META-INF/container.xml"))
        rootfile = next(el.get("full-path") for el in container.iter() if _local(el.tag) == "rootfile")
        opf = ElementTree.fromstring(_read_member(archive, rootfile))
        names = set(archive.namelist())
    base = posixpath.dirname(rootfile)
    manifest = {}          # id -> (member name, properties)
    cover_id = ""
    for el in opf.iter():
        tag = _local(el.tag)
        if tag == "item" and el.get("media-type", "").startswith("image/"):
            member = posixpath.normpath(posixpath.join(base, unquote(el.get("href", ""))))
            manifest[el.get("id", member)] = (member, el.get("properties", ""))
        elif tag == "meta" and el.get("name") == "cover":
            cover_id = el.get("content", "")
    ordered = [m for m, props in manifest.values() if "cover-image" in props.split()]
    if cover_id in manifest:
        ordered.append(manifest[cover_id][0])
    ordered += [m for key, (m, _) in manifest.items() if "cover" in key.lower() or "cover" in m.lower()]
    ordered += [m for m, _ in manifest.values()]
    seen, out = set(), []
    for member in ordered:
        if member in names and member not in seen:
            seen.add(member)
            out.append(member)
    return out


def _epub_pages(path: str, edge: int, limit: int) -> list:
    pages = []
    try:
        candidates = _epub_candidates(path)
        with zipfile.ZipFile(path) as archive:
            for member in candidates[:limit]:
                if archive.getinfo(member).file_size > MAX_PAGE_BYTES:
                    continue
                image = decode(archive.read(member), edge)
                if not image.isNull():
                    pages.append(image)
                    if len(pages) == 1 and content(image) >= LOW_BELOW:
                        break          # the declared cover is fine: no need to look further
    except (zipfile.BadZipFile, OSError, KeyError, StopIteration, ElementTree.ParseError,
            RuntimeError, NotImplementedError) as e:
        logger.warning("Could not read the cover of %s: %s", path, e)
    return pages


def _pdf_pages(path: str, edge: int, limit: int) -> list:
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return []
    document = QPdfDocument()
    if document.load(path) != QPdfDocument.Error.None_:
        return []
    pages = []
    try:
        for index in range(min(limit, document.pageCount())):
            points = document.pagePointSize(index)
            scale = edge / max(points.width(), points.height(), 1.0)
            size = QSize(max(1, round(points.width() * scale)), max(1, round(points.height() * scale)))
            rendered = document.render(index, size)
            if rendered.isNull():
                continue
            # pages can come out transparent; a cover is drawn on paper
            paper = QImage(rendered.size(), QImage.Format.Format_RGB32)
            paper.fill(Qt.GlobalColor.white)
            painter = QPainter(paper)
            painter.drawImage(0, 0, rendered)
            painter.end()
            pages.append(paper)
    finally:
        document.close()
    return pages


# ---- Entry point ------------------------------------------------------------------------

def make_cover(path: str, edge: int) -> QImage:
    """The cover of the comic, EPUB or PDF at `path`, no bigger than `edge` pixels
    (a null image if it cannot be read)."""
    suffix = Path(path).suffix.lower()
    source = {".cbz": _cbz_pages, ".epub": _epub_pages, ".pdf": _pdf_pages}.get(suffix)
    if source is None:
        return QImage()
    pages = source(path, edge, SCAN_PAGES)
    chosen = choose(pages)
    return pages[chosen] if chosen >= 0 else QImage()
