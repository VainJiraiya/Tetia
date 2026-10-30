import re

from PySide6.QtCore import QObject, Slot
from PySide6.QtQml import QmlElement

from models.database import Database


QML_IMPORT_NAME = "Gallery"
QML_IMPORT_MAJOR_VERSION = 1


def normalize_tag(name: str) -> str:
    """Normalize a tag name for storage and comparison.

    - Strip leading/trailing whitespace
    - Convert to lowercase
    - Collapse internal whitespace to underscores

    Raises ValueError for empty names or names containing forbidden characters.
    """
    name = name.strip().lower()
    if not name:
        raise ValueError("Tag name cannot be empty")

    # Check for forbidden characters
    forbidden = {",", ":", "*", "~"}
    if any(c in name for c in forbidden):
        raise ValueError(f"Tag name contains forbidden character")

    if name.startswith("-"):
        raise ValueError("Tag name cannot start with '-'")

    # Collapse internal whitespace to underscores
    name = re.sub(r"\s+", "_", name)

    return name


@QmlElement
class TagModel(QObject):
    """Service class for tag operations on media items."""

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        self._db = Database()

    @Slot(int, result=list)
    def tagsFor(self, media_id: int) -> list[dict]:
        """Return a list of dicts with tags for a given media_id.

        Returns: [{"id": 1, "name": "isekai", "category": "genre"}, ...]
        """
        cursor = self._db.conn.cursor()
        cursor.execute("""
            SELECT t.id, t.name, tc.name AS category
            FROM media_tag mt
            JOIN tag t ON t.id = mt.tag_id
            JOIN tag_category tc ON tc.id = t.category_id
            WHERE mt.media_id = ?
        """, (media_id,))
        return [{"id": row["id"], "name": row["name"], "category": row["category"]}
                for row in cursor.fetchall()]

    @Slot(int, str, str)
    def addTag(self, media_id: int, raw_name: str, category_name: str) -> bool:
        """Add a tag to a media item.

        Normalizes the name, resolves aliases, creates the tag if missing,
        then links it to the media item. Returns True on success.
        """
        try:
            normalized = normalize_tag(raw_name)
        except ValueError:
            return False

        # Check if this normalized name already exists as a tag
        tag_id = self._db.get_tag_id(normalized)

        # Check if the normalized name is an alias for another tag
        if tag_id is None:
            alias_tag_id = self._db.get_alias_tag_id(normalized)
            if alias_tag_id is not None:
                tag_id = alias_tag_id

        # Get the category id
        cat_id = self._db.get_category_id(category_name)
        if cat_id is None:
            return False

        # Create the tag if it doesn't exist
        if tag_id is None:
            try:
                tag_id = self._db.insert_tag(normalized, cat_id)
            except Exception:
                # Tag might already exist (race condition or UNIQUE violation)
                tag_id = self._db.get_tag_id(normalized)
                if tag_id is None:
                    return False

        # Link the tag to the media item
        try:
            self._db.conn.execute("PRAGMA foreign_keys = ON")
            self._db.insert_media_tag(media_id, tag_id)
            return True
        except Exception:
            return False

    @Slot(list, str, str)
    def addTagsToMedia(self, media_ids: list, raw_name: str, category_name: str):
        """Bulk add a tag to multiple media items in a single transaction."""
        try:
            normalized = normalize_tag(raw_name)
        except ValueError:
            return

        # Check if this normalized name already exists as a tag
        tag_id = self._db.get_tag_id(normalized)

        # Check if the normalized name is an alias for another tag
        if tag_id is None:
            alias_tag_id = self._db.get_alias_tag_id(normalized)
            if alias_tag_id is not None:
                tag_id = alias_tag_id

        # Get the category id
        cat_id = self._db.get_category_id(category_name)
        if cat_id is None:
            return

        # Create the tag if it doesn't exist
        if tag_id is None:
            try:
                tag_id = self._db.insert_tag(normalized, cat_id)
            except Exception:
                tag_id = self._db.get_tag_id(normalized)
                if tag_id is None:
                    return

        # Bulk insert in a single transaction
        in_txn = self._db.conn.in_transaction
        try:
            self._db.conn.execute("PRAGMA foreign_keys = ON")
            for media_id in media_ids:
                self._db.insert_media_tag(media_id, tag_id)
            if not in_txn:
                self._db.conn.commit()
        except Exception:
            if not in_txn:
                self._db.conn.rollback()

    @Slot(int, int)
    def removeTag(self, media_id: int, tag_id: int):
        """Remove a tag link from a media item. The tag itself is preserved."""
        self._db.remove_media_tag(media_id, tag_id)

    @Slot(list, int)
    def removeTagsFromMedia(self, media_ids: list, tag_id: int):
        """Remove a tag from multiple media items in a single transaction."""
        in_txn = self._db.conn.in_transaction
        try:
            for media_id in media_ids:
                self._db.remove_media_tag(media_id, tag_id)
            if not in_txn:
                self._db.conn.commit()
        except Exception:
            if not in_txn:
                self._db.conn.rollback()

    @Slot(str, result=list)
    def suggest(self, prefix: str) -> list[dict]:
        """Return up to 10 tag dicts matching the prefix for autocomplete.

        Returns: [{"id": 1, "name": "isekai", "category": "genre"}, ...]
        """
        cursor = self._db.conn.cursor()
        cursor.execute("""
            SELECT t.id, t.name, tc.name AS category
            FROM tag t
            JOIN tag_category tc ON tc.id = t.category_id
            WHERE t.name LIKE ?
            ORDER BY t.name
            LIMIT 10
        """, (prefix + "%",))
        return [{"id": row["id"], "name": row["name"], "category": row["category"]}
                for row in cursor.fetchall()]
