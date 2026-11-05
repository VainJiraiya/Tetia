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

from tetia.models import covers, series, virtualfolders
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
_PICTURE_EXTENSIONS = covers.ANY_PICTURE_EXTENSIONS


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


def _has_match(directory: str, extensions, seen: set, depth: int = 0, placed=None) -> bool:
    """Whether the directory or anything below holds a file with one of the
    extensions. `seen` (resolved paths) breaks symlink loops. `placed` is what the virtual folders
    have taken away: (the real paths of placed files, the keys of placed folders), which do not count."""
    try:
        real = os.path.realpath(directory)
    except OSError:
        return False
    if real in seen or depth > MAX_DEPTH:
        return False
    seen.add(real)
    placed_files, placed_folders = placed if placed else (frozenset(), frozenset())
    files, dirs = _scan(directory)
    for name in files:
        if Path(name).suffix.lower() in extensions and not (
                placed_files and os.path.realpath(os.path.join(directory, name)) in placed_files):
            return True
    return any(_has_match(os.path.join(directory, d), extensions, seen, depth + 1, placed)
               for d in dirs if covers.folder_key(os.path.join(directory, d)) not in placed_folders)


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
        SingleFileRole = Qt.UserRole + 8
        IsVirtualRole = Qt.UserRole + 9
        VirtualIdRole = Qt.UserRole + 10

    filterModeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._parent_dir = ""
        self._virtual_id = -1           # >= 0: the tiles of that virtual folder, not of a real one
        self._filter_mode = MediaModel.FilterMode.All
        self._dirs: list[dict] = []   # {"path", "name", "count"}
        self._meta: dict = {}
        covers.notifier.changed.connect(self._on_collection_changed)

    # ---- model ------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return len(self._dirs)

    # The tabs whose one-file folders are shown as the file (see series.FLATTEN_CATEGORIES)
    _FLATTEN_MODES = (MediaModel.FilterMode.MangaOnly, MediaModel.FilterMode.BooksOnly,
                      MediaModel.FilterMode.VideosOnly)

    def _single_file(self, entry: dict) -> str:
        if entry.get("virtual") is not None:
            return ""
        if self._filter_mode not in self._FLATTEN_MODES or self._is_series(entry):
            return ""
        return series.single_file(entry["path"], self._extensions())

    @Slot(str, result=str)
    def openSingleFile(self, folder_path: str) -> str:
        if self._filter_mode not in self._FLATTEN_MODES:
            return ""
        return series.open_single_file(folder_path, self._extensions())

    def _is_series(self, entry: dict) -> bool:
        if entry.get("virtual") is not None:
            return False
        return bool(self._meta.get(covers.folder_key(entry["path"]), {}).get("is_series"))

    def _cover(self, entry: dict):
        if entry.get("virtual") is not None:
            return entry.get("cover")
        cover = self._meta.get(covers.folder_key(entry["path"]), {}).get("cover_path")
        return cover if cover and os.path.exists(cover) else None

    def _hero(self, entry: dict) -> str:
        """The picture on the tile: the same lookup as the Favorites tab and the
        collections grid (see covers.tile_picture), limited to what this tab lists."""
        if entry.get("virtual") is not None:
            return entry.get("hero", "")

        def meta_for(path):
            key = covers.folder_key(path)
            return self._meta.get(key) or self._db.get_collection_meta(key)

        return covers.tile_picture(entry["path"], self._extensions() & _PICTURE_EXTENSIONS, meta_for,
                                   {os.path.realpath(self._parent_dir)} if self._parent_dir else set())

    def data(self, index, role):
        if not index.isValid() or not (0 <= index.row() < len(self._dirs)):
            return None
        entry = self._dirs[index.row()]
        virtual = entry.get("virtual")
        if role == self.Roles.IsVirtualRole:
            return virtual is not None
        if role == self.Roles.VirtualIdRole:
            return virtual if virtual is not None else -1
        if role == self.Roles.PathRole:
            return "virtual:%d" % virtual if virtual is not None else covers.folder_uri(entry["path"])
        if role == self.Roles.NameRole:
            return entry["name"]
        if role == self.Roles.HeroPathRole:
            return self._hero(entry)
        if role == self.Roles.ItemCountRole:
            return len(series.chapters(entry["path"])) if self._is_series(entry) else entry["count"]
        if role == self.Roles.IsSeriesRole:
            return self._is_series(entry)
        if role == self.Roles.SingleFileRole:
            return self._single_file(entry)
        if role == self.Roles.IsFavoriteRole:
            if virtual is not None:
                return False
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
            self.Roles.SingleFileRole: b"singleFile",
            self.Roles.IsVirtualRole: b"isVirtual",
            self.Roles.VirtualIdRole: b"virtualId",
        }

    # ---- loading ----------------------------------------------------------

    def _extensions(self):
        return _MODE_EXTENSIONS.get(self._filter_mode, _ALL)

    @Slot(str)
    def load(self, folder: str):
        """List the subfolders of `folder` (a path or file:// URI) that hold
        something matching the current filter, and the virtual folders made in it."""
        self._parent_dir = covers.folder_key(folder)
        self._virtual_id = -1
        self._reload()

    @Slot(int)
    def loadVirtual(self, vfolder_id: int):
        """List the tiles inside a virtual folder: the virtual folders in it and the real folders placed in it."""
        self._parent_dir = ""
        self._virtual_id = int(vfolder_id)
        self._reload()

    # ---- the tiles of a virtual folder ----------------------------------------------------------------

    def _virtual_entry(self, row: dict, extensions) -> dict | None:
        """The tile of one virtual folder, or None when this tab's filter finds nothing in it.
        A folder with nothing in it at all shows in every tab (it has to be there to be filled)."""
        vid = row["id"]
        files = virtualfolders.subtree_media(self._db, vid)
        folders = virtualfolders.subtree_folders(self._db, vid)
        matching = [f for f in files if Path(f["path"]).suffix.lower() in extensions]
        if (files or folders) and not matching and not any(
                _has_match(path, extensions, set()) for path in folders):
            return None
        hero = ""
        cover = None
        if row["cover_media_id"] is not None:
            info = self._db.get_media_info(row["cover_media_id"])
            if info and os.path.exists(info["path"]):
                cover = hero = info["path"]
        if not hero:
            usable = sorted((f for f in matching if Path(f["path"]).suffix.lower() in covers.ANY_PICTURE_EXTENSIONS),
                            key=lambda f: covers.natural_key(os.path.basename(f["path"])))
            if usable:
                hero = usable[0]["path"]
            else:
                for path in folders:
                    hero = covers.tile_picture(path, extensions & _PICTURE_EXTENSIONS,
                                               lambda p: self._db.get_collection_meta(covers.folder_key(p)), set())
                    if hero:
                        break
        return {"virtual": vid, "path": "virtual:%d" % vid, "name": row["name"], "count": len(matching),
                "hero": hero, "cover": cover}

    def _folder_entry(self, path: str, extensions, placed) -> dict | None:
        """The tile of a real subfolder (None if nothing matching is left in it)."""
        if not _has_match(path, extensions, {os.path.realpath(self._parent_dir or path)}, placed=placed):
            if not virtualfolders.has_roots_under(self._db, path):
                return None
        own_files, _ = _scan(path)
        placed_files = placed[0] if placed else frozenset()
        count = sum(1 for f in own_files if Path(f).suffix.lower() in extensions
                    and not (placed_files and os.path.realpath(os.path.join(path, f)) in placed_files))
        return {"path": path, "name": os.path.basename(path), "count": count}

    def _reload(self):
        extensions = self._extensions()
        found = []
        try:
            if self._virtual_id >= 0:
                found = self._entries_in_virtual(extensions)
            elif self._parent_dir:
                found = self._entries_in_folder(extensions)
        except sqlite3.Error as e:
            logger.error("Failed to list the tiles: %s", e)
        try:
            meta = self._db.get_collections_meta(
                [covers.folder_key(e["path"]) for e in found if e.get("virtual") is None])
        except sqlite3.Error as e:
            logger.error("Failed to load subfolder covers/favorites: %s", e)
            meta = {}
        self.beginResetModel()
        self._dirs = found
        self._meta = meta
        self.endResetModel()

    def _entries_in_folder(self, extensions) -> list:
        placed_folders = virtualfolders.placed_folder_keys(self._db)
        placed = (virtualfolders.placed_paths_under(self._db, self._parent_dir), placed_folders)
        found = []
        _, names = _scan(self._parent_dir)
        for name in names:
            path = os.path.join(self._parent_dir, name)
            if covers.folder_key(path) in placed_folders:
                continue                       # it was put in a virtual folder
            # Seeded with the parent so a symlink back up to it adds nothing
            # (deeper loops still end: the walk is depth-capped).
            entry = self._folder_entry(path, extensions, placed)
            if entry:
                found.append(entry)
        for row in virtualfolders.roots_at(self._db, self._parent_dir):
            entry = self._virtual_entry(row, extensions)
            if entry:
                found.append(entry)
        found.sort(key=lambda e: covers.natural_key(e["name"]))
        return found

    def _entries_in_virtual(self, extensions) -> list:
        found = []
        placed = (set(), virtualfolders.placed_folder_keys(self._db))
        for key in virtualfolders.member_folders(self._db, self._virtual_id):
            if not os.path.isdir(key) or not _has_match(key, extensions, set()):
                continue
            own_files, _ = _scan(key)
            found.append({"path": key, "name": os.path.basename(key),
                          "count": sum(1 for f in own_files if Path(f).suffix.lower() in extensions)})
        for row in virtualfolders.children_of(self._db, self._virtual_id):
            entry = self._virtual_entry(row, extensions)
            if entry:
                found.append(entry)
        found.sort(key=lambda e: covers.natural_key(e["name"]))
        return found

    def _on_collection_changed(self, key: str):
        for row, entry in enumerate(self._dirs):
            if entry.get("virtual") is not None:
                continue
            own = covers.folder_key(entry["path"])
            if key == own:
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
            elif key.startswith(own + os.sep):
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [self.Roles.HeroPathRole])

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
