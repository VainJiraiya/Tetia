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
        self._init_tables()

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