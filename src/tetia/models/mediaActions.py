# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
from pathlib import Path

import sqlite3
from PySide6.QtCore import QObject, QFile, Slot
from PySide6.QtQml import QmlElement

from tetia.models.database import get_database

logger = logging.getLogger(__name__)


QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1


def _trash(path: str) -> bool:
    """Move one file to the system (freedesktop) trash. Qt handles per-drive
    trash folders and the .trashinfo bookkeeping. Kept separate so tests can
    swap it out."""
    return QFile.moveToTrash(path)


@QmlElement
class MediaActions(QObject):
    """File-level actions on media items (as opposed to tagging)."""

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        self._db = get_database()

    @Slot(list, result=list)
    def moveToTrash(self, media_ids: list) -> list:
        """Move the files to the system trash and drop their database rows
        (tag links and favorites go with them).

        Returns the ids that were removed. A file that is already gone from
        disk counts as removed; one that can't be trashed (permissions,
        read-only mount) is left alone, row included, and is not returned.
        """
        ids = []
        for value in media_ids or []:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue

        try:
            paths = self._db.get_media_paths(ids)
        except sqlite3.Error as e:
            logger.error("Failed to look up media paths: %s", e)
            return []

        removed = []
        for media_id in ids:
            path = paths.get(media_id)
            if path is None:
                continue  # not in the database
            if Path(path).exists() and not _trash(path):
                logger.error("Could not move to trash: %s", path)
                continue
            removed.append(media_id)

        if removed:
            try:
                self._db.delete_media(removed)
            except sqlite3.Error as e:
                logger.error("Trashed files but failed to delete rows: %s", e)
        return removed
