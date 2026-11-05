# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os

import sqlite3
from PySide6.QtCore import (QAbstractListModel, QModelIndex, Property, QUrl, Qt,
                            Signal, Slot)
from PySide6.QtQml import QmlElement

from tetia.models import covers, series
from tetia.models.database import get_database

logger = logging.getLogger(__name__)


QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

# Section order and titles on the Favorites tab: (media.kind, heading)
SECTIONS = (
    ("ebook", "Books"),
    ("comic", "Manga"),
    ("image", "Images"),
    ("video", "Videos"),
)
_ORDER = {kind: i for i, (kind, _) in enumerate(SECTIONS)}


@QmlElement
class FavoritesModel(QAbstractListModel):
    """Every favorited item, grouped by type, plus favorited folders.

    Used two ways:
    - as a plain list model (set `kind` to e.g. "image" to filter), with the
      same roles MediaModel exposes, so ImageViewer can page through just the
      favorited images. It also has the rating/favorite slots TagPanel calls
      on its model.
    - layoutRows(columns) returns the whole Favorites tab as section headers
      and rows of tiles, ready for a ListView. Favorited folders ("collections")
      come first as their own section; they are not part of the list model.
    """

    MediaIdRole = Qt.UserRole + 1   # same value MediaModel uses for mediaId
    FileUriRole = Qt.UserRole + 2
    FileNameRole = Qt.UserRole + 3
    KindRole = Qt.UserRole + 4
    IsVideoRole = Qt.UserRole + 5
    IsComicRole = Qt.UserRole + 6
    IsBookRole = Qt.UserRole + 7
    RatingRole = Qt.UserRole + 8

    kindChanged = Signal()
    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._kind = ""
        self._all = []    # every favorite, in section order
        self._rows = []   # `_all` filtered by kind
        self._collections = []   # favorited folders: key, name, hero, uri
        self._load()

    # ---- data ------------------------------------------------------------

    def _load(self):
        try:
            rows = self._db.get_favorites()
        except sqlite3.Error as e:
            logger.error("Failed to load favorites: %s", e)
            rows = []
        # Stable sort keeps the name order the query already gave within a kind
        self._all = sorted(rows, key=lambda r: _ORDER.get(r["kind"], 99))
        self._apply_filter()
        self._load_collections()

    def _load_collections(self):
        """Favorited folders that still exist and are still in the library
        (a library folder, or anything inside one)."""
        try:
            rows = self._db.get_favorite_collections()
            roots = [covers.folder_key(p) for p in self._db.get_all_folders()]
        except sqlite3.Error as e:
            logger.error("Failed to load favorite folders: %s", e)
            rows, roots = [], []
        out = []
        for row in rows:
            key = row["path"]
            if not os.path.isdir(key):
                continue
            if not any(key == r or key.startswith(r.rstrip(os.sep) + os.sep) for r in roots):
                continue
            out.append({
                "key": key,
                "name": os.path.basename(key) or key,
                "hero": covers.hero_path(key, row["cover_path"], bool(row["is_series"])),
                "uri": covers.folder_uri(key),
                # a series, or a folder holding one file, opens that file instead of the folder
                "opensFile": series.opens_directly(self._db, key),
            })
        out.sort(key=lambda c: c["name"].lower())
        self._collections = out

    @Slot(str, result=str)
    def openCollection(self, folder_uri: str) -> str:
        """The URI of the file a favorited folder's tile opens (the chapter to resume for a
        series, the only file of a one-file folder), or '' when it opens as a folder."""
        return series.direct_target(self._db, folder_uri)

    def _apply_filter(self):
        self._rows = [r for r in self._all if not self._kind or r["kind"] == self._kind]

    @staticmethod
    def _uri(path: str) -> str:
        # Fully percent-encoded: a bare '#' or '?' in a file name would
        # otherwise be read as the start of a fragment/query and cut the id short.
        return QUrl.fromLocalFile(path).toString(QUrl.FullyEncoded)

    # ---- QAbstractListModel ---------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self):
        return {
            self.MediaIdRole: b"mediaId",
            self.FileUriRole: b"fileUri",
            self.FileNameRole: b"fileName",
            self.KindRole: b"kind",
            self.IsVideoRole: b"isVideo",
            self.IsComicRole: b"isComic",
            self.IsBookRole: b"isBook",
            self.RatingRole: b"rating",
        }

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.MediaIdRole:
            return row["id"]
        if role == self.FileUriRole:
            return self._uri(row["path"])
        if role in (self.FileNameRole, Qt.DisplayRole):
            return row["name"]
        if role == self.KindRole:
            return row["kind"]
        if role == self.IsVideoRole:
            return row["kind"] == "video"
        if role == self.IsComicRole:
            return row["kind"] == "comic"
        if role == self.IsBookRole:
            return row["kind"] == "ebook"
        if role == self.RatingRole:
            return -1 if row["rating"] is None else row["rating"]
        return None

    # ---- properties ------------------------------------------------------

    @Property(str, notify=kindChanged)
    def kind(self):
        return self._kind

    @kind.setter
    def kind(self, value):
        if value == self._kind:
            return
        self.beginResetModel()
        self._kind = value
        self._apply_filter()
        self.endResetModel()
        self.kindChanged.emit()
        self.countChanged.emit()

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._rows)

    @Property(int, notify=countChanged)
    def collectionCount(self):
        return len(self._collections)

    # ---- slots -----------------------------------------------------------

    @Slot()
    def reload(self):
        """Re-read the favorites from the database."""
        self.beginResetModel()
        self._load()
        self.endResetModel()
        self.countChanged.emit()

    @Slot(int, result=bool)
    def removeFavorite(self, media_id: int) -> bool:
        """Un-favorite an item and drop it from the list."""
        try:
            self._db.set_media_favorite(media_id, False)
        except sqlite3.Error as e:
            logger.error("Failed to remove favorite %d: %s", media_id, e)
            return False
        self._all = [r for r in self._all if r["id"] != media_id]
        for i, row in enumerate(self._rows):
            if row["id"] == media_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._rows[i]
                self.endRemoveRows()
                self.countChanged.emit()
                break
        return True

    @Slot(str)
    def removeCollectionFavorite(self, folder_path: str):
        """Un-favorite a folder (a file:// URI or plain path) and drop it."""
        key = covers.folder_key(folder_path)
        try:
            self._db.set_collection_favorite(key, False)
        except sqlite3.Error as e:
            logger.error("Failed to un-favorite folder %s: %s", key, e)
            return
        self._collections = [c for c in self._collections if c["key"] != key]
        covers.notifier.changed.emit(key)
        self.countChanged.emit()

    @Slot(int, result=list)
    def layoutRows(self, columns: int) -> list:
        """The Favorites tab, flattened for a ListView: for each non-empty
        section a header row, then rows of up to `columns` tiles.

            {"type": "header", "kind", "title", "count"}
            {"type": "tiles", "kind", "items": [{"mediaId", "fileUri",
                                                 "fileName", "kind", "kindIndex"}]}

        `kindIndex` is the item's position among favorites of its kind, which
        for images is its index in a FavoritesModel with kind "image".

        Favorited folders come first, as a "collection" section. Their tiles
        carry `folderUri` (file:// URI, to open the folder), `mediaId` -1, and
        `fileUri` is the cover picture's path ("" if the folder has none).
        """
        columns = max(1, int(columns))
        out = []
        if self._collections:
            out.append({"type": "header", "kind": "collection", "title": "Collections",
                        "count": len(self._collections)})
            tiles = [{
                "mediaId": -1,
                "fileUri": c["hero"],
                "fileName": c["name"],
                "kind": "collection",
                "kindIndex": i,
                "folderUri": c["uri"],
                "opensFile": c["opensFile"],
            } for i, c in enumerate(self._collections)]
            for start in range(0, len(tiles), columns):
                out.append({"type": "tiles", "kind": "collection", "items": tiles[start:start + columns]})
        for kind, title in SECTIONS:
            items = [r for r in self._all if r["kind"] == kind]
            if not items:
                continue
            out.append({"type": "header", "kind": kind, "title": title, "count": len(items)})
            tiles = [{
                "mediaId": r["id"],
                "fileUri": self._uri(r["path"]),
                "fileName": r["name"],
                "kind": kind,
                "kindIndex": i,
            } for i, r in enumerate(items)]
            for start in range(0, len(tiles), columns):
                out.append({"type": "tiles", "kind": kind, "items": tiles[start:start + columns]})
        return out

    # The next four are what TagPanel calls on the viewer's model.

    @Slot(int, result=int)
    def getRating(self, media_id: int) -> int:
        rating = self._db.get_media_rating(media_id)
        return -1 if rating is None else rating

    @Slot(int, int)
    def setRating(self, media_id: int, rating: int):
        try:
            self._db.set_media_rating(media_id, rating)
        except (sqlite3.Error, ValueError) as e:
            logger.error("Failed to set rating for %d: %s", media_id, e)

    @Slot(int, result=bool)
    def getFavorite(self, media_id: int) -> bool:
        return bool(self._db.get_media_favorite(media_id))

    @Slot(int, bool)
    def setFavorite(self, media_id: int, favorite: bool):
        # Deliberately doesn't remove the row: a viewer paging through this
        # model must not shift under the user. The Favorites tab reloads when
        # it is shown again.
        try:
            self._db.set_media_favorite(media_id, favorite)
        except sqlite3.Error as e:
            logger.error("Failed to set favorite for %d: %s", media_id, e)
