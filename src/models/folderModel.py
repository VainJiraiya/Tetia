from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal, Slot, Property
from PySide6.QtQml import QmlElement
from models.database import Database
import os
from pathlib import Path

QML_IMPORT_NAME = "Gallery"
QML_IMPORT_MAJOR_VERSION = 1

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".ico", ".svg", ".avif", ".heic", ".heif", ".jxl",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv",
}
ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


@QmlElement
class FolderModel(QAbstractListModel):
    class Roles:
        PathRole = Qt.UserRole + 1
        NameRole = Qt.UserRole + 2
        CategoryRole = Qt.UserRole + 3
        HeroPathRole = Qt.UserRole + 4
        ItemCountRole = Qt.UserRole + 5

    categoryChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database()
        self._current_category = "photos"
        self._folders = []
        self.refresh()

    def rowCount(self, parent=QModelIndex()):
        return len(self._folders)

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
            return self._find_first_media(folder["path"])
        elif role == self.Roles.ItemCountRole:
            return self._count_media(folder["path"])
        return None

    def roleNames(self):
        return {
            self.Roles.PathRole: b"folderPath",
            self.Roles.NameRole: b"folderName",
            self.Roles.CategoryRole: b"category",
            self.Roles.HeroPathRole: b"heroPath",
            self.Roles.ItemCountRole: b"itemCount",
        }

    def _uri_to_local_path(self, uri: str) -> str:
        """Convert file:// URI to local filesystem path."""
        if uri.startswith("file://"):
            return uri[7:]  # strip file://
        return uri

    def _find_first_media(self, folder_path: str) -> str:
        local_path = self._uri_to_local_path(folder_path)
        try:
            if not os.path.isdir(local_path):
                return ""
            entries = sorted(os.listdir(local_path))
            for entry in entries:
                full_path = os.path.join(local_path, entry)
                if os.path.isfile(full_path):
                    ext = Path(entry).suffix.lower()
                    if ext in ALL_MEDIA_EXTENSIONS:
                        return full_path
        except (OSError, PermissionError):
            pass
        return ""

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
        self.endResetModel()

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