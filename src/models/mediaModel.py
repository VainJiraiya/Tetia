import hashlib
import sys
from enum import IntEnum
from pathlib import Path

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

from models.database import Database

# Sets the QML import module configuration so QML files can write "import Gallery 1.0"
QML_IMPORT_NAME = "Gallery"
QML_IMPORT_MAJOR_VERSION = 1

# Defines sets of allowed file extensions for images and videos
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv"}

# Comic/manga archive formats
COMIC_EXTENSIONS = {".cbz", ".cbr", ".cb7", ".cbt"}

# Ebook formats. PDF is included here rather than under comics, since PDF
# manga is comparatively rare and PDF ebooks/documents are the common case.
EBOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw", ".azw3", ".fb2", ".djvu"}


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

    # Defines Qt signals to notify QML whenever properties change
    filterModeChanged = Signal()
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
        self._filter_mode: MediaModel.FilterMode = MediaModel.FilterMode.All

        # Database connection for persistent media identity
        self._db = Database()

        # Initializes Qt file system watcher to monitor loaded directories for real-time changes
        self._file_system_watcher = QFileSystemWatcher(self)

        # Connects the file watcher's directory modification signal to our internal callback method
        self._file_system_watcher.directoryChanged.connect(self._on_directory_changed)

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
        # Stops execution early if an empty path string was passed in
        if not qurl_string:
            return

        # Converts QUrl string (file://) into a standard system path string
        clean_path_string = (
            QUrl(qurl_string).toLocalFile() or qurl_string
        )
        folder_directory = Path(clean_path_string)

        # Stops execution if the target path is not a valid directory on disk
        if not folder_directory.is_dir():
            return

        self._current_folder_path = str(folder_directory)

        # Unsubscribes watcher from previously monitored folders if any exist
        existing_watched_directories = self._file_system_watcher.directories()
        if existing_watched_directories:
            self._file_system_watcher.removePaths(existing_watched_directories)

        # Subscribes watcher to start monitoring the newly selected directory path
        self._file_system_watcher.addPath(self._current_folder_path)

        temporary_images_list = []
        temporary_videos_list = []
        temporary_comics_list = []
        temporary_books_list = []

        scanned_paths = set()

        # Iterates over every file in the target directory and collects media metadata
        for directory_item in folder_directory.iterdir():
            # Checks if the current item is an actual file (not a subfolder)
            if directory_item.is_file():
                file_extension = directory_item.suffix.lower()

                is_image = file_extension in IMAGE_EXTENSIONS
                is_video = file_extension in VIDEO_EXTENSIONS
                is_comic = file_extension in COMIC_EXTENSIONS
                is_book = file_extension in EBOOK_EXTENSIONS

                # Skips anything that doesn't match a supported extension
                if not (is_image or is_video or is_comic or is_book):
                    continue

                abs_path = str(directory_item.resolve())
                scanned_paths.add(abs_path)
                file_size = directory_item.stat().st_size
                file_mtime = int(directory_item.stat().st_mtime)
                content_hash = self._compute_content_hash(abs_path)

                # Check if this hash matches a missing row (move/rename reconciliation)
                move_info = self._db.find_missing_by_hash(content_hash)
                if move_info:
                    self._db.upsert_media(
                        abs_path, directory_item.name,
                        self._kind_from_ext(file_extension),
                        file_size, file_mtime, content_hash
                    )
                    media_id = move_info["id"]
                else:
                    self._db.upsert_media(
                        abs_path, directory_item.name,
                        self._kind_from_ext(file_extension),
                        file_size, file_mtime, content_hash
                    )
                    # Retrieve the media_id we just upserted
                    cursor = self._db.conn.cursor()
                    cursor.execute("SELECT id FROM media WHERE path = ?", (abs_path,))
                    row = cursor.fetchone()
                    media_id = row[0] if row else 0

                favorite = self._db.get_media_favorite(media_id)
                rating = self._db.get_media_rating(media_id)

                item_metadata = {
                    "media_id": media_id,
                    "uniform_resource_identifier": directory_item.as_uri(),
                    "file_name": directory_item.name,
                    "is_video": is_video,
                    "is_comic": is_comic,
                    "is_book": is_book,
                    "is_favorite": favorite,
                    "rating": rating,
                }

                # Sorts item into whichever list matches its extension
                if is_image:
                    temporary_images_list.append(item_metadata)
                elif is_video:
                    temporary_videos_list.append(item_metadata)
                elif is_comic:
                    temporary_comics_list.append(item_metadata)
                elif is_book:
                    temporary_books_list.append(item_metadata)

        # Mark files that existed before but are no longer scanned as missing
        self._db.mark_missing(scanned_paths)

        self._all_images = temporary_images_list
        self._all_videos = temporary_videos_list
        self._all_comics = temporary_comics_list
        self._all_books = temporary_books_list

        # Refreshes the active grid display list and notifies QML of path changes
        self._update_visible_items()
        self.folderPathChanged.emit()

    def _kind_from_ext(self, ext: str) -> str:
        if ext in IMAGE_EXTENSIONS:
            return "image"
        elif ext in VIDEO_EXTENSIONS:
            return "video"
        elif ext in COMIC_EXTENSIONS:
            return "comic"
        elif ext in EBOOK_EXTENSIONS:
            return "ebook"
        return "image"

    # Automatically reloads directory contents whenever the file watcher detects on-disk changes
    def _on_directory_changed(self, modified_directory_path: str):
        # Re-runs folder parsing using the modified directory path
        self.load_from_qurl(modified_directory_path)

    # Rebuilds the active grid display list according to the current filter mode setting
    def _update_visible_items(self):
        # Tells Qt to temporarily freeze UI updates while we rebuild the data list
        self.beginResetModel()

        # Displays only image files if filter mode is set to ImagesOnly
        if self._filter_mode == MediaModel.FilterMode.ImagesOnly:
            self._visible_items = self._all_images

        # Displays only video files if filter mode is set to VideosOnly
        elif self._filter_mode == MediaModel.FilterMode.VideosOnly:
            self._visible_items = self._all_videos

        # Displays only comic/manga archives if filter mode is set to MangaOnly
        elif self._filter_mode == MediaModel.FilterMode.MangaOnly:
            self._visible_items = self._all_comics

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

        # Unfreezes Qt UI updates and tells QML to redraw the grid view
        self.endResetModel()

    # --- Favorite and Rating operations (keyed by media_id, emit dataChanged for single row) ---

    def _visible_row_for_media_id(self, media_id: int):
        """Find the visible row index for a given media_id. Returns -1 if not found."""
        for i, item in enumerate(self._visible_items):
            if item.get("media_id") == media_id:
                return i
        return -1

    @Slot(int, bool)
    def setFavorite(self, media_id: int, favorite: bool):
        """Toggle favorite status for a media item. Emits dataChanged for the affected row only."""
        self._db.set_media_favorite(media_id, favorite)
        row = self._visible_row_for_media_id(media_id)
        if row >= 0:
            idx = self.index(row)
            self._visible_items[row]["is_favorite"] = 1 if favorite else 0
            self.dataChanged.emit(idx, idx, [MediaModel.Roles.IsFavoriteRole])

    @Slot(int, int)
    def setRating(self, media_id: int, rating: int):
        """Set rating for a media item. rating=-1 clears to NULL. Emits dataChanged for the affected row only."""
        db_rating = None if rating == -1 else rating
        self._db.set_media_rating(media_id, db_rating)
        row = self._visible_row_for_media_id(media_id)
        if row >= 0:
            idx = self.index(row)
            self._visible_items[row]["rating"] = db_rating
            self.dataChanged.emit(idx, idx, [MediaModel.Roles.RatingRole])

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
