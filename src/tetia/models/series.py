# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Folders shown as one series.

A lot of manga is downloaded as a folder named after the title, holding one
.cbz per chapter. Marking such a folder as a series shows it as a single tile
(one cover, one count) that opens the right chapter, instead of as a folder of
files. Plain functions with no Qt, so they are easy to test.
"""
import logging
import os
import re
import sqlite3
from pathlib import Path

from PySide6.QtCore import QUrl

from tetia.models import covers
from tetia.models.scanner import EBOOK_EXTENSIONS, MANGA_TAB_EXTENSIONS, VIDEO_EXTENSIONS

# A loose picture with one of these names (any common image extension) is the
# folder's cover; checked in this order.
LOOSE_COVER_NAMES = ("cover", "folder", "poster", "thumb", "front", "a1")
_COVER_EXTENSIONS = (covers.IMAGE_EXTENSIONS - {".ico", ".svg"})

FIRST, RESUME, NEXT, PREVIOUS = "first", "resume", "next", "previous"

logger = logging.getLogger(__name__)

# "Vol.2", "Volume 2", "Ch.21.1", "Chapter 7". Not preceded by a letter, so the
# "_Vol.1" that scanlation tools append to the group name still counts, but the
# "och" of "Epoch 5" does not.
_VOLUME = re.compile(r"(?<![a-z])vol(?:ume)?\.?\s*(\d+(?:\.\d+)*)", re.IGNORECASE)
_CHAPTER = re.compile(r"(?<![a-z])ch(?:apter)?\.?\s*(\d+(?:\.\d+)*)", re.IGNORECASE)


def _number(pattern, text: str) -> tuple:
    """The first number after the keyword as a tuple, so 21.1 is (21, 1) and
    21.10 sorts after 21.9 ("21" < "21.1" < "21.2"); () if there is none."""
    match = pattern.search(text)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def sort_chapter_names(names: list[str]) -> list[str]:
    """File names of one title's chapters, oldest chapter first.

    Downloaded chapters are named like "Group_Vol.2 Ch.21.1_a1b2c3.cbz", where
    several groups translated different stretches, so a plain natural sort
    puts all of one group's chapters before another's. Chapters are numbered
    through the whole title, so order by chapter number (a decimal such as
    16.5 is an extra after 16), with the volume and then the natural name
    breaking ties. If not every name has a chapter number, order by volume
    when every name has one, and otherwise by natural name."""
    stems = {name: Path(name).stem for name in names}
    chapters_ = {name: _number(_CHAPTER, stems[name]) for name in names}
    volumes = {name: _number(_VOLUME, stems[name]) for name in names}
    if names and all(chapters_.values()):
        return sorted(names, key=lambda n: (chapters_[n], volumes[n], covers.natural_key(n)))
    if names and all(volumes.values()):
        return sorted(names, key=lambda n: (volumes[n], chapters_[n], covers.natural_key(n)))
    return sorted(names, key=covers.natural_key)


def chapters(folder: str) -> list[str]:
    """The chapter files directly inside `folder`, in reading order (see
    sort_chapter_names)."""
    try:
        names = [e for e in os.listdir(folder)
                 if not e.startswith(".")
                 and Path(e).suffix.lower() in MANGA_TAB_EXTENSIONS
                 and os.path.isfile(os.path.join(folder, e))]
    except OSError:
        return []
    return [os.path.join(folder, n) for n in sort_chapter_names(names)]


def loose_cover(folder: str) -> str:
    """A picture lying in `folder` named cover, folder, poster, thumb, front or A1
    ('' if there is none)."""
    try:
        entries = os.listdir(folder)
    except OSError:
        return ""
    found = {}
    for entry in entries:
        stem, suffix = os.path.splitext(entry)
        if suffix.lower() in _COVER_EXTENSIONS and os.path.isfile(os.path.join(folder, entry)):
            found.setdefault(stem.casefold(), []).append(entry)
    for name in LOOSE_COVER_NAMES:
        if name in found:
            return os.path.join(folder, min(found[name], key=covers.natural_key))
    return ""


# Categories whose one-file folders are shown as the file itself. Photos are left out:
# a photo opens in Tetia's own viewer, which works on a whole folder of pictures.
FLATTEN_CATEGORIES = ("manga", "books", "videos")
# For a folder met outside any one tab (the Favorites tab): a file of any of those kinds
FLATTEN_EXTENSIONS = MANGA_TAB_EXTENSIONS | EBOOK_EXTENSIONS | VIDEO_EXTENSIONS


def single_file(directory: str, extensions) -> str:
    """The one file of a folder that holds exactly one file the tab lists and no
    subfolders ('' if it holds none, several, or any subfolder). Hidden files and
    files of other kinds (a .txt, a cover picture, subtitles) are not counted."""
    try:
        entries = [e for e in os.listdir(directory) if not e.startswith(".")]
    except OSError:
        return ""
    found = ""
    for entry in entries:
        full_path = os.path.join(directory, entry)
        if os.path.isdir(full_path):
            return ""
        if Path(entry).suffix.lower() in extensions and os.path.isfile(full_path):
            if found:
                return ""
            found = full_path
    return found


def open_single_file(folder: str, extensions) -> str:
    """The file:// URI of the one file in `folder` ('' if it is not a one-file folder)."""
    path = single_file(covers.folder_key(folder), extensions)
    return QUrl.fromLocalFile(path).toString(QUrl.FullyEncoded) if path else ""


def chapter_to_open(folder: str, last_read: str, which: str = RESUME) -> str:
    """The chapter a series tile should open, or '' if the folder has none.

    first:  the first chapter.
    resume: the chapter opened last time, else the first.
    next:   the one after the chapter opened last time (the last chapter stays
            put), else the first.
    previous: the one before it (the first chapter stays put), else the first."""
    files = chapters(folder)
    if not files:
        return ""
    if which == FIRST or last_read not in files:
        return files[0]
    if which == NEXT:
        return files[min(files.index(last_read) + 1, len(files) - 1)]
    if which == PREVIOUS:
        return files[max(files.index(last_read) - 1, 0)]
    return last_read


def set_series(db, folder: str, is_series: bool):
    """Show `folder` as one series tile (or as a folder again), and tell every
    model that shows it."""
    key = covers.folder_key(folder)
    try:
        db.set_collection_series(key, is_series)
    except sqlite3.Error as e:
        logger.error("Failed to set series for %s: %s", key, e)
        return
    covers.notifier.changed.emit(key)


def open_series(db, folder: str, which: str) -> str:
    """The file:// URI of the chapter a series tile should open ('' if the
    folder has no chapter files), remembered as the last one read."""
    key = covers.folder_key(folder)
    chapter = chapter_to_open(key, db.get_collection_meta(key)["last_read"] or "", which)
    if not chapter:
        return ""
    try:
        db.set_collection_last_read(key, chapter)
    except sqlite3.Error as e:
        logger.error("Failed to remember the chapter for %s: %s", key, e)
    return QUrl.fromLocalFile(chapter).toString(QUrl.FullyEncoded)


def direct_target(db, folder: str) -> str:
    """The file:// URI a tile for `folder` opens instead of the folder, for a place that
    knows no tab (the Favorites tab): the chapter to resume if it is a series, else the one
    file of a one-file folder, else '' (it opens as a folder)."""
    key = covers.folder_key(folder)
    if db.get_collection_meta(key)["is_series"]:
        uri = open_series(db, key, RESUME)
        if uri:
            return uri
    return open_single_file(key, FLATTEN_EXTENSIONS)


def opens_directly(db, folder: str) -> bool:
    """Whether direct_target would open a file (without remembering anything)."""
    key = covers.folder_key(folder)
    if db.get_collection_meta(key)["is_series"] and chapters(key):
        return True
    return bool(single_file(key, FLATTEN_EXTENSIONS))
