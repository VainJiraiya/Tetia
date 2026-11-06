# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import sqlite3
import threading
import weakref
from pathlib import Path

from tetia.models import profiles

_instance = None


def get_database():
    """Return the shared Database singleton. Created on first call."""
    global _instance
    if _instance is None:
        _instance = Database()
    return _instance


def app_data_dir() -> Path:
    """The active profile's data folder (database, covers). Created on first use.
    General's is $XDG_DATA_HOME/tetia (~/.local/share/tetia); a private profile has its own."""
    return profiles.profile_dir()


def reset_singleton():
    """Close and reset the singleton. For tests only."""
    global _instance
    if _instance is not None:
        try:
            _instance.close()
        except Exception:
            pass
        _instance = None


# Every open Database, with the thread it was made on (sqlite connections may
# only be closed from their own thread), so they can all be closed before a
# vault is locked.
_open_databases: "weakref.WeakSet[Database]" = weakref.WeakSet()


def close_all_databases():
    """Close every database connection made on the calling thread. Used just
    before a vault is locked: an open database file would block the lock."""
    global _instance
    for db in list(_open_databases):
        if db._thread_id == threading.get_ident():
            try:
                db.close()
            except Exception:
                pass
    _instance = None


profiles.add_release_hook(close_all_databases, order=100)


class Database:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = app_data_dir() / "gallery.db"

        # Generous busy timeout: the indexer thread and the UI both write
        self._thread_id = threading.get_ident()
        _open_databases.add(self)
        self.conn = sqlite3.connect(str(db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # WAL keeps UI reads (thumbnail/tag lookups) from blocking behind a scan's
        # write transaction, and NORMAL sync is safe with WAL.
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self._init_tables()
        self._migrate()

    def _write(self, fn, *args):
        """Execute a write statement. Commits only if we started the transaction.
        Rolls back on sqlite3.Error only if we started the transaction, then re-raises.
        Returns the result of fn()."""
        started = not self.conn.in_transaction
        try:
            result = fn(*args)
        except sqlite3.Error:
            if started:
                self.conn.rollback()
            raise
        else:
            if started:
                self.conn.commit()
            return result

    def _init_tables(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    category TEXT NOT NULL,
                    UNIQUE(path, category)
                );
            """)

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS item_metadata (
                    file_path TEXT PRIMARY KEY,
                    is_favorite INTEGER DEFAULT 0,
                    tags TEXT
                );
            """)

    def _migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        steps = (
            (1, self._migrate_v1),
            (2, self._migrate_v2),
            (3, self._migrate_v3),
            (4, self._migrate_v4),
            (5, self._migrate_v5),
            (6, self._migrate_v6),
            (7, self._migrate_v7),
            (8, self._migrate_v8),
            (9, self._migrate_v9),
        )
        for target, step in steps:
            if version < target:
                self._run_migration(target, step)

    def _run_migration(self, target: int, step):
        """Run one migration step and bump user_version in a single transaction.

        Python's sqlite3 doesn't open a transaction before DDL, so without the
        explicit BEGIN a crash mid-migration could leave half the tables created
        and user_version unchanged. The steps also use IF NOT EXISTS, so a
        database left half-migrated by an older build still upgrades cleanly.
        """
        with self.conn:  # commits on success, rolls back on exception
            self.conn.execute("BEGIN")
            step()
            self.conn.execute(f"PRAGMA user_version = {int(target)}")

    def _migrate_v1(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id            INTEGER PRIMARY KEY,
                path          TEXT NOT NULL UNIQUE,
                name          TEXT NOT NULL,
                kind          TEXT NOT NULL CHECK (kind IN ('image','video','comic','ebook')),
                size          INTEGER,
                mtime         INTEGER,
                content_hash  TEXT,
                favorite      INTEGER NOT NULL DEFAULT 0,
                rating        INTEGER CHECK (rating BETWEEN 0 AND 3),
                missing       INTEGER NOT NULL DEFAULT 0
            );
        """)

    def _migrate_v2(self):
        self.conn.execute("CREATE INDEX IF NOT EXISTS media_hash ON media(content_hash)")

    def _migrate_v3(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tag_category (
                id         INTEGER PRIMARY KEY,
                name       TEXT NOT NULL UNIQUE,
                sort_order INTEGER NOT NULL
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tag (
                id          INTEGER PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
                category_id INTEGER NOT NULL REFERENCES tag_category(id),
                description TEXT
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tag_alias (
                alias  TEXT PRIMARY KEY COLLATE NOCASE,
                tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tag_implication (
                antecedent_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
                consequent_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
                PRIMARY KEY (antecedent_id, consequent_id),
                CHECK (antecedent_id <> consequent_id)
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS media_tag (
                media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                tag_id   INTEGER NOT NULL REFERENCES tag(id)   ON DELETE CASCADE,
                source   TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','import')),
                PRIMARY KEY (media_id, tag_id)
            );
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS media_tag_by_tag ON media_tag(tag_id, media_id)")

        # Seed categories in sort order
        self.conn.executemany(
            "INSERT OR IGNORE INTO tag_category (id, name, sort_order) VALUES (?, ?, ?)",
            [
                (1, "creator", 1),
                (2, "series", 2),
                (3, "character", 3),
                (4, "genre", 4),
                (5, "content", 5),
            ]
        )

    def _migrate_v4(self):
        # Per-folder ("collection") settings. Keyed by the folder's plain local
        # path (covers.folder_key), not by the `folders` row, so it keeps
        # working for subfolders once nested collections exist.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS collection (
                path       TEXT PRIMARY KEY,
                cover_path TEXT,
                favorite   INTEGER NOT NULL DEFAULT 0
            );
        """)

    def _migrate_v5(self):
        # A folder can be shown as one series (a tile that opens its chapters);
        # last_read is the chapter file opened last. ALTER has no IF NOT EXISTS,
        # so check the columns first (a half-migrated database must still upgrade).
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(collection)")}
        if "is_series" not in columns:
            self.conn.execute("ALTER TABLE collection ADD COLUMN is_series INTEGER NOT NULL DEFAULT 0")
        if "last_read" not in columns:
            self.conn.execute("ALTER TABLE collection ADD COLUMN last_read TEXT")

    def _migrate_v6(self):
        # View preferences (tile sizes and the like), kept in the profile's own
        # database so a private profile keeps its own and leaves nothing outside it
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS setting (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

    def _migrate_v7(self):
        # The page a user picked as the cover of a comic, EPUB or PDF: an image kept in the
        # profile's covers folder. The thumbnail cache is disposable, so the choice lives here.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS book_cover (
                path       TEXT PRIMARY KEY,
                image_path TEXT NOT NULL
            );
        """)

    def _migrate_v8(self):
        # The reader's memory: where you stopped in each book, and the pages you starred. Both belong to
        # the media row, so they go with it if the file is trashed.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reading_progress (
                media_id INTEGER PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
                page     INTEGER NOT NULL DEFAULT 0,
                offset   REAL    NOT NULL DEFAULT 0,
                total    INTEGER NOT NULL DEFAULT 0,
                finished INTEGER NOT NULL DEFAULT 0,
                updated  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS bookmark (
                media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                page     INTEGER NOT NULL,
                created  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (media_id, page)
            );
        """)

    def _migrate_v9(self):
        # Virtual folders: a place inside a library folder that only exists in Tetia. Where a thing lives is
        # exclusive (one row per item, like a file in a real folder), and everything in a virtual folder
        # belongs to the real folder `home` or below it. A file placed here is moved out of its real folder's
        # grid without touching the disk; deleting the virtual folder gives everything back (see virtualfolders.py).
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS virtual_folder (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT    NOT NULL,
                home           TEXT    NOT NULL,
                parent_id      INTEGER REFERENCES virtual_folder(id) ON DELETE CASCADE,
                cover_media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
                created        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS media_placement (
                media_id   INTEGER PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
                vfolder_id INTEGER NOT NULL REFERENCES virtual_folder(id) ON DELETE CASCADE
            );
        """)
        # a real folder (a subfolder tile, a series, a one-file folder) placed in a virtual folder
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS folder_placement (
                folder     TEXT PRIMARY KEY,
                vfolder_id INTEGER NOT NULL REFERENCES virtual_folder(id) ON DELETE CASCADE
            );
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_vfolder_parent ON virtual_folder(parent_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_vfolder_home ON virtual_folder(home)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_media_placement_folder ON media_placement(vfolder_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_folder_placement_folder ON folder_placement(vfolder_id)")

    def close(self):
        self.conn.close()

    # --- Folders (these run outside scans, so each commits on its own) ---

    def add_folder(self, path: str, category: str):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO folders (path, category) VALUES (?, ?)",
                (path, category)
            )

    def remove_folder(self, path: str):
        with self.conn:
            self.conn.execute("DELETE FROM folders WHERE path = ?", (path,))

    def get_folders_by_category(self, category: str) -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT path, category FROM folders WHERE category = ?", (category,))
        return [dict(row) for row in cursor.fetchall()]

    def get_all_folders(self) -> list[str]:
        """Every folder path in the library (the stored strings, any category)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT path FROM folders")
        return [row[0] for row in cursor.fetchall()]

    # --- Settings: small key/value preferences ---

    def get_setting(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self._write(lambda: self.conn.execute(
            "INSERT INTO setting (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value)))

    # --- Reading progress and bookmarks (the reader) ---

    def get_progress(self, media_id: int):
        """{'page', 'offset', 'total', 'finished'} for a book, or None if it was never opened."""
        row = self.conn.execute(
            "SELECT page, offset, total, finished FROM reading_progress WHERE media_id = ?", (int(media_id),)).fetchone()
        return {"page": row["page"], "offset": row["offset"], "total": row["total"], "finished": bool(row["finished"])} if row else None

    def get_progress_many(self, media_ids) -> dict:
        """{media_id: progress} for the books that have one."""
        ids = [int(i) for i in media_ids]
        out = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                    f"SELECT media_id, page, offset, total, finished FROM reading_progress WHERE media_id IN ({marks})", chunk):
                out[row["media_id"]] = {"page": row["page"], "offset": row["offset"], "total": row["total"],
                                        "finished": bool(row["finished"])}
        return out

    def set_progress(self, media_id: int, page: int, offset: float, total: int, finished: bool):
        """Remember where the reader stopped. Finished stays set once a book has been read to the end."""
        self._write(lambda: self.conn.execute(
            "INSERT INTO reading_progress (media_id, page, offset, total, finished, updated) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(media_id) DO UPDATE SET page = excluded.page, offset = excluded.offset, "
            "total = excluded.total, finished = MAX(finished, excluded.finished), updated = CURRENT_TIMESTAMP",
            (int(media_id), int(page), float(offset), int(total), 1 if finished else 0)))

    def clear_progress(self, media_id: int):
        self._write(lambda: self.conn.execute("DELETE FROM reading_progress WHERE media_id = ?", (int(media_id),)))

    def get_bookmarks(self, media_id: int) -> list:
        return [row["page"] for row in self.conn.execute(
            "SELECT page FROM bookmark WHERE media_id = ? ORDER BY page", (int(media_id),))]

    def add_bookmark(self, media_id: int, page: int):
        self._write(lambda: self.conn.execute(
            "INSERT OR IGNORE INTO bookmark (media_id, page) VALUES (?, ?)", (int(media_id), int(page))))

    def remove_bookmark(self, media_id: int, page: int):
        self._write(lambda: self.conn.execute(
            "DELETE FROM bookmark WHERE media_id = ? AND page = ?", (int(media_id), int(page))))

    # --- Book covers: the page picked as a file's cover ---

    def get_book_cover(self, path: str):
        row = self.conn.execute("SELECT image_path FROM book_cover WHERE path = ?", (path,)).fetchone()
        return row["image_path"] if row else None

    def set_book_cover(self, path: str, image_path: str):
        self._write(lambda: self.conn.execute(
            "INSERT INTO book_cover (path, image_path) VALUES (?, ?) "
            "ON CONFLICT(path) DO UPDATE SET image_path = excluded.image_path", (path, image_path)))

    def clear_book_cover(self, path: str):
        self._write(lambda: self.conn.execute("DELETE FROM book_cover WHERE path = ?", (path,)))

    def delete_setting(self, key: str):
        self._write(lambda: self.conn.execute("DELETE FROM setting WHERE key = ?", (key,)))

    # --- Collections: cover image + favorite per folder ---
    # Each commits on its own. Rows with no cover and no favorite are dropped.

    def get_collection_meta(self, path: str) -> dict:
        """{'cover_path', 'favorite', 'is_series', 'last_read'} (defaults if no row)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT cover_path, favorite, is_series, last_read FROM collection WHERE path = ?", (path,))
        row = cursor.fetchone()
        return self._meta_from_row(row) if row else self._meta_from_row(None)

    @staticmethod
    def _meta_from_row(row) -> dict:
        if row is None:
            return {"cover_path": None, "favorite": False, "is_series": False, "last_read": None}
        return {"cover_path": row["cover_path"], "favorite": bool(row["favorite"]),
                "is_series": bool(row["is_series"]), "last_read": row["last_read"]}

    def get_collections_meta(self, paths) -> dict[str, dict]:
        """get_collection_meta for many paths at once: {path: meta}."""
        paths = list(paths)
        out = {}
        for start in range(0, len(paths), 500):  # stay under SQLite's variable limit
            chunk = paths[start:start + 500]
            marks = ",".join("?" * len(chunk))
            cursor = self.conn.execute(
                f"SELECT path, cover_path, favorite, is_series, last_read FROM collection "
                f"WHERE path IN ({marks})",
                chunk
            )
            for row in cursor.fetchall():
                out[row["path"]] = self._meta_from_row(row)
        return out

    def _tidy_collection(self, path: str):
        self.conn.execute(
            "DELETE FROM collection WHERE path = ? AND favorite = 0 AND cover_path IS NULL "
            "AND is_series = 0",
            (path,)
        )

    def set_collection_favorite(self, path: str, favorite: bool):
        def _do():
            self.conn.execute(
                "INSERT INTO collection (path, favorite) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET favorite = excluded.favorite",
                (path, 1 if favorite else 0)
            )
            self._tidy_collection(path)
        self._write(_do)

    def set_collection_cover(self, path: str, cover_path):
        """Set the cover (a file path), or None to go back to the default."""
        def _do():
            self.conn.execute(
                "INSERT INTO collection (path, cover_path) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET cover_path = excluded.cover_path",
                (path, cover_path)
            )
            self._tidy_collection(path)
        self._write(_do)

    def set_collection_series(self, path: str, is_series: bool):
        def _do():
            self.conn.execute(
                "INSERT INTO collection (path, is_series) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET is_series = excluded.is_series",
                (path, 1 if is_series else 0)
            )
            if not is_series:
                self.conn.execute("UPDATE collection SET last_read = NULL WHERE path = ?", (path,))
            self._tidy_collection(path)
        self._write(_do)

    def set_collection_last_read(self, path: str, chapter_path):
        """Remember the chapter file opened last in a series (None to forget)."""
        self._write(lambda: self.conn.execute(
            "UPDATE collection SET last_read = ? WHERE path = ?", (chapter_path, path)))

    def get_favorite_collections(self) -> list[dict]:
        """Favorited folders as dicts: path, cover_path."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT path, cover_path, is_series FROM collection WHERE favorite = 1")
        return [dict(row) for row in cursor.fetchall()]

    # --- Media scan helpers ---
    # The scan helpers below (get_stored_hash through mark_missing) never commit.
    # The caller (MediaModel.load_from_qurl) wraps a whole scan in one transaction.

    def get_stored_hash(self, path: str, size: int, mtime: int):
        """Return the stored content_hash if a row for this path has the same
        size and mtime (so the file doesn't need rehashing), else ''."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT content_hash FROM media WHERE path = ? AND size = ? AND mtime = ?",
            (path, size, mtime)
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else ""

    def get_media_by_path(self, path: str):
        """Return (id, favorite, rating) for this path, or None if there is no row."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, favorite, rating FROM media WHERE path = ?", (path,))
        row = cursor.fetchone()
        return (row[0], row[1], row[2]) if row else None

    def upsert_media(self, path: str, name: str, kind: str, size: int, mtime: int, content_hash: str):
        """Insert a new row or update the existing row for this path in place
        (id, favorite and rating are kept). Returns (id, favorite, rating)."""
        cursor = self.conn.execute("""
            INSERT INTO media (path, name, kind, size, mtime, content_hash, favorite, rating, missing)
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, 0)
            ON CONFLICT(path) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                size = excluded.size,
                mtime = excluded.mtime,
                content_hash = excluded.content_hash,
                missing = 0
            RETURNING id, favorite, rating
        """, (path, name, kind, size, mtime, content_hash))
        row = cursor.fetchall()[0]
        return (row[0], row[1], row[2])

    def find_missing_by_hash(self, content_hash: str, scanned_paths, exclude_ids=()):
        """Find a row with this content hash whose file is gone, i.e. a rename/move candidate.

        Skips rows whose path was seen in the current scan, rows already claimed
        during this scan, and rows whose file still exists on disk (so an identical
        copy elsewhere is never mistaken for a move). Returns {'id', 'path'} or None.
        """
        if not content_hash:
            return None

        cursor = self.conn.cursor()
        cursor.execute("SELECT id, path FROM media WHERE content_hash = ?", (content_hash,))
        for row in cursor.fetchall():
            if row["id"] in exclude_ids:
                continue
            if row["path"] in scanned_paths:
                continue
            if Path(row["path"]).exists():
                continue
            return {"id": row["id"], "path": row["path"]}
        return None

    def claim_move(self, media_id: int, new_path: str, new_name: str, kind: str,
                   size: int, mtime: int, content_hash: str):
        """Point an existing row at its new path. Keeps id, favorite and rating.
        Returns (id, favorite, rating), or None if the row no longer exists."""
        cursor = self.conn.execute("""
            UPDATE media SET
                path = ?,
                name = ?,
                kind = ?,
                size = ?,
                mtime = ?,
                content_hash = ?,
                missing = 0
            WHERE id = ?
            RETURNING id, favorite, rating
        """, (new_path, new_name, kind, size, mtime, content_hash, media_id))
        rows = cursor.fetchall()
        return (rows[0][0], rows[0][1], rows[0][2]) if rows else None

    def mark_missing(self, folder_path: str, scanned_paths=None):
        """Mark rows that are direct children of folder_path as missing, unless
        their path was seen in this scan (scanned_paths).

        Selects candidate rows with an exact, case-sensitive range query over the
        path index (so _ and % in folder names need no escaping), then filters
        subfolder entries and scanned paths in Python.
        """
        scanned = scanned_paths or ()
        prefix = folder_path.rstrip("/") + "/"
        # Every string starting with `prefix` (which ends in '/') sorts in [prefix, upper)
        upper = prefix[:-1] + chr(ord("/") + 1)

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, path FROM media WHERE missing = 0 AND path >= ? AND path < ?",
            (prefix, upper)
        )
        stale_ids = [
            (row["id"],)
            for row in cursor.fetchall()
            if "/" not in row["path"][len(prefix):] and row["path"] not in scanned
        ]
        if stale_ids:
            self.conn.executemany("UPDATE media SET missing = 1 WHERE id = ?", stale_ids)

    # --- Favorite / rating (called from UI slots, so each commits on its own) ---

    def get_media_favorite(self, media_id: int) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT favorite FROM media WHERE id = ?", (media_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def set_media_favorite(self, media_id: int, favorite: bool):
        self._write(
            self.conn.execute,
            "UPDATE media SET favorite = ? WHERE id = ?",
            (1 if favorite else 0, media_id)
        )

    def get_media_rating(self, media_id: int):
        cursor = self.conn.cursor()
        cursor.execute("SELECT rating FROM media WHERE id = ?", (media_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def set_media_rating(self, media_id: int, rating):
        """Set a rating: 0 General, 1 Suggestive, 2 Mature, 3 Explicit.
        None or any negative value means Unrated and is stored as NULL
        (the UI sends -1; the column's CHECK only allows 0..3 or NULL)."""
        self._write(
            self.conn.execute,
            "UPDATE media SET rating = ? WHERE id = ?",
            (self._normalize_rating(rating), media_id)
        )

    @staticmethod
    def _normalize_rating(rating):
        if rating is None:
            return None
        rating = int(rating)
        if rating < 0:
            return None
        if rating > 3:
            raise ValueError(f"rating must be 0-3, -1 or None, got {rating}")
        return rating

    # --- Tag helpers ---

    def get_category_id(self, category_name: str) -> int | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM tag_category WHERE name = ?", (category_name,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_tag_id(self, tag_name: str) -> int | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM tag WHERE name = ?", (tag_name,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_alias_tag_id(self, alias_name: str) -> int | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT tag_id FROM tag_alias WHERE alias = ?", (alias_name,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_tag_category_name(self, tag_id: int) -> str | None:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT tc.name FROM tag_category tc
            JOIN tag t ON t.category_id = tc.id
            WHERE t.id = ?
        """, (tag_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def insert_tag(self, tag_name: str, category_id: int) -> int:
        """Insert a new tag and return its id. Raises if tag already exists."""
        def _do():
            cursor = self.conn.execute(
                "INSERT INTO tag (name, category_id) VALUES (?, ?) RETURNING id",
                (tag_name, category_id)
            )
            return cursor.fetchone()[0]
        return self._write(_do)

    def insert_media_tag(self, media_id: int, tag_id: int, source: str = "manual"):
        """Link a tag to media. No-op if already linked (INSERT OR IGNORE)."""
        self._write(
            self.conn.execute,
            "INSERT OR IGNORE INTO media_tag (media_id, tag_id, source) VALUES (?, ?, ?)",
            (media_id, tag_id, source)
        )

    # A tag nothing uses and that nothing refers to: no item has it, and it is not an alias target or part of an
    # implication (those were set up on purpose and a tag can be used through them). Such a tag is what is left
    # behind by a misspelling that was typed and then removed.
    _TAG_IN_USE = ("(EXISTS (SELECT 1 FROM media_tag mt WHERE mt.tag_id = {t}.id)"
                   " OR EXISTS (SELECT 1 FROM tag_alias ta WHERE ta.tag_id = {t}.id)"
                   " OR EXISTS (SELECT 1 FROM tag_implication ti WHERE ti.antecedent_id = {t}.id OR ti.consequent_id = {t}.id))")

    def _prune_unused_tags(self, tag_ids):
        """Delete the tags among `tag_ids` that nothing uses (see _TAG_IN_USE). Runs inside the caller's transaction."""
        for tag_id in set(tag_ids):
            self.conn.execute(
                "DELETE FROM tag WHERE id = ? AND NOT " + self._TAG_IN_USE.format(t="tag"), (int(tag_id),))

    def remove_media_tag(self, media_id: int, tag_id: int):
        """Remove a tag link from media. A tag left with nothing using it goes too, so a misspelling does not
        stay behind as a suggestion."""
        def _do():
            self.conn.execute("DELETE FROM media_tag WHERE media_id = ? AND tag_id = ?", (media_id, tag_id))
            self._prune_unused_tags([tag_id])
        self._write(_do)

    # --- Favorites (for the consolidated Favorites tab) ---

    KIND_ORDER = ("image", "video", "comic", "ebook")

    def get_favorites(self) -> list[dict]:
        """All non-missing favorites, grouped by kind (images, videos, comics,
        ebooks) and then by name, so a view can put a section header whenever
        `kind` changes. Returns dicts: id, path, name, kind, rating."""
        order = " ".join(f"WHEN '{k}' THEN {i}" for i, k in enumerate(self.KIND_ORDER))
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT id, path, name, kind, rating
            FROM media
            WHERE favorite = 1 AND missing = 0
            ORDER BY CASE kind {order} ELSE 99 END, name COLLATE NOCASE
        """)
        return [dict(row) for row in cursor.fetchall()]

    # --- Tag reads ---

    def resolve_tag_id(self, tag_name: str) -> int | None:
        """Tag id for a name, falling back to aliases."""
        tag_id = self.get_tag_id(tag_name)
        if tag_id is None:
            tag_id = self.get_alias_tag_id(tag_name)
        return tag_id

    def get_tags_for_media(self, media_id: int) -> list[dict]:
        """Tags on one item, in category order (creator, series, ... content)
        then alphabetical. Returns dicts: id, name, category."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT t.id, t.name, tc.name AS category
            FROM media_tag mt
            JOIN tag t ON t.id = mt.tag_id
            JOIN tag_category tc ON tc.id = t.category_id
            WHERE mt.media_id = ?
            ORDER BY tc.sort_order, t.name
        """, (media_id,))
        return [dict(row) for row in cursor.fetchall()]

    def get_tag_counts(self, media_ids) -> list[dict]:
        """How many of these items carry each tag: [{id, name, category, count}], in category order, then
        most used first, then alphabetical."""
        ids = [int(i) for i in media_ids]
        counts = {}
        for start in range(0, len(ids), 500):       # stay under SQLite's variable limit
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            for row in self.conn.execute(f"""
                SELECT t.id, t.name, tc.name AS category, tc.sort_order AS position, COUNT(*) AS n
                FROM media_tag mt
                JOIN tag t ON t.id = mt.tag_id
                JOIN tag_category tc ON tc.id = t.category_id
                WHERE mt.media_id IN ({marks})
                GROUP BY t.id""", chunk):
                found = counts.setdefault(row["id"], {"id": row["id"], "name": row["name"], "category": row["category"],
                                                      "position": row["position"], "count": 0})
                found["count"] += row["n"]
        ordered = sorted(counts.values(), key=lambda t: (t["position"], -t["count"], t["name"]))
        for tag in ordered:
            del tag["position"]
        return ordered

    def search_tags(self, text: str, limit: int = 10) -> list[dict]:
        """Autocomplete: tags whose name (or alias) starts with or contains `text`.

        Prefix matches rank first, then the most-used tags. `_` and `%` in the
        input are matched literally (stored names are full of underscores).
        Returns dicts: id, name, category (plus `alias` when matched via one).
        """
        text = text.strip()
        if not text:
            return []
        esc = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        prefix, anywhere = esc + "%", "%" + esc + "%"

        in_use = self._TAG_IN_USE.format(t="t")      # leftovers of a removed misspelling are not suggested
        usage = "(SELECT COUNT(*) FROM media_tag mt WHERE mt.tag_id = t.id)"
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT t.id, t.name, tc.name AS category, NULL AS alias,
                   (t.name LIKE ? ESCAPE '\\') AS is_prefix, {usage} AS uses
            FROM tag t JOIN tag_category tc ON tc.id = t.category_id
            WHERE t.name LIKE ? ESCAPE '\\' AND {in_use}
            UNION ALL
            SELECT t.id, t.name, tc.name, a.alias,
                   (a.alias LIKE ? ESCAPE '\\'), {usage}
            FROM tag_alias a
            JOIN tag t ON t.id = a.tag_id
            JOIN tag_category tc ON tc.id = t.category_id
            WHERE a.alias LIKE ? ESCAPE '\\'
        """, (prefix, anywhere, prefix, anywhere))

        best = {}
        for row in cursor.fetchall():
            key = (not row["is_prefix"], -row["uses"], row["name"])
            current = best.get(row["id"])
            if current is None or key < current[0]:
                best[row["id"]] = (key, {
                    "id": row["id"], "name": row["name"], "category": row["category"],
                    **({"alias": row["alias"]} if row["alias"] else {}),
                })
        return [item for _, item in sorted(best.values(), key=lambda p: p[0])[:limit]]

    # --- Tag writes ---

    def get_or_create_tag(self, tag_name: str, category_name: str) -> int | None:
        """Return the id for `tag_name` (resolving aliases), creating it in
        `category_name` if it doesn't exist. None if the category is unknown.
        An existing tag keeps its own category."""
        existing = self.resolve_tag_id(tag_name)
        if existing is not None:
            return existing
        category_id = self.get_category_id(category_name)
        if category_id is None:
            return None
        return self.insert_tag(tag_name, category_id)

    def insert_media_tags(self, media_ids, tag_id: int, source: str = "manual"):
        """Link one tag to many items in ONE transaction (one commit)."""
        rows = [(m, tag_id, source) for m in media_ids]
        self._write(
            self.conn.executemany,
            "INSERT OR IGNORE INTO media_tag (media_id, tag_id, source) VALUES (?, ?, ?)",
            rows
        )

    def remove_media_tags(self, media_ids, tag_id: int):
        """Unlink one tag from many items in ONE transaction (one commit); a tag left unused goes too."""
        def _do():
            self.conn.executemany("DELETE FROM media_tag WHERE media_id = ? AND tag_id = ?",
                                  [(m, tag_id) for m in media_ids])
            self._prune_unused_tags([tag_id])
        self._write(_do)

    # --- Deleting media ---

    # --- Search support ---

    def expand_tag(self, tag_id: int) -> set[int]:
        """The tag plus every tag that implies it (recursively): the set of tags
        that satisfy a search for `tag_id`. Computed at query time, never stored."""
        cursor = self.conn.execute("""
            WITH RECURSIVE satisfying(id) AS (
                SELECT ?
                UNION
                SELECT i.antecedent_id
                FROM tag_implication i JOIN satisfying s ON i.consequent_id = s.id
            )
            SELECT id FROM satisfying
        """, (tag_id,))
        return {row[0] for row in cursor.fetchall()}

    def tag_ids_matching(self, pattern: str, category: str | None = None) -> set[int]:
        """Ids of tags whose name or alias matches a pattern where `*` is a
        wildcard (every other character is literal)."""
        like = "".join("%" if ch == "*" else
                       ("\\" + ch if ch in "\\%_" else ch) for ch in pattern)
        sql = """
            SELECT t.id FROM tag t JOIN tag_category tc ON tc.id = t.category_id
            WHERE (t.name LIKE ? ESCAPE '\\'
                   OR EXISTS (SELECT 1 FROM tag_alias a WHERE a.tag_id = t.id AND a.alias LIKE ? ESCAPE '\\'))
        """
        params = [like, like]
        if category:
            sql += " AND tc.name = ?"
            params.append(category)
        return {row[0] for row in self.conn.execute(sql, params).fetchall()}

    def run_media_query(self, sql: str, params) -> list[tuple[int, str]]:
        """Run a SELECT id, path query built by tag_query: [(id, path), ...]."""
        return [(row[0], row[1]) for row in self.conn.execute(sql, params).fetchall()]

    def get_media_rows(self, media_ids) -> dict[int, dict]:
        """{id: {path, name, kind, favorite, rating}} for the given ids."""
        ids = [int(i) for i in media_ids]
        rows = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            cursor = self.conn.execute(
                f"SELECT id, path, name, kind, favorite, rating FROM media WHERE id IN ({marks})",
                chunk)
            rows.update({row["id"]: dict(row) for row in cursor.fetchall()})
        return rows

    def get_media_paths(self, media_ids) -> dict[int, str]:
        """{id: path} for the given ids (unknown ids are left out)."""
        ids = [int(i) for i in media_ids]
        paths = {}
        for start in range(0, len(ids), 500):  # stay under SQLite's variable limit
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            cursor = self.conn.execute(f"SELECT id, path FROM media WHERE id IN ({marks})", chunk)
            paths.update({row["id"]: row["path"] for row in cursor.fetchall()})
        return paths

    def get_media_info(self, media_id: int):
        """{'path', 'kind'} for one media id, or None if unknown."""
        cursor = self.conn.execute("SELECT path, kind FROM media WHERE id = ?", (int(media_id),))
        row = cursor.fetchone()
        return {"path": row["path"], "kind": row["kind"]} if row else None

    def delete_media(self, media_ids):
        """Delete media rows in ONE transaction. Their tag links go with them
        (media_tag cascades); the tags themselves are kept."""
        self._write(
            self.conn.executemany,
            "DELETE FROM media WHERE id = ?",
            [(int(i),) for i in media_ids]
        )
