# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""View preferences for QML (tile sizes), stored in the active profile's database."""
import logging
import sqlite3

from PySide6.QtCore import QObject, Slot
from PySide6.QtQml import QmlElement

from tetia.models.database import get_database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


@QmlElement
class UiSettings(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()

    @Slot(str, int, result=int)
    def intValue(self, key: str, default: int) -> int:
        try:
            return int(self._db.get_setting(key, default))
        except (sqlite3.Error, ValueError):
            return default

    @Slot(str, int)
    def setIntValue(self, key: str, value: int):
        try:
            self._db.set_setting(key, str(int(value)))
        except sqlite3.Error as e:
            logger.error("Could not save the setting %s: %s", key, e)
