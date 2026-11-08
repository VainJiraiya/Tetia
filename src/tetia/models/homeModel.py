# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The QML face of home.py: the rows of the Home tab, and pinning things to it."""
import logging
import sqlite3

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtQml import QmlElement

import os

from tetia.models import covers, home
from tetia.models.database import get_database
from tetia.models.searchModel import _Resolver

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


@QmlElement
class HomeModel(QObject):
    pinsChanged = Signal()

    def _rows(self, what, fn):
        try:
            return fn(get_database())
        except sqlite3.Error as e:
            logger.error("Reading %s for Home failed: %s", what, e)
            return []

    @Slot(result=list)
    def continueItems(self):
        return self._rows("what is partway", lambda db: home.continue_items(db))

    @Slot(result=list)
    def pinned(self):
        return self._rows("the pins", lambda db: home.pinned_items(db, _Resolver(db)))

    @Slot(result=list)
    def favorites(self):
        return self._rows("the favorites", lambda db: home.favorite_files(db))

    @Slot(result=list)
    def favoriteCovers(self):
        return self._rows("the favorite collections", lambda db: home.favorite_covers(db))

    @Slot(result=list)
    def library(self):
        return self._rows("the library", lambda db: home.library_summary(db))

    @Slot(result=list)
    def recent(self):
        return self._rows("what was added", lambda db: home.recent_files(db))

    @Slot(str, str, result=bool)
    def isPinned(self, kind: str, ref: str) -> bool:
        try:
            return home.is_pinned(get_database(), kind, ref)
        except sqlite3.Error:
            return False

    @Slot(str, str, bool)
    def setPinned(self, kind: str, ref: str, pinned: bool):
        """Pin a board (its id), a folder or series (its path or file:// address) or a tag (its name) to Home."""
        try:
            (home.pin if pinned else home.unpin)(get_database(), kind, ref)
        except (sqlite3.Error, ValueError) as e:
            logger.error("Pinning failed: %s", e)
            return
        self.pinsChanged.emit()

    @Slot(str, str)
    def unfavorite(self, kind: str, ref: str):
        """Take something out of the favorites: a file (its media id), a book (its path) or a folder (its path)."""
        db = get_database()
        try:
            if kind == "file":
                db.set_media_favorite(int(ref), False)
            elif kind == "book":
                found = db.get_media_by_path(os.path.realpath(ref))
                if found:
                    db.set_media_favorite(found[0], False)
            else:
                key = covers.folder_key(ref)
                db.set_collection_favorite(key, False)
                covers.notifier.changed.emit(key)
        except (sqlite3.Error, ValueError) as e:
            logger.error("Taking out of the favorites failed: %s", e)
            return
        self.pinsChanged.emit()          # (Home reads its rows again)

