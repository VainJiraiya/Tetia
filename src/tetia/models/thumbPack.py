# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""A private profile's thumbnails in one file (no Qt).

The freedesktop cache is one small file per thumbnail. In a vault on a hard drive each of those costs several seeks
(measured through gocryptfs: 28-36 ms a thumbnail, about 6 disk reads for an 85 KB file), so a private profile keeps
them in one SQLite file in its folder instead: one open file, and the thumbnails of a page, made together, lie
together on the disk. General keeps the shared freedesktop folders, which other apps read too.

Each row holds the PNG exactly as the freedesktop cache would (with its Thumb::URI and Thumb::MTime), keyed by the
same MD5 of the file's URI and the tier's folder name ("normal", "large", "x-large", "xx-large").
"""
import logging
import sqlite3
import threading
from pathlib import Path

from tetia.models import profiles

logger = logging.getLogger(__name__)

# Bigger pages than SQLite's 4 KB: a thumbnail spans a few pages instead of a few dozen (set when the file is made)
PAGE_SIZE = 32768


class ThumbPack:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn = None
        self._closed = False
        self._lock = threading.Lock()      # one connection, used from Qt's loader threads one at a time

    def _db(self):
        if self._conn is None and not self._closed:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
            conn.execute(f"PRAGMA page_size = {PAGE_SIZE}")       # (only takes on a new, empty file)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("CREATE TABLE IF NOT EXISTS thumb (hash TEXT NOT NULL, tier TEXT NOT NULL, "
                         "png BLOB NOT NULL, PRIMARY KEY (hash, tier))")
            conn.commit()
            self._conn = conn
        return self._conn

    def get(self, uri_md5: str) -> dict:
        """Every tier kept of one file: {tier: PNG bytes} (empty if none, or if the pack can't be read)."""
        with self._lock:
            try:
                db = self._db()
                if db is None:
                    return {}
                return {tier: bytes(png) for tier, png in
                        db.execute("SELECT tier, png FROM thumb WHERE hash = ?", (uri_md5,))}
            except sqlite3.Error as e:
                logger.error("Reading the thumbnails failed: %s", e)
                return {}

    def put(self, uri_md5: str, tier: str, png: bytes) -> bool:
        with self._lock:
            try:
                db = self._db()
                if db is None:
                    return False
                db.execute("INSERT OR REPLACE INTO thumb (hash, tier, png) VALUES (?, ?, ?)", (uri_md5, tier, png))
                db.commit()
                return True
            except sqlite3.Error as e:
                logger.error("Keeping a thumbnail failed: %s", e)
                return False

    def forget(self, uri_md5: str):
        """Drop every tier of one file (its cover was changed by hand)."""
        with self._lock:
            try:
                db = self._db()
                if db is not None:
                    db.execute("DELETE FROM thumb WHERE hash = ?", (uri_md5,))
                    db.commit()
            except sqlite3.Error as e:
                logger.error("Forgetting a thumbnail failed: %s", e)

    def close(self):
        """Let go of the file (the vault is about to be locked); later calls find nothing."""
        with self._lock:
            self._closed = True
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None


_current = None
_current_lock = threading.Lock()


def pack():
    """The active profile's pack, or None for General (the freedesktop folders)."""
    global _current
    path = profiles.thumbnail_pack()
    with _current_lock:
        if path is None:
            return None
        if _current is None or _current.path != path:
            if _current is not None:
                _current.close()
            _current = ThumbPack(path)
        return _current


def _close_current():
    with _current_lock:
        if _current is not None:
            _current.close()


# With the databases: after the thumbnail loader has stopped (order 0)
profiles.add_release_hook(_close_current, order=100)
