import sqlite3
from pathlib import Path


class Database:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = Path.home() / ".local" / "share" / "GalleryApp"
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = base_dir / "gallery.db"

        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_tables()
        self._migrate()

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
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA user_version")
        version = cursor.fetchone()[0]

        if version < 1:
            with self.conn:
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
                self.conn.execute("PRAGMA user_version = 1")

        if version < 2:
            with self.conn:
                self.conn.execute("CREATE INDEX IF NOT EXISTS media_hash ON media(content_hash)")
                self.conn.execute("PRAGMA user_version = 2")

        if version < 3:
            with self.conn:
                self.conn.execute("""
                    CREATE TABLE tag_category (
                        id         INTEGER PRIMARY KEY,
                        name       TEXT NOT NULL UNIQUE,
                        sort_order INTEGER NOT NULL
                    );
                """)
                self.conn.execute("""
                    CREATE TABLE tag (
                        id          INTEGER PRIMARY KEY,
                        name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        category_id INTEGER NOT NULL REFERENCES tag_category(id),
                        description TEXT
                    );
                """)
                self.conn.execute("""
                    CREATE TABLE tag_alias (
                        alias  TEXT PRIMARY KEY COLLATE NOCASE,
                        tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE
                    );
                """)
                self.conn.execute("""
                    CREATE TABLE tag_implication (
                        antecedent_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
                        consequent_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
                        PRIMARY KEY (antecedent_id, consequent_id),
                        CHECK (antecedent_id <> consequent_id)
                    );
                """)
                self.conn.execute("""
                    CREATE TABLE media_tag (
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
                self.conn.execute("PRAGMA user_version = 3")

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
        in_txn = self.conn.in_transaction
        self.conn.execute("UPDATE media SET favorite = ? WHERE id = ?", (1 if favorite else 0, media_id))
        if not in_txn:
            self.conn.commit()

    def get_media_rating(self, media_id: int):
        cursor = self.conn.cursor()
        cursor.execute("SELECT rating FROM media WHERE id = ?", (media_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def set_media_rating(self, media_id: int, rating):
        in_txn = self.conn.in_transaction
        self.conn.execute("UPDATE media SET rating = ? WHERE id = ?", (rating, media_id))
        if not in_txn:
            self.conn.commit()

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
        in_txn = self.conn.in_transaction
        cursor = self.conn.execute(
            "INSERT INTO tag (name, category_id) VALUES (?, ?) RETURNING id",
            (tag_name, category_id)
        )
        row = cursor.fetchone()[0]
        if not in_txn:
            self.conn.commit()
        return row

    def insert_media_tag(self, media_id: int, tag_id: int, source: str = "manual"):
        """Link a tag to media. No-op if already linked (INSERT OR IGNORE)."""
        in_txn = self.conn.in_transaction
        self.conn.execute(
            "INSERT OR IGNORE INTO media_tag (media_id, tag_id, source) VALUES (?, ?, ?)",
            (media_id, tag_id, source)
        )
        if not in_txn:
            self.conn.commit()

    def remove_media_tag(self, media_id: int, tag_id: int):
        """Remove a tag link from media."""
        in_txn = self.conn.in_transaction
        self.conn.execute(
            "DELETE FROM media_tag WHERE media_id = ? AND tag_id = ?",
            (media_id, tag_id)
        )
        if not in_txn:
            self.conn.commit()
