"""Search: runs queries (see tag_query), suggests terms, and keeps the library
indexed in the background so a search sees every file, not just the folders
that have been opened."""
import logging
import os
import re
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtQml import QmlElement

from tetia.models import covers, profiles, tag_query
from tetia.models.database import Database, get_database
from tetia.models.scanner import scan_folder, ALL_MEDIA_EXTENSIONS
import hashlib
import sqlite3

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


def content_hash(file_path: str) -> str:
    """Same partial hash MediaModel uses (size + first and last 1 MB)."""
    p = Path(file_path)
    try:
        size = p.stat().st_size
    except OSError:
        return ""
    if size == 0:
        return hashlib.sha1(b"empty").hexdigest()
    data = str(size).encode()
    try:
        with open(p, "rb") as f:
            data += f.read(1024 * 1024)
            if size > 1024 * 1024:
                f.seek(-1024 * 1024, 2)
                data += f.read(1024 * 1024)
    except OSError:
        return ""
    return hashlib.sha1(data).hexdigest()


class _Resolver:
    """Turns tag names into the sets of tag ids that satisfy them."""

    def __init__(self, db):
        self.db = db

    def tag_ids(self, name, category):
        name = re.sub(r"\s+", "_", name.strip().lower())
        tag_id = self.db.resolve_tag_id(name)
        if tag_id is None:
            return set()
        if category and self.db.get_tag_category_name(tag_id) != category:
            return set()
        return self.db.expand_tag(tag_id)

    def wildcard_ids(self, pattern, category):
        pattern = re.sub(r"\s+", "_", pattern)
        ids = set()
        for tag_id in self.db.tag_ids_matching(pattern, category):
            ids |= self.db.expand_tag(tag_id)
        return ids


def walk_directories(root: str, max_depth: int = 32):
    """Yield every directory under root (itself first), skipping hidden ones
    and symlink loops."""
    seen = set()
    stack = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            real = os.path.realpath(directory)
        except OSError:
            continue
        if real in seen or depth > max_depth:
            continue
        seen.add(real)
        yield directory
        try:
            with os.scandir(directory) as entries:
                children = sorted(
                    (e.path for e in entries
                     if not e.name.startswith(".") and e.is_dir()),
                    key=lambda p: covers.natural_key(os.path.basename(p)), reverse=True)
        except OSError:
            continue
        stack.extend((child, depth + 1) for child in children)


@QmlElement
class SearchModel(QObject):
    indexingChanged = Signal()
    # Emitted from the index thread; delivered to the GUI thread by Qt
    indexFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._resolver = _Resolver(self._db)
        self._indexing = False
        self._index_lock = threading.Lock()
        self._rerun = False
        self._stop = threading.Event()
        self._thread = None
        profiles.add_release_hook(self.stop_indexing, order=0)

    # ---- indexing ----------------------------------------------------------

    @Property(bool, notify=indexingChanged)
    def indexing(self):
        return self._indexing

    def _set_indexing(self, value: bool):
        if self._indexing != value:
            self._indexing = value
            self.indexingChanged.emit()

    @Slot()
    def indexLibrary(self):
        """Scan every folder of the library, subfolders included, on a
        background thread. Safe to call repeatedly: a call while one is
        running just asks for another pass when it finishes."""
        if self._stop.is_set():
            return
        with self._index_lock:
            if self._indexing:
                self._rerun = True
                return
            self._set_indexing(True)
        folders = [covers.folder_key(f) for f in self._db.get_all_folders()]
        self._thread = threading.Thread(target=self._index_worker, args=(folders,), daemon=True)
        self._thread.start()

    def stop_indexing(self):
        """Stop the indexer and wait for it, and keep it stopped. Called before
        the profile's files are released (locking a vault)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=15)

    def _index_worker(self, folders):
        db = None
        try:
            db = Database()   # a connection of its own: sqlite connections are per-thread
            for root in folders:
                for directory in walk_directories(root):
                    if self._stop.is_set():
                        return
                    try:
                        scan_folder(db, Path(directory), content_hash)
                    except (OSError, sqlite3.Error) as e:
                        logger.warning("Indexing %s failed: %s", directory, e)
        except Exception:
            logger.exception("Library indexing failed")
        finally:
            if db is not None:
                db.close()
            with self._index_lock:
                again, self._rerun = self._rerun, False
                self._indexing = False
            self.indexingChanged.emit()
            self.indexFinished.emit()
            if again and not self._stop.is_set():
                self.indexLibrary()

    # ---- queries -----------------------------------------------------------

    def _ranges(self, scope: str):
        if scope:
            return [tag_query.scope_range(os.path.realpath(covers.folder_key(scope)))]
        # The whole library: everything below any of its folders
        return [tag_query.scope_range(os.path.realpath(covers.folder_key(f)))
                for f in self._db.get_all_folders()]

    @Slot(str, result=list)
    def splitTokens(self, text: str) -> list:
        return tag_query.split_tokens(text)

    @Slot(str, str, result=list)
    def search(self, query: str, scope: str) -> list:
        """Media ids matching the query, in natural path order. `scope` is a
        folder (path or file:// URI) to search inside, or '' for the whole library."""
        terms = tag_query.parse(query)
        sql, params = tag_query.build_sql(terms, self._resolver, self._ranges(scope))
        try:
            rows = self._db.run_media_query(sql, params)
        except sqlite3.Error as e:
            logger.error("Search failed (%s): %s", query, e)
            return []
        rows.sort(key=lambda r: covers.natural_key(r[1]))
        return [media_id for media_id, _ in rows]

    # ---- suggestions -------------------------------------------------------

    @Slot(str, result=list)
    def suggest(self, token: str) -> list:
        """Completions for the token being typed. Each is {label, insert,
        category}: `insert` replaces the token (keeping a leading - or ~)."""
        prefix = re.match(r"^[-~]*", token).group(0)
        body = token[len(prefix):]
        out = []
        if ":" in body:
            key, _, value = body.partition(":")
            key = key.lower()
            value = value.lower()
            if key == "type":
                options = ["photo", "video", "manga", "ebook"]
            elif key == "is":
                options = ["favorite"]
            elif key == "rating":
                options = ["general", "suggestive", "mature", "explicit", "unrated"]
            elif key in tag_query.CATEGORIES:
                tags = self._db.search_tags(re.sub(r"\s+", "_", value), limit=30) if value else []
                return [{"label": t["name"], "insert": f'{prefix}{key}:{t["name"]}', "category": key}
                        for t in tags if t["category"] == key][:8]
            else:
                return []
            return [{"label": o, "insert": f"{prefix}{key}:{o}", "category": "meta"}
                    for o in options if o.startswith(value)][:8]

        text = body.lower()
        if not text:
            return []
        for meta in tag_query.METATAGS:
            if meta.startswith(text) and meta != text:
                out.append({"label": meta + ":", "insert": f"{prefix}{meta}:", "category": "meta"})
        try:
            for t in self._db.search_tags(re.sub(r"\s+", "_", text), limit=8):
                out.append({"label": t["name"] + (f'  ({t["alias"]})' if t.get("alias") else ""),
                            "insert": prefix + t["name"], "category": t["category"]})
        except sqlite3.Error:
            pass
        return out[:10]
