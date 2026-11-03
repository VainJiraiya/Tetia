import logging
import os
import sqlite3
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QUrl, Signal, Slot, Property
from PySide6.QtQml import QmlElement

from tetia.models import covers
from tetia.models.covers import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from tetia.models.database import Database

logger = logging.getLogger(__name__)

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


@QmlElement
class FolderModel(QAbstractListModel):
    class Roles:
        PathRole = Qt.UserRole + 1
        NameRole = Qt.UserRole + 2
        CategoryRole = Qt.UserRole + 3
        HeroPathRole = Qt.UserRole + 4
        ItemCountRole = Qt.UserRole + 5
        IsFavoriteRole = Qt.UserRole + 6
        HasCustomCoverRole = Qt.UserRole + 7

    categoryChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database()
        self._current_category = "photos"
        self._folders = []
        # folder key -> {"cover_path", "favorite"}; reloaded on refresh and
        # patched when a cover/favorite changes anywhere (covers.notifier)
        self._meta = {}
        covers.notifier.changed.connect(self._on_collection_changed)
        self.refresh()

    def rowCount(self, parent=QModelIndex()):
        return len(self._folders)

    def _meta_for(self, folder: dict) -> dict:
        return self._meta.get(covers.folder_key(folder["path"]), {})

    def data(self, index, role):
        if not index.isValid() or not (0 <= index.row() < len(self._folders)):
            return None

        folder = self._folders[index.row()]
        if role == self.Roles.PathRole:
            return folder["path"]
        elif role == self.Roles.NameRole:
            return folder["path"].rstrip("/").split("/")[-1] or folder["path"]
        elif role == self.Roles.CategoryRole:
            return folder["category"]
        elif role == self.Roles.HeroPathRole:
            cover = self._meta_for(folder).get("cover_path")
            if cover and os.path.exists(cover):
                return cover
            return self._find_first_media(folder["path"])
        elif role == self.Roles.ItemCountRole:
            return self._count_media(folder["path"])
        elif role == self.Roles.IsFavoriteRole:
            return bool(self._meta_for(folder).get("favorite"))
        elif role == self.Roles.HasCustomCoverRole:
            cover = self._meta_for(folder).get("cover_path")
            return bool(cover and os.path.exists(cover))
        return None

    def roleNames(self):
        return {
            self.Roles.PathRole: b"folderPath",
            self.Roles.NameRole: b"folderName",
            self.Roles.CategoryRole: b"category",
            self.Roles.HeroPathRole: b"heroPath",
            self.Roles.ItemCountRole: b"itemCount",
            self.Roles.IsFavoriteRole: b"isFavorite",
            self.Roles.HasCustomCoverRole: b"hasCustomCover",
        }

    def _uri_to_local_path(self, uri: str) -> str:
        """Convert a file:// URI to a local filesystem path (decoding %XX)."""
        return QUrl(uri).toLocalFile() or uri

    def _find_first_media(self, folder_path: str) -> str:
        return covers.first_media_file(self._uri_to_local_path(folder_path))

    def _count_media(self, folder_path: str) -> int:
        local_path = self._uri_to_local_path(folder_path)
        count = 0
        try:
            for entry in os.listdir(local_path):
                full_path = os.path.join(local_path, entry)
                if os.path.isfile(full_path):
                    ext = Path(entry).suffix.lower()
                    if ext in ALL_MEDIA_EXTENSIONS:
                        count += 1
        except (OSError, PermissionError):
            pass
        return count

    @Slot(str, str)
    def addFolder(self, path: str, category: str):
        self.db.add_folder(path, category)
        self.refresh()

    @Slot(str)
    def removeFolder(self, path: str):
        self.db.remove_folder(path)
        self.refresh()

    def refresh(self):
        self.beginResetModel()
        self._folders = self.db.get_folders_by_category(self._current_category)
        self._meta = self._load_meta()
        self.endResetModel()

    def _load_meta(self) -> dict:
        keys = [covers.folder_key(f["path"]) for f in self._folders]
        try:
            return self.db.get_collections_meta(keys)
        except sqlite3.Error as e:
            logger.error("Failed to load folder covers/favorites: %s", e)
            return {}

    # ---- covers and favorites --------------------------------------------

    @Slot(str, bool)
    def setFavorite(self, folder_path: str, favorite: bool):
        key = covers.folder_key(folder_path)
        try:
            self.db.set_collection_favorite(key, favorite)
        except sqlite3.Error as e:
            logger.error("Failed to set folder favorite for %s: %s", key, e)
            return
        covers.notifier.changed.emit(key)

    @Slot(str, str, result=bool)
    def setCoverFromFile(self, folder_path: str, image_path: str) -> bool:
        """Use any image on disk as this folder's cover."""
        return covers.set_cover_from_file(folder_path, image_path, db=self.db)

    @Slot(str)
    def clearCover(self, folder_path: str):
        covers.clear_cover(folder_path, db=self.db)

    def _on_collection_changed(self, key: str):
        for row, folder in enumerate(self._folders):
            if covers.folder_key(folder["path"]) != key:
                continue
            try:
                self._meta[key] = self.db.get_collection_meta(key)
            except sqlite3.Error:
                return
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [
                self.Roles.HeroPathRole,
                self.Roles.IsFavoriteRole,
                self.Roles.HasCustomCoverRole,
            ])
            return

    @Property(str, notify=categoryChanged)
    def currentCategory(self):
        return self._current_category

    @currentCategory.setter
    def currentCategory(self, cat: str):
        if self._current_category != cat:
            self._current_category = cat
            self.refresh()
            self.categoryChanged.emit()

    @Property(int, notify=categoryChanged)
    def count(self):
        return len(self._folders)

    @Slot(int, result=str)
    def getFolderPath(self, row: int) -> str:
        if 0 <= row < len(self._folders):
            return self._folders[row]["path"]
        return ""
