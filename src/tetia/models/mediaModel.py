# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import sys
from enum import IntEnum
from pathlib import Path
import sqlite3
import threading
import weakref

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
    QTimer,
    QUrl,
)
from PySide6.QtQml import QmlElement
from shiboken6 import isValid

from tetia import timing
from tetia.models import covers, profiles, series, virtualfolders
from tetia.models.database import Database, get_database
from tetia.models.playbackStore import progress_fraction, prober
from tetia.models.scanner import (
    COMIC_EXTENSIONS, EBOOK_EXTENSIONS, IMAGE_EXTENSIONS, MANGA_TAB_EXTENSIONS,
    VIDEO_EXTENSIONS, ScanStopped, kind_from_ext, known_items, scan_folder,
)
from tetia.models.scanner import fingerprint as scanner_fingerprint

# Sets the QML import module configuration so QML files can write "import Tetia 1.0"
QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

# every media model, so a test can stop their background scans when it ends
_instances = weakref.WeakSet()


def stop_all_scans():
    for model in list(_instances):
        if isValid(model):
            model._stop_scan()

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
        WatchFractionRole = Qt.UserRole + 9    # how much of a video was watched, 0..1 (0: not started)
        IsWatchedRole = Qt.UserRole + 10       # a video watched to the end
        AspectRole = Qt.UserRole + 11          # width / height of the picture as shown; 0 while not known
        DurationRole = Qt.UserRole + 12        # a video's length in seconds; 0 while not known

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
    scanningChanged = Signal()
    sourcesChanged = Signal()
    _scanDone = Signal(int, object)     # (scan generation, the four lists or None), from the scan thread

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

        # An opened folder is shown from what the library knows, then scanned in the background
        self._scan_generation = 0
        self._scan_stop = threading.Event()
        self._scan_thread = None
        self._scanning = False
        self._sources: list[str] = []     # a tab's top level: the library folders whose contents are shown together
        self._scanDone.connect(self._apply_scan)
        profiles.add_release_hook(self._stop_scan, order=0)
        _instances.add(self)

        # Videos' lengths and picture sizes are learned in the background; the page catches up a moment later
        self._learned_timer = QTimer(self)
        self._learned_timer.setSingleShot(True)
        self._learned_timer.setInterval(400)
        self._learned_timer.timeout.connect(self._refresh_videos)
        prober().learned.connect(self._learned_timer.start)

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

        elif data_role == MediaModel.Roles.WatchFractionRole:
            return current_item.get("watch_fraction", 0.0)

        elif data_role == MediaModel.Roles.IsWatchedRole:
            return current_item.get("watched", False)

        elif data_role == MediaModel.Roles.DurationRole:
            return float(current_item.get("duration", 0.0))

        elif data_role == MediaModel.Roles.AspectRole:
            width, height = current_item.get("width") or 0, current_item.get("height") or 0
            return width / height if width > 0 and height > 0 else 0.0

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
            MediaModel.Roles.WatchFractionRole: b"watchFraction",
            MediaModel.Roles.IsWatchedRole: b"isWatched",
            MediaModel.Roles.AspectRole: b"aspect",
            MediaModel.Roles.DurationRole: b"duration",
        }

    # --- Hashing ---

    # The fingerprint that recognises a renamed file (scanner.fingerprint: a scan given exactly this function reads
    # each new file once, its picture size included). A test may put a slower one on an instance.
    _compute_content_hash = staticmethod(scanner_fingerprint)

    # --- Slots & Public Methods ---

    # Receives a file URL string from QML or Python, parses the folder, and extracts file data
    @Slot(str)
    def load_from_qurl(self, qurl_string: str):
        """Scan a folder and show it, all before returning (the file watcher's reloads and tests use this;
        a page uses openFolder, which does not make the window wait)."""
        folder_directory = self._enter_folder(qurl_string)
        if folder_directory is None:
            return
        self._show_lists(scan_folder(self._db, folder_directory, self._compute_content_hash))

    @Slot(str)
    @timing.measured("files: open a folder")
    def openFolder(self, qurl_string: str):
        """Show a folder at once from what the library already knows about it, and scan it in the background
        (reading and fingerprinting new files can take a long while on a slow drive). The page updates when the
        scan is done, and only if something changed; `scanning` is true meanwhile."""
        folder_directory = self._enter_folder(qurl_string)
        if folder_directory is None:
            return
        try:
            with timing.timed("files: what the library knows"):
                known = known_items(self._db, folder_directory)
        except sqlite3.Error as e:
            logger.error("Failed to read what is known of %s: %s", folder_directory, e)
            known = ([], [], [], [])
        with timing.timed("files: shown (rows built)"):
            self._show_lists(known)
        self._start_scan(folder_directory)

    @Slot(list)
    @timing.measured("files: open a tab's top")
    def openSources(self, locations: list):
        """A tab's top level: the files lying directly in each of these library folders, kept together by folder
        (each group under its folder's name), shown at once from the library and scanned in the background."""
        folders = []
        for location in locations or []:
            folder = Path(QUrl(str(location)).toLocalFile() or str(location))
            if folder.is_dir():
                folders.append(folder)
        self._cancel_scan()
        self._current_folder_path = ""
        self._virtual_id = -1
        self._sortable_ids = True
        self._sources = [str(f) for f in folders]
        watched = self._file_system_watcher.directories()
        if watched:
            self._file_system_watcher.removePaths(watched)
        if self._sources and not self._released:
            self._file_system_watcher.addPaths(self._sources)
        try:
            with timing.timed("files: what the library knows"):
                known = self._merge([known_items(self._db, f) for f in folders])
        except sqlite3.Error as e:
            logger.error("Failed to read what is known of the library folders: %s", e)
            known = ([], [], [], [])
        with timing.timed("files: shown (rows built)"):
            self._show_lists(known)
        self.sourcesChanged.emit()
        if folders:
            self._start_scan(folders)

    @staticmethod
    def _merge(per_folder):
        """One set of four lists from several folders' scans; each item remembers which folder (its index)."""
        merged = ([], [], [], [])
        for index, lists in enumerate(per_folder):
            for kind, items in enumerate(lists):
                for item in items:
                    item["source"] = index
                merged[kind].extend(items)
        return merged

    def _leave_sources(self):
        if self._sources:
            self._sources = []
            self.sourcesChanged.emit()

    @Slot(result="QVariantMap")
    def kindCounts(self) -> dict:
        """How many of each kind the page holds, whatever the filter (for a results page's type chips)."""
        pdfs = sum(1 for item in self._all_books if Path(item["file_name"]).suffix.lower() in MANGA_TAB_EXTENSIONS)
        return {"all": len(self._all_images) + len(self._all_videos) + len(self._all_comics) + len(self._all_books),
                "images": len(self._all_images), "videos": len(self._all_videos),
                "manga": len(self._all_comics) + pdfs, "books": len(self._all_books)}

    @Property(list, notify=sourcesChanged)
    def sources(self):
        """The library folders shown together (a tab's top level), as paths; empty otherwise."""
        return list(self._sources)

    def sourceGroups(self):
        """For the page's layout: [(first row, folder name, how many)] of each folder's files, in order."""
        groups = []
        for row, item in enumerate(self._visible_items):
            index = item.get("source", 0)
            if not groups or groups[-1][3] != index:
                name = os.path.basename(self._sources[index].rstrip(os.sep)) if index < len(self._sources) else ""
                groups.append([row, name, 0, index])
            groups[-1][2] += 1
        return [(row, name, count) for row, name, count, _ in groups]

    def _enter_folder(self, qurl_string: str):
        """Make `qurl_string` the open folder (and watch it); the folder as a Path, or None if it isn't one."""
        if not qurl_string:
            return None
        folder_directory = Path(QUrl(qurl_string).toLocalFile() or qurl_string)
        if not folder_directory.is_dir():
            logger.info("Not a folder: %s", folder_directory)
            return None
        self._cancel_scan()
        self._leave_sources()
        # Kept exactly as chosen, since QML reads it back through folderPath
        self._current_folder_path = str(folder_directory)
        self._virtual_id = -1
        self._sortable_ids = False

        existing_watched_directories = self._file_system_watcher.directories()
        if existing_watched_directories:
            self._file_system_watcher.removePaths(existing_watched_directories)
        self._file_system_watcher.addPath(self._current_folder_path)
        return folder_directory

    def _show_lists(self, lists):
        # What was put in a virtual folder is shown there, no longer here
        self._all_images, self._all_videos, self._all_comics, self._all_books = self._without_placed(*lists)
        self._update_visible_items()
        self.folderPathChanged.emit()

    # --- The background scan ---

    @Property(bool, notify=scanningChanged)
    def scanning(self):
        return self._scanning

    def _set_scanning(self, scanning: bool):
        if scanning != self._scanning:
            self._scanning = scanning
            self.scanningChanged.emit()

    def _start_scan(self, folder_directory):
        """Scan a folder (or, for a tab's top level, a list of them) in the background."""
        self._cancel_scan()
        if self._released:
            return
        generation, stop = self._scan_generation, self._scan_stop
        hash_fn = self._compute_content_hash
        folders = list(folder_directory) if isinstance(folder_directory, (list, tuple)) else None

        def work():
            db = None
            try:
                db = Database()      # a connection of its own: sqlite connections are per-thread
                if folders is None:
                    lists = scan_folder(db, folder_directory, hash_fn, stop.is_set)
                else:
                    lists = self._merge([scan_folder(db, f, hash_fn, stop.is_set) for f in folders])
            except ScanStopped:
                return
            except Exception:
                logger.exception("Scanning %s failed", folder_directory)
                lists = None
            finally:
                if db is not None:
                    db.close()
            if not stop.is_set() and isValid(self):       # (the model may be gone by now)
                self._scanDone.emit(generation, lists)

        self._scan_thread = threading.Thread(target=work, name="folder-scan", daemon=True)
        self._set_scanning(True)
        self._scan_thread.start()

    def _cancel_scan(self):
        """Forget a scan still running (its result would be for a page no longer shown)."""
        self._scan_stop.set()
        self._scan_stop = threading.Event()
        self._scan_generation += 1
        self._set_scanning(False)

    def _stop_scan(self):
        """Stop a running scan and wait for it (before a vault is locked: it holds files and the database)."""
        self._cancel_scan()
        thread = self._scan_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=15)

    @staticmethod
    def _signature(lists):
        return [[(i["media_id"], i["file_name"], i.get("size"), i.get("mtime")) for i in items] for items in lists]

    def _apply_scan(self, generation: int, lists):
        if generation != self._scan_generation:
            return                                   # another folder (or a search) is shown now
        self._set_scanning(False)
        if lists is None:
            return
        fresh = self._without_placed(*lists)
        shown = (self._all_images, self._all_videos, self._all_comics, self._all_books)
        if self._signature(fresh) != self._signature(shown):
            self._show_lists(lists)
            return
        # Nothing came or went: only what the scan learned on the way (an image's size), without a reset
        known = {item["media_id"]: item for items in fresh for item in items}
        changed = []
        for row, item in enumerate(self._visible_items):
            new = known.get(item.get("media_id"))
            if new is not None and (new["width"], new["height"]) != (item.get("width", 0), item.get("height", 0)):
                item["width"], item["height"] = new["width"], new["height"]
                changed.append(row)
        if changed:
            self.dataChanged.emit(self.index(changed[0]), self.index(changed[-1]), [MediaModel.Roles.AspectRole])

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
        # Scans the folder again in the background; the page keeps showing what it has meanwhile
        if self._sources and modified_directory_path in self._sources:
            self._start_scan([Path(f) for f in self._sources])
        elif modified_directory_path == self._current_folder_path:
            self._start_scan(Path(modified_directory_path))

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

    def _grouped(self, items: list) -> list:
        """On a tab's top level the files stay together by library folder (a stable sort keeps their order)."""
        return sorted(items, key=lambda item: item.get("source", 0)) if self._sources else items

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

        self._visible_items = self._grouped(self._sorted(self._visible_items))
        self._attach_playback()
        unknown = [QUrl(item["uniform_resource_identifier"]).toLocalFile() for item in self._visible_items
                   if item.get("is_video") and not item.get("width")]
        if unknown:
            prober().request(unknown)

        # Unfreezes Qt UI updates and tells QML to redraw the grid view
        self.endResetModel()

    def _attach_playback(self):
        """Put how far each video was watched next to it (one query for the page)."""
        videos = [item for item in self._visible_items if item.get("is_video") and item.get("media_id") is not None]
        try:
            records = self._db.get_playback_many([item["media_id"] for item in videos]) if videos else {}
        except sqlite3.Error as e:
            logger.error("Failed to read playback progress: %s", e)
            records = {}
        for item in videos:
            record = records.get(item["media_id"])
            item["watched"] = bool(record and record["finished"])
            item["watch_fraction"] = (progress_fraction(record["position"], record["duration"], record["finished"])
                                      if record else 0.0)
            item["duration"] = record["duration"] if record else 0.0

    def _refresh_videos(self):
        """The background probe learned more about some videos: their shape and length (no reset)."""
        rows = [row for row, item in enumerate(self._visible_items) if item.get("is_video")]
        if not rows:
            return
        try:
            stored = self._db.get_media_rows([self._visible_items[row]["media_id"] for row in rows])
        except sqlite3.Error as e:
            logger.error("Failed to read video sizes: %s", e)
            return
        for row in rows:
            found = stored.get(self._visible_items[row]["media_id"])
            if found is not None:
                self._visible_items[row]["width"] = found["width"] or 0
                self._visible_items[row]["height"] = found["height"] or 0
        self._attach_playback()
        self.dataChanged.emit(self.index(rows[0]), self.index(rows[-1]),
                              [MediaModel.Roles.AspectRole, MediaModel.Roles.WatchFractionRole,
                               MediaModel.Roles.IsWatchedRole, MediaModel.Roles.DurationRole])

    @Slot()
    def refreshPlayback(self):
        """After watching: update the bars and marks of the videos on the page (no reset, so the grid keeps its place)."""
        self._attach_playback()
        videos = [row for row, item in enumerate(self._visible_items) if item.get("is_video")]
        if videos:
            self.dataChanged.emit(self.index(videos[0]), self.index(videos[-1]),
                                  [MediaModel.Roles.WatchFractionRole, MediaModel.Roles.IsWatchedRole])

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
        self._cancel_scan()
        self._leave_sources()
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
                "width": row["width"] or 0,
                "height": row["height"] or 0,
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
        self._cancel_scan()
        self._leave_sources()
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
                "width": row["width"] or 0,
                "height": row["height"] or 0,
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
    @Slot(result=list)
    def videoList(self) -> list:
        """The videos shown now, in the order shown, for the player to step through: [{row, uri, name}]."""
        return [{"row": row, "uri": item["uniform_resource_identifier"], "name": item["file_name"]}
                for row, item in enumerate(self._visible_items) if item.get("is_video")]

    @Slot(int, result=str)
    def getFileUri(self, row: int) -> str:
        if 0 <= row < len(self._visible_items):
            return self._visible_items[row]["uniform_resource_identifier"]
        return ""
