import logging
import re

import sqlite3
from PySide6.QtCore import QObject, Slot
from PySide6.QtQml import QmlElement

from tetia.models.database import get_database

logger = logging.getLogger(__name__)


QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

# Characters that would break tag syntax in search ("a,b", "creator:x", "x*", "~x", "-x").
# TagPanel.qml checks the same rules so it can show an error instead of failing silently.
FORBIDDEN_CHARS = {",", ":", "*", "~"}


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

    if any(c in name for c in FORBIDDEN_CHARS):
        raise ValueError("Tag name contains a forbidden character")

    if name.startswith("-"):
        raise ValueError("Tag name cannot start with '-'")

    # Collapse internal whitespace to underscores
    return re.sub(r"\s+", "_", name)


def _as_ids(media_ids) -> list[int]:
    """QML hands lists over as Python lists of int/float; coerce and drop junk."""
    ids = []
    for value in media_ids or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


@QmlElement
class TagModel(QObject):
    """Service class for tag operations on media items."""

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        self._db = get_database()

    @Slot(int, result=list)
    def tagsFor(self, media_id: int) -> list[dict]:
        """Return the tags on a media item, ordered by category then name.

        Returns: [{"id": 1, "name": "isekai", "category": "genre"}, ...]
        """
        try:
            return self._db.get_tags_for_media(media_id)
        except sqlite3.Error as e:
            logger.error("Failed to get tags for media_id=%d: %s", media_id, e)
            return []

    def _resolve_tag(self, raw_name: str, category_name: str) -> int | None:
        """Normalize, resolve aliases and create the tag if needed.
        Returns the tag id, or None if the name/category is invalid."""
        try:
            normalized = normalize_tag(raw_name)
        except ValueError:
            return None
        try:
            return self._db.get_or_create_tag(normalized, category_name)
        except sqlite3.Error as e:
            logger.error("Failed to create tag %r: %s", normalized, e)
            return None

    @Slot(int, str, str, result=bool)
    def addTag(self, media_id: int, raw_name: str, category_name: str) -> bool:
        """Add a tag to a media item. Returns True on success, False if the
        name is invalid, the category is unknown, or the write failed."""
        tag_id = self._resolve_tag(raw_name, category_name)
        if tag_id is None:
            return False
        try:
            self._db.insert_media_tag(media_id, tag_id)
            return True
        except sqlite3.Error as e:
            logger.error("Failed to add tag to media_id=%d: %s", media_id, e)
            return False

    @Slot(list, str, str, result=bool)
    def addTagsToMedia(self, media_ids: list, raw_name: str, category_name: str) -> bool:
        """Add one tag to many media items in a single transaction.
        All-or-nothing; returns True on success."""
        tag_id = self._resolve_tag(raw_name, category_name)
        if tag_id is None:
            return False
        try:
            self._db.insert_media_tags(_as_ids(media_ids), tag_id)
            return True
        except sqlite3.Error as e:
            logger.error("Failed to bulk-add tag: %s", e)
            return False

    @Slot(int, int)
    def removeTag(self, media_id: int, tag_id: int):
        """Remove a tag link from a media item. The tag itself is preserved."""
        try:
            self._db.remove_media_tag(media_id, tag_id)
        except sqlite3.Error as e:
            logger.error("Failed to remove tag from media_id=%d: %s", media_id, e)

    @Slot(list, int)
    def removeTagsFromMedia(self, media_ids: list, tag_id: int):
        """Remove a tag from many media items in a single transaction."""
        try:
            self._db.remove_media_tags(_as_ids(media_ids), tag_id)
        except sqlite3.Error as e:
            logger.error("Failed to bulk-remove tag: %s", e)

    @Slot(str, result=list)
    def suggest(self, text: str) -> list[dict]:
        """Autocomplete for the tag input: up to 10 tags whose name or alias
        starts with / contains the text, best matches first.

        The text is normalized the same way stored names are (so "john sm"
        finds "john_smith"). Returns: [{"id", "name", "category"}, ...]
        """
        text = re.sub(r"\s+", "_", text.strip().lower())
        if not text:
            return []
        try:
            return self._db.search_tags(text, limit=10)
        except sqlite3.Error as e:
            logger.error("Failed to suggest tags: %s", e)
            return []
