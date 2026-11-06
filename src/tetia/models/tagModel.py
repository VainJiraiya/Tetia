# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import re

import sqlite3
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import covers
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


def _folder_path(key) -> str:
    """A folder as the database keys its tags: its real path (what the paths of the files below it start with)."""
    return os.path.realpath(covers.folder_key(str(key))) if key else ""


def _folder_paths(keys) -> list[str]:
    return [p for p in (_folder_path(k) for k in keys or []) if p]


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

    # a tag was added to or removed from some items: what shows tags (the viewer's header) should look again
    tagsChanged = Signal()

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

    @Slot(list, list, result=list)
    def browse(self, media_ids: list, folder_keys: list) -> list:
        """The tags to browse on a page of items and folder tiles: [{category, tags: [{id, name, count}]}] in
        category order, each category's tags most used first. A tag on only one of the items is left out (it would
        lead to nothing more than the item already in view), and so is a category left with none."""
        try:
            counted = self._db.get_tag_counts(_as_ids(media_ids), _folder_paths(folder_keys))
        except sqlite3.Error as e:
            logger.error("Failed to count the tags of a page: %s", e)
            return []
        groups = []
        for tag in counted:
            if tag["count"] < 2 and not tag["on_folder"]:     # a tag on one file is left out; a series was tagged by hand
                continue
            if not groups or groups[-1]["category"] != tag["category"]:
                groups.append({"category": tag["category"], "tags": []})
            groups[-1]["tags"].append({"id": tag["id"], "name": tag["name"], "count": tag["count"]})
        return groups

    @Slot(int, result=list)
    def tagsShown(self, media_id: int) -> list[dict]:
        """The tags to show with a file: its own and those of the folders it lies in (see tagsFor for its own only)."""
        try:
            return self._db.get_tags_shown_for_media(media_id)
        except sqlite3.Error as e:
            logger.error("Failed to get the tags shown for media_id=%d: %s", media_id, e)
            return []

    @Slot(str, result=list)
    def tagsForFolder(self, folder: str) -> list[dict]:
        """The tags a folder carries itself: [{id, name, category}]."""
        try:
            return self._db.get_tags_for_folder(_folder_path(folder))
        except sqlite3.Error as e:
            logger.error("Failed to get the tags of a folder: %s", e)
            return []

    @Slot(list, str, str, result=bool)
    def addTagToFolders(self, folder_keys: list, raw_name: str, category_name: str) -> bool:
        """Give folders a tag: the files below them count as having it in a search, now and when added later."""
        tag_id = self._resolve_tag(raw_name, category_name)
        if tag_id is None:
            return False
        try:
            # only a folder shown as a series takes tags
            keys = [k for k in folder_keys or [] if self._db.get_collection_meta(covers.folder_key(str(k)))["is_series"]]
            self._db.insert_folder_tags(_folder_paths(keys), tag_id)
        except sqlite3.Error as e:
            logger.error("Failed to tag folders: %s", e)
            return False
        self.tagsChanged.emit()
        return True

    @Slot(list, int)
    def removeTagFromFolders(self, folder_keys: list, tag_id: int):
        """Take a tag off folders. A tag that nothing uses any more is removed too."""
        try:
            self._db.remove_folder_tags(_folder_paths(folder_keys), tag_id)
        except sqlite3.Error as e:
            logger.error("Failed to remove a tag from folders: %s", e)
            return
        self.tagsChanged.emit()

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
            self.tagsChanged.emit()
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
            self.tagsChanged.emit()
            return True
        except sqlite3.Error as e:
            logger.error("Failed to bulk-add tag: %s", e)
            return False

    @Slot(int, int)
    def removeTag(self, media_id: int, tag_id: int):
        """Remove a tag link from a media item. A tag that nothing uses any more is removed too."""
        try:
            self._db.remove_media_tag(media_id, tag_id)
            self.tagsChanged.emit()
        except sqlite3.Error as e:
            logger.error("Failed to remove tag from media_id=%d: %s", media_id, e)

    @Slot(list, int)
    def removeTagsFromMedia(self, media_ids: list, tag_id: int):
        """Remove a tag from many media items in a single transaction."""
        try:
            self._db.remove_media_tags(_as_ids(media_ids), tag_id)
            self.tagsChanged.emit()
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
