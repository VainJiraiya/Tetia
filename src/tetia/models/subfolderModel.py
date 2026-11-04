# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Subfolders of the folder open in the media grid (nested collections).

A folder on disk is a collection, so nesting just mirrors the directory tree.
Only the immediate children are listed (scans stay lazy, one level per page),
and a child appears only if something inside it, at any depth, matches the
grid's current filter -- so the Manga tab never offers a "Finale movies" folder.
"""
import logging
import os
import sqlite3
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QUrl, Signal, Slot, Property
from PySide6.QtQml import QmlElement

from tetia.models import covers, series
from tetia.models.database import get_database
from tetia.models.mediaModel import (
    COMIC_EXTENSIONS, EBOOK_EXTENSIONS, IMAGE_EXTENSIONS, MANGA_TAB_EXTENSIONS,
    VIDEO_EXTENSIONS, MediaModel,
)

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

MAX_DEPTH = 8  # how far below a subfolder to look for matching files

# Extensions the grid shows for each MediaModel.FilterMode
_ALL = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | COMIC_EXTENSIONS | EBOOK_EXTENSIONS
_MODE_EXTENSIONS = {
    MediaModel.FilterMode.All: _ALL,
    MediaModel.FilterMode.ImagesOnly: IMAGE_EXTENSIONS,
    MediaModel.FilterMode.VideosOnly: VIDEO_EXTENSIONS,
    MediaModel.FilterMode.MangaOnly: MANGA_TAB_EXTENSIONS,
    MediaModel.FilterMode.BooksOnly: EBOOK_EXTENSIONS,
}
# Files the thumbnail provider can draw, for tile pictures
_PICTURE_EXTENSIONS = covers.MEDIA_EXTENSIONS | COMIC_EXTENSIONS


def _scan(directory: str):
    """(files, subdirs) of a directory as sorted lists of names; empty on error.
    Hidden entries are skipped."""
    files, dirs = [], []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        dirs.append(entry.name)
                    elif entry.is_file():
                        files.append(entry.name)
                except OSError:
                    continue
    except OSError:
        pass
    files.sort(key=covers.natural_key)
    dirs.sort(key=covers.natural_key)
    return files, dirs


def _has_match(directory: str, extensions, seen: set, depth: int = 0) -> bool:
    """Whether the directory or anything below holds a file with one of the
    extensions. `seen` (resolved paths) breaks symlink loops."""
    try:
        real = os.path.realpath(directory)
    except OSError:
        return False
    if real in seen or depth > MAX_DEPTH:
        return False
    seen.add(real)
    files, dirs = _scan(directory)
    if any(Path(name).suffix.lower() in extensions for name in files):
        return True
    return any(_has_match(os.path.join(directory, d), extensions, seen, depth + 1)
               for d in dirs)


@QmlElement
class SubfolderModel(QAbstractListModel):
    class Roles:
        PathRole = Qt.UserRole + 1
        NameRole = Qt.UserRole + 2
        HeroPathRole = Qt.UserRole + 3
        ItemCountRole = Qt.UserRole + 4
        IsFavoriteRole = Qt.UserRole + 5
        HasCustomCoverRole = Qt.UserRole + 6
        IsSeriesRole = Qt.UserRole + 7

    filterModeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._parent_dir = ""
        self._filter_mode = MediaModel.FilterMode.All
        self._dirs: list[dict] = []   # {"path", "name", "count"}
        self._meta: dict = {}
        covers.notifier.changed.connect(self._on_collection_changed)

    # ---- model ------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return len(self._dirs)

    def _is_series(self, entry: dict) -> bool:
        return bool(self._meta.get(covers.folder_key(entry["path"]), {}).get("is_series"))

    def _cover(self, entry: dict):
        cover = self._meta.get(covers.folder_key(entry["path"]), {}).get("cover_path")
        return cover if cover and os.path.exists(cover) else None

    def _hero(self, entry: dict) -> str:
        """Own cover, else a loose cover picture, else (a series) its first
        chapter, else the first matching picture inside (any depth). The same
        lookup as the Favorites tab, so both show the same picture."""
        cover = self._cover(entry) or series.loose_cover(entry["path"])
        if cover:
            return cover
        if self._is_series(entry):
            chapters = series.chapters(entry["path"])
            if chapters:
                return chapters[0]
        return covers.first_media_file(
            entry["path"], self._extensions() & _PICTURE_EXTENSIONS,
            {os.path.realpath(self._parent_dir)})

    def data(self, index, role):
        if not index.isValid() or not (0 <= index.row() < len(self._dirs)):
            return None
        entry = self._dirs[index.row()]
        if role == self.Roles.PathRole:
            return covers.folder_uri(entry["path"])
        if role == self.Roles.NameRole:
            return entry["name"]
        if role == self.Roles.HeroPathRole:
            return self._hero(entry)
        if role == self.Roles.ItemCountRole:
            return len(series.chapters(entry["path"])) if self._is_series(entry) else entry["count"]
        if role == self.Roles.IsSeriesRole:
            return self._is_series(entry)
        if role == self.Roles.IsFavoriteRole:
            return bool(self._meta.get(covers.folder_key(entry["path"]), {}).get("favorite"))
        if role == self.Roles.HasCustomCoverRole:
            return self._cover(entry) is not None
        return None

    def roleNames(self):
        return {
            self.Roles.PathRole: b"folderPath",
            self.Roles.NameRole: b"folderName",
            self.Roles.HeroPathRole: b"heroPath",
            self.Roles.ItemCountRole: b"itemCount",
            self.Roles.IsFavoriteRole: b"isFavorite",
            self.Roles.HasCustomCoverRole: b"hasCustomCover",
            self.Roles.IsSeriesRole: b"isSeries",
        }

    # ---- loading ----------------------------------------------------------

    def _extensions(self):
        return _MODE_EXTENSIONS.get(self._filter_mode, _ALL)

    @Slot(str)
    def load(self, folder: str):
        """List the subfolders of `folder` (a path or file:// URI) that hold
        something matching the current filter."""
        self._parent_dir = covers.folder_key(folder)
        self._reload()

    def _reload(self):
        extensions = self._extensions()
        found = []
        if self._parent_dir:
            _, names = _scan(self._parent_dir)
            for name in names:
                path = os.path.join(self._parent_dir, name)
                # Seeded with the parent so a symlink back up to it adds nothing
                # (deeper loops still end: the walk is depth-capped).
                if not _has_match(path, extensions, {os.path.realpath(self._parent_dir)}):
                    continue
                own_files, _ = _scan(path)
                count = sum(1 for f in own_files if Path(f).suffix.lower() in extensions)
                found.append({"path": path, "name": name, "count": count})
        try:
            meta = self._db.get_collections_meta(
                [covers.folder_key(e["path"]) for e in found])
        except sqlite3.Error as e:
            logger.error("Failed to load subfolder covers/favorites: %s", e)
            meta = {}
        self.beginResetModel()
        self._dirs = found
        self._meta = meta
        self.endResetModel()

    def _on_collection_changed(self, key: str):
        for row, entry in enumerate(self._dirs):
            if covers.folder_key(entry["path"]) != key:
                continue
            try:
                self._meta[key] = self._db.get_collection_meta(key)
            except sqlite3.Error:
                return
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [
                self.Roles.HeroPathRole,
                self.Roles.IsFavoriteRole,
                self.Roles.HasCustomCoverRole,
                self.Roles.IsSeriesRole,
                self.Roles.ItemCountRole,
            ])
            return

    # ---- favorites and covers (same slots as FolderModel) ------------------

    @Slot(str, bool)
    def setFavorite(self, folder_path: str, favorite: bool):
        key = covers.folder_key(folder_path)
        try:
            self._db.set_collection_favorite(key, favorite)
        except sqlite3.Error as e:
            logger.error("Failed to set folder favorite for %s: %s", key, e)
            return
        covers.notifier.changed.emit(key)

    @Slot(str, str, result=bool)
    def setCoverFromFile(self, folder_path: str, image_path: str) -> bool:
        return covers.set_cover_from_file(folder_path, image_path, db=self._db)

    @Slot(str, bool)
    def setSeries(self, folder_path: str, is_series: bool):
        series.set_series(self._db, folder_path, is_series)

    @Slot(str, str, result=str)
    def openSeries(self, folder_path: str, which: str) -> str:
        return series.open_series(self._db, folder_path, which)

    @Slot(str, result=bool)
    def hasCustomCover(self, folder_path: str) -> bool:
        cover = self._meta.get(covers.folder_key(folder_path), {}).get("cover_path")
        return bool(cover and os.path.exists(cover))

    @Slot(str)
    def clearCover(self, folder_path: str):
        covers.clear_cover(folder_path, db=self._db)

    # ---- filter -----------------------------------------------------------

    @Property(int, notify=filterModeChanged)
    def filterMode(self) -> int:
        return int(self._filter_mode)

    @filterMode.setter
    def filterMode(self, mode: int):
        if int(self._filter_mode) != mode:
            self._filter_mode = MediaModel.FilterMode(mode)
            self.filterModeChanged.emit()
            self._reload()
