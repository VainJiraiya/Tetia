# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import logging
import sys
from enum import IntEnum
from pathlib import Path
import sqlite3

from PySide6.QtCore import (
    QAbstractListModel,
    QFileSystemWatcher,
    QModelIndex,
    QObject,
    Property,
    QEnum,
    Qt,
    Signal,
    Slot,
    QUrl,
)
from PySide6.QtQml import QmlElement

from tetia.models import covers, profiles, series, virtualfolders
from tetia.models.database import get_database
from tetia.models.scanner import (
    COMIC_EXTENSIONS, EBOOK_EXTENSIONS, IMAGE_EXTENSIONS, MANGA_TAB_EXTENSIONS,
    VIDEO_EXTENSIONS, kind_from_ext, scan_folder,
)

# Sets the QML import module configuration so QML files can write "import Tetia 1.0"
QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

# Registers this Python class as a usable QML element
@QmlElement
class MediaModel(QAbstractListModel):
    # Defines unique integer identifiers for custom data properties exposed to QML
    class Roles(IntEnum):
        MediaIdRole = Qt.UserRole + 1
        UniformResourceIdentifierRole = Qt.UserRole + 2
        FileNameRole = Qt.UserRole + 3
        IsVideoRole = Qt.UserRole + 4
        IsComicRole = Qt.UserRole + 5
        IsBookRole = Qt.UserRole + 6
        IsFavoriteRole = Qt.UserRole + 7
        RatingRole = Qt.UserRole + 8

    # Defines the available view filtering modes
    class FilterMode(IntEnum):
        All = 0
        ImagesOnly = 1
        VideosOnly = 2
        MangaOnly = 3
        BooksOnly = 4

    # Registers the FilterMode enum with Qt's meta-object system so QML can access it
    QEnum(FilterMode)

    # How the files of an open folder are ordered. Default is the order each
    # tab has always used (natural name order; chapter order in a series).
    class SortMode(IntEnum):
        Default = 0
        NameDescending = 1
        NewestFirst = 2
        OldestFirst = 3
        LargestFirst = 4
        SmallestFirst = 5

    QEnum(SortMode)

    # Defines Qt signals to notify QML whenever properties change
    filterModeChanged = Signal()
    sortModeChanged = Signal()
    folderPathChanged = Signal()

    # Initializes the class instance and sets up default internal variables
    def __init__(self, parent_object: QObject = None):
        super().__init__(parent_object)

        # Internal storage lists for media metadata dictionaries
        self._all_images: list[dict] = []
        self._all_videos: list[dict] = []
        self._all_comics: list[dict] = []
        self._all_books: list[dict] = []
        self._visible_items: list[dict] = []

        # Internal state tracking variables
        self._current_folder_path: str = ""
        self._virtual_id: int = -1      # the virtual folder shown, if the grid shows one
        self._sortable_ids = False      # the ids shown are a tag page's, which the sort choice applies to
        self._sort_mode = MediaModel.SortMode.Default
        self._filter_mode: MediaModel.FilterMode = MediaModel.FilterMode.All

        # Database connection for persistent media identity
        self._db = get_database()

        # Initializes Qt file system watcher to monitor loaded directories for real-time changes
        self._file_system_watcher = QFileSystemWatcher(self)

        # Connects the file watcher's directory modification signal to our internal callback method
        self._file_system_watcher.directoryChanged.connect(self._on_directory_changed)
        self._released = False
        profiles.add_release_hook(self._release_watchers, order=0)

    # --- QAbstractListModel Overrides ---

    # Returns the total number of items currently visible in the model for QML to render
    def rowCount(self, parent_index: QModelIndex = QModelIndex()) -> int:
        return len(self._visible_items)

    # Fetches specific piece of data (URI, name, or video flag) for a given grid index and role
    def data(self, item_index: QModelIndex, data_role: int = Qt.DisplayRole):
        # Checks if the requested index exists within the valid bounds of our visible items list
        if not item_index.isValid() or not (
            0 <= item_index.row() < len(self._visible_items)
        ):
            return None

        current_item = self._visible_items[item_index.row()]

        # Returns the media database ID
        if data_role == MediaModel.Roles.MediaIdRole:
            return current_item.get("media_id")

        # Returns the URI string if QML requests the URI role or default display role
        if (
            data_role == MediaModel.Roles.UniformResourceIdentifierRole
            or data_role == Qt.DisplayRole
        ):
            return current_item["uniform_resource_identifier"]

        # Returns the plain file name if QML requests the file name role
        elif data_role == MediaModel.Roles.FileNameRole:
            return current_item["file_name"]

        # Returns True/False if QML requests the video check role
        elif data_role == MediaModel.Roles.IsVideoRole:
            return current_item["is_video"]

        # Returns True/False if QML requests the comic/manga check role
        elif data_role == MediaModel.Roles.IsComicRole:
            return current_item["is_comic"]

        # Returns True/False if QML requests the ebook check role
        elif data_role == MediaModel.Roles.IsBookRole:
            return current_item["is_book"]

        # Returns favorite status (0 or 1)
        elif data_role == MediaModel.Roles.IsFavoriteRole:
            return current_item.get("is_favorite", 0)

        # Returns rating (-1 means NULL/unrated in QML)
        elif data_role == MediaModel.Roles.RatingRole:
            rating = current_item.get("rating")
            return rating if rating is not None else -1

        return None

    # Maps Python integer role IDs to variable names that QML delegates can read directly
    def roleNames(self) -> dict[int, bytes]:
        return {
            MediaModel.Roles.MediaIdRole: b"mediaId",
            MediaModel.Roles.UniformResourceIdentifierRole: b"fileUri",
            MediaModel.Roles.FileNameRole: b"fileName",
            MediaModel.Roles.IsVideoRole: b"isVideo",
            MediaModel.Roles.IsComicRole: b"isComic",
            MediaModel.Roles.IsBookRole: b"isBook",
            MediaModel.Roles.IsFavoriteRole: b"isFavorite",
            MediaModel.Roles.RatingRole: b"rating",
        }

    # --- Hashing ---

    def _compute_content_hash(self, file_path: str) -> str:
        """Compute a cheap partial hash: SHA-1 over size + first 1MB + last 1MB."""
        p = Path(file_path)
        try:
            file_size = p.stat().st_size
        except OSError:
            return ""

        if file_size == 0:
            return hashlib.sha1(b"empty").hexdigest()

        to_hash = str(file_size).encode()

        try:
            with open(p, "rb") as f:
                # First 1 MB
                to_hash += f.read(1024 * 1024)

                # Last 1 MB
                if file_size > 1024 * 1024:
                    f.seek(-1024 * 1024, 2)
                    to_hash += f.read(1024 * 1024)
        except OSError:
            return ""

        return hashlib.sha1(to_hash).hexdigest()

    # --- Slots & Public Methods ---

    # Receives a file URL string from QML or Python, parses the folder, and extracts file data
    @Slot(str)
    def load_from_qurl(self, qurl_string: str):
        print(f"[MEDIA] load_from_qurl called with: {qurl_string}")
        # Stops execution early if an empty path string was passed in
        if not qurl_string:
            print("[MEDIA] Empty path, returning")
            return

        # Converts QUrl string (file://) into a standard system path string
        clean_path_string = (
            QUrl(qurl_string).toLocalFile() or qurl_string
        )
        folder_directory = Path(clean_path_string)
        print(f"[MEDIA] Resolved path: {folder_directory}, is_dir: {folder_directory.is_dir()}")

        # Stops execution if the target path is not a valid directory on disk
        if not folder_directory.is_dir():
            print("[MEDIA] Path is not a directory, returning")
            return

        # Kept exactly as chosen, since QML reads it back through folderPath
        self._current_folder_path = str(folder_directory)
        self._virtual_id = -1
        self._sortable_ids = False

        # Stored media paths are resolved (symlinks followed), so database
        # comparisons for this folder must use the resolved form as well
        scan_directory = folder_directory.resolve()

        # Unsubscribes watcher from previously monitored folders if any exist
        existing_watched_directories = self._file_system_watcher.directories()
        if existing_watched_directories:
            self._file_system_watcher.removePaths(existing_watched_directories)

        # Subscribes watcher to start monitoring the newly selected directory path
        self._file_system_watcher.addPath(self._current_folder_path)

        (
            temporary_images_list,
            temporary_videos_list,
            temporary_comics_list,
            temporary_books_list,
        ) = scan_folder(self._db, folder_directory, self._compute_content_hash)

        # What was put in a virtual folder is shown there, no longer here
        self._all_images, self._all_videos, self._all_comics, self._all_books = self._without_placed(
            temporary_images_list, temporary_videos_list, temporary_comics_list, temporary_books_list)

        # Refreshes the active grid display list and notifies QML of path changes
        self._update_visible_items()
        self.folderPathChanged.emit()

    def _without_placed(self, *lists):
        ids = [item["media_id"] for items in lists for item in items if item.get("media_id") is not None]
        try:
            placed = virtualfolders.placed_media_ids(self._db, ids) if ids else set()
        except sqlite3.Error as e:
            logger.error("Failed to look up virtual folder placements: %s", e)
            placed = set()
        if not placed:
            return lists
        return tuple([item for item in items if item.get("media_id") not in placed] for items in lists)

    def _kind_from_ext(self, ext: str) -> str:
        return kind_from_ext(ext)

    # Automatically reloads directory contents whenever the file watcher detects on-disk changes
    def _release_watchers(self):
        """Stop watching folders and stop reacting to changes (before a vault is locked)."""
        self._released = True
        watched = self._file_system_watcher.directories()
        if watched:
            self._file_system_watcher.removePaths(watched)

    def _on_directory_changed(self, modified_directory_path: str):
        if self._released:
            return
        # Re-runs folder parsing using the modified directory path
        self.load_from_qurl(modified_directory_path)

    # Rebuilds the active grid display list according to the current filter mode setting
    def _sorted(self, items: list) -> list:
        """`items` in the chosen sort order. Only for an open folder (search
        results keep their ranking); ties fall back to natural name order."""
        mode = self._sort_mode
        if mode == MediaModel.SortMode.Default or not (self._current_folder_path or self._virtual_id >= 0 or self._sortable_ids):
            return items
        name = lambda item: covers.natural_key(item["file_name"])
        if mode == MediaModel.SortMode.NameDescending:
            return sorted(items, key=name, reverse=True)
        keys = {
            MediaModel.SortMode.NewestFirst: lambda i: (-i.get("mtime", 0), name(i)),
            MediaModel.SortMode.OldestFirst: lambda i: (i.get("mtime", 0), name(i)),
            MediaModel.SortMode.LargestFirst: lambda i: (-i.get("size", 0), name(i)),
            MediaModel.SortMode.SmallestFirst: lambda i: (i.get("size", 0), name(i)),
        }
        return sorted(items, key=keys[mode])

    def _folder_is_series(self) -> bool:
        try:
            meta = self._db.get_collection_meta(covers.folder_key(self._current_folder_path))
        except sqlite3.Error:
            return False
        return bool(meta["is_series"])

    def _update_visible_items(self):
        # Tells Qt to temporarily freeze UI updates while we rebuild the data list
        self.beginResetModel()

        # Displays only image files if filter mode is set to ImagesOnly
        if self._filter_mode == MediaModel.FilterMode.ImagesOnly:
            self._visible_items = self._all_images

        # Displays only video files if filter mode is set to VideosOnly
        elif self._filter_mode == MediaModel.FilterMode.VideosOnly:
            self._visible_items = self._all_videos

        # Displays comic/manga archives and PDFs if filter mode is set to MangaOnly.
        # PDFs are ebooks by kind, so they are picked out of the books list.
        elif self._filter_mode == MediaModel.FilterMode.MangaOnly:
            manga = self._all_comics + [
                item for item in self._all_books
                if Path(item["file_name"]).suffix.lower() in MANGA_TAB_EXTENSIONS
            ]
            manga.sort(key=lambda item: covers.natural_key(item["file_name"]))
            if self._folder_is_series() and manga:
                # One title's chapters: reading order, not alphabetical
                position = {name: i for i, name in enumerate(
                    series.sort_chapter_names([item["file_name"] for item in manga]))}
                manga.sort(key=lambda item: position[item["file_name"]])
            self._visible_items = manga

        # Displays only ebooks if filter mode is set to BooksOnly
        elif self._filter_mode == MediaModel.FilterMode.BooksOnly:
            self._visible_items = self._all_books

        # Displays all media files combined if filter mode is set to All
        else:
            self._visible_items = (
                self._all_images
                + self._all_videos
                + self._all_comics
                + self._all_books
            )

        self._visible_items = self._sorted(self._visible_items)

        # Unfreezes Qt UI updates and tells QML to redraw the grid view
        self.endResetModel()

    # --- Favorite and Rating operations (keyed by media_id, emit dataChanged for single row) ---

    def _visible_row_for_media_id(self, media_id: int):
        """Find the visible row index for a given media_id. Returns -1 if not found."""
        for i, item in enumerate(self._visible_items):
            if item.get("media_id") == media_id:
                return i
        return -1

    @Slot(list)
    def load_media_ids_sorted(self, media_ids: list):
        """Like load_media_ids, for the results of a tag: the ids are in natural name order and the grid's sort
        choice applies to them (a search keeps its own order)."""
        self.load_media_ids(media_ids)
        self._sortable_ids = True
        self._update_visible_items()

    @Slot(list)
    def load_media_ids(self, media_ids: list):
        """Show these media rows (search results) instead of a folder's files,
        in the order given. Leaves no folder open, so folder-only features
        (watching, folder cover, subfolder tiles) switch themselves off."""
        ids = [int(i) for i in media_ids or []]
        rows = self._db.get_media_rows(ids)

        existing_watched = self._file_system_watcher.directories()
        if existing_watched:
            self._file_system_watcher.removePaths(existing_watched)
        self._current_folder_path = ""
        self._virtual_id = -1
        self._sortable_ids = False

        images, videos, comics, books = [], [], [], []
        for media_id in ids:
            row = rows.get(media_id)
            if row is None:
                continue
            kind = row["kind"]
            item = {
                "media_id": media_id,
                "uniform_resource_identifier": Path(row["path"]).as_uri(),
                "file_name": row["name"],
                "is_video": kind == "video",
                "is_comic": kind == "comic",
                "is_book": kind == "ebook",
                "is_favorite": row["favorite"],
                "rating": row["rating"],
            }
            {"image": images, "video": videos, "comic": comics, "ebook": books}[kind].append(item)

        self._all_images, self._all_videos = images, videos
        self._all_comics, self._all_books = comics, books
        self._update_visible_items()
        self.folderPathChanged.emit()

    @Slot(int)
    def load_virtual_folder(self, vfolder_id: int):
        """Show the files placed directly in a virtual folder (they can come from anywhere below its home
        folder), in the usual folder order. Like search results it has no real folder behind it, so nothing
        is watched; the folder tiles come from SubfolderModel.loadVirtual."""
        existing_watched = self._file_system_watcher.directories()
        if existing_watched:
            self._file_system_watcher.removePaths(existing_watched)
        self._current_folder_path = ""
        self._virtual_id = int(vfolder_id)
        self._sortable_ids = False

        images, videos, comics, books = [], [], [], []
        for row in virtualfolders.member_rows(self._db, self._virtual_id):
            kind = row["kind"]
            item = {
                "media_id": row["id"],
                "uniform_resource_identifier": Path(row["path"]).as_uri(),
                "file_name": row["name"],
                "is_video": kind == "video",
                "is_comic": kind == "comic",
                "is_book": kind == "ebook",
                "is_favorite": row["favorite"],
                "rating": row["rating"],
            }
            try:
                info = Path(row["path"]).stat()
                item["size"], item["mtime"] = info.st_size, int(info.st_mtime)
            except OSError:
                pass
            {"image": images, "video": videos, "comic": comics, "ebook": books}[kind].append(item)

        self._all_images, self._all_videos = images, videos
        self._all_comics, self._all_books = comics, books
        self._update_visible_items()
        self.folderPathChanged.emit()

    @Property(int, notify=folderPathChanged)
    def virtualId(self) -> int:
        """The virtual folder shown now, or -1."""
        return self._virtual_id

    @Slot(int, bool)
    def setFavorite(self, media_id: int, favorite: bool):
        """Toggle favorite status for a media item. Emits dataChanged for the affected row only."""
        try:
            self._db.set_media_favorite(media_id, favorite)
        except sqlite3.Error as e:
            logger.error("Failed to set favorite for media_id=%d: %s", media_id, e)
            return
        row = self._visible_row_for_media_id(media_id)
        if row >= 0:
            idx = self.index(row)
            self._visible_items[row]["is_favorite"] = 1 if favorite else 0
            self.dataChanged.emit(idx, idx, [MediaModel.Roles.IsFavoriteRole])

    @Slot(int, result=bool)
    def getFavorite(self, media_id: int) -> bool:
        try:
            return bool(self._db.get_media_favorite(media_id))
        except sqlite3.Error as e:
            logger.error("Failed to get favorite for media_id=%d: %s", media_id, e)
            return False

    @Slot(int, result=int)
    def getRating(self, media_id: int) -> int:
        try:
            rating = self._db.get_media_rating(media_id)
            return rating if rating is not None else -1
        except sqlite3.Error as e:
            logger.error("Failed to get rating for media_id=%d: %s", media_id, e)
            return -1

    @Slot(int, int)
    def setRating(self, media_id: int, rating: int):
        """Set rating for a media item. rating=-1 clears to NULL. Emits dataChanged for the affected row only."""
        db_rating = None if rating == -1 else rating
        try:
            self._db.set_media_rating(media_id, db_rating)
        except sqlite3.Error as e:
            logger.error("Failed to set rating for media_id=%d: %s", media_id, e)
            return
        row = self._visible_row_for_media_id(media_id)
        if row >= 0:
            idx = self.index(row)
            self._visible_items[row]["rating"] = db_rating
            self.dataChanged.emit(idx, idx, [MediaModel.Roles.RatingRole])

    @Slot(int, result=bool)
    def setFolderCover(self, media_id: int) -> bool:
        """Use this item as the cover of the folder being shown. An image is
        used as is, a video gives a full-size frame (ffmpeg), a manga/book uses
        its own first page. Returns False if it could not be done."""
        if self._virtual_id >= 0:
            # a virtual folder's picture is one of its own files
            try:
                self._db._write(lambda: self._db.conn.execute(
                    "UPDATE virtual_folder SET cover_media_id = ? WHERE id = ?", (int(media_id), self._virtual_id)))
            except sqlite3.Error as e:
                logger.error("Failed to set the virtual folder cover: %s", e)
                return False
            return True
        if not self._current_folder_path:
            return False
        try:
            info = self._db.get_media_info(media_id)
        except sqlite3.Error as e:
            logger.error("Failed to look up media_id=%d: %s", media_id, e)
            return False
        if info is None:
            return False
        return covers.set_cover_from_media(
            self._current_folder_path, info["path"], info["kind"], db=self._db
        )

    @Slot(result=list)
    def imageIds(self) -> list:
        """The media ids of the pictures shown now (no videos, comics or books), in the order shown."""
        return [item["media_id"] for item in self._visible_items
                if not (item.get("is_video") or item.get("is_comic") or item.get("is_book"))]

    @Slot(result=list)
    def visibleIds(self) -> list:
        """The media ids of every file shown now (the page's items, whatever their type), in the order shown."""
        return [item["media_id"] for item in self._visible_items if item.get("media_id") is not None]

    @Slot(str, result=bool)
    def setFolderCoverFromPath(self, path: str) -> bool:
        """Use the picture a subfolder tile shows (a file inside it, which is not one of this
        folder's own files) as the cover of the folder being shown. Same rules as setFolderCover."""
        if not self._current_folder_path or not path:
            return False
        suffix = Path(path).suffix.lower()
        if suffix in covers.IMAGE_EXTENSIONS:
            kind = "image"
        elif suffix in VIDEO_EXTENSIONS:
            kind = "video"
        elif suffix in COMIC_EXTENSIONS:
            kind = "comic"
        elif suffix in EBOOK_EXTENSIONS:
            kind = "ebook"
        else:
            return False
        return covers.set_cover_from_media(self._current_folder_path, path, kind, db=self._db)

    # --- Properties exposed to QML ---

    # Exposes the current filter mode value to QML as a readable property
    @Property(int, notify=filterModeChanged)
    def filterMode(self) -> int:
        return self._filter_mode

    # Receives new filter mode settings from QML and updates the visible items list
    @filterMode.setter
    def filterMode(self, selected_mode: int):
        # Only updates and triggers redraws if the incoming mode is different from current mode
        if self._filter_mode != selected_mode:
            self._filter_mode = MediaModel.FilterMode(selected_mode)
            self._update_visible_items()
            self.filterModeChanged.emit()

    @Property(int, notify=sortModeChanged)
    def sortMode(self) -> int:
        return int(self._sort_mode)

    @sortMode.setter
    def sortMode(self, selected_mode: int):
        if int(self._sort_mode) != selected_mode:
            self._sort_mode = MediaModel.SortMode(selected_mode)
            self._update_visible_items()
            self.sortModeChanged.emit()

    # Exposes the current loaded folder path string to QML as a read-only property
    @Property(str, notify=folderPathChanged)
    def folderPath(self) -> str:
        return self._current_folder_path

    # Looks up a single item's file URI by its row in the currently visible
    # (filtered) list. Used by QML to open videos/comics/ebooks externally
    # since those don't have dedicated in-app viewers yet.
    @Slot(int, result=str)
    def getFileUri(self, row: int) -> str:
        if 0 <= row < len(self._visible_items):
            return self._visible_items[row]["uniform_resource_identifier"]
        return ""
