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

        if version >= 1:
            return

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

    def close(self):
        self.conn.close()

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

    def upsert_media(self, path: str, name: str, kind: str, size: int, mtime: int, content_hash: str):
        with self.conn:
            self.conn.execute("""
                INSERT INTO media (path, name, kind, size, mtime, content_hash, favorite, rating, missing)
                VALUES (?, ?, ?, ?, ?, ?, 0, NULL, 0)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    size = excluded.size,
                    mtime = excluded.mtime,
                    content_hash = excluded.content_hash,
                    missing = 0
                WHERE media.path = excluded.path
            """, (path, name, kind, size, mtime, content_hash))

    def mark_missing(self, paths):
        if not paths:
            return
        with self.conn:
            placeholders = ",".join("?" for _ in paths)
            self.conn.execute(
                f"UPDATE media SET missing = 1 WHERE missing = 0 AND path NOT IN ({placeholders})",
                tuple(paths)
            )

    def clear_missing(self, path: str):
        with self.conn:
            self.conn.execute("UPDATE media SET missing = 0 WHERE path = ?", (path,))

    def find_missing_by_hash(self, content_hash: str):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, path FROM media WHERE content_hash = ? AND missing = 1 LIMIT 1", (content_hash,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

    def mark_all_missing(self):
        with self.conn:
            self.conn.execute("UPDATE media SET missing = 1")

    def get_media_favorite(self, media_id: int) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT favorite FROM media WHERE id = ?", (media_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def set_media_favorite(self, media_id: int, favorite: bool):
        with self.conn:
            self.conn.execute("UPDATE media SET favorite = ? WHERE id = ?", (1 if favorite else 0, media_id))

    def get_media_rating(self, media_id: int):
        cursor = self.conn.cursor()
        cursor.execute("SELECT rating FROM media WHERE id = ?", (media_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def set_media_rating(self, media_id: int, rating):
        with self.conn:
            self.conn.execute("UPDATE media SET rating = ? WHERE id = ?", (rating, media_id))
