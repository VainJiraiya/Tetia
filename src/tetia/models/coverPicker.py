# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Choosing the cover of a comic, EPUB or PDF by hand (the picker dialog's backend).

The picked page is kept as an image in the profile's covers folder and remembered in the
database, so clearing the thumbnail cache cannot lose it; the file's cached thumbnails
are deleted and made again from the pick the next time the tile is drawn."""
import logging
import os
import sqlite3

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQml import QmlElement

from tetia.models import bookpages, covers, thumbModel
from tetia.models.database import get_database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


def _on_white(image: QImage) -> QImage:
    """A cover is saved without transparency."""
    paper = QImage(image.size(), QImage.Format.Format_RGB32)
    paper.fill(0xFFFFFFFF)
    painter = QPainter(paper)
    painter.drawImage(0, 0, image)
    painter.end()
    return paper


@QmlElement
class CoverPicker(QObject):
    stateChanged = Signal()
    # the cover of this file (a plain path) was changed or reset: tiles showing it must reload
    coverChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._path = ""
        self._refs = []
        self._token = ""
        self._title = ""
        self._message = ""
        self._custom = False

    # ---- what the dialog shows ----------------------------------------------------

    @Property(int, notify=stateChanged)
    def count(self):
        return len(self._refs)

    @Property(str, notify=stateChanged)
    def token(self):
        return self._token

    @Property(str, notify=stateChanged)
    def title(self):
        return self._title

    @Property(str, notify=stateChanged)
    def message(self):
        return self._message

    @Property(bool, notify=stateChanged)
    def custom(self):
        return self._custom

    # ---- actions ----------------------------------------------------------------------------

    @Slot(int, result=bool)
    def open(self, media_id: int) -> bool:
        """Load the pages of this media item. False if it is not a file in the library."""
        try:
            row = self._db.get_media_rows([media_id]).get(media_id)
        except sqlite3.Error as e:
            logger.error("Could not look up media %s: %s", media_id, e)
            row = None
        if row is None:
            self.close()
            return False
        return self._load(row["path"], row["name"])

    @Slot(str, result=bool)
    def openPath(self, path: str) -> bool:
        """Load the pages of the file at this path (a plain path or a file:// URI)."""
        path = covers.folder_key(path)
        if not os.path.isfile(path):
            self.close()
            return False
        return self._load(path, os.path.basename(path))

    def _load(self, path: str, title: str) -> bool:
        self.close()
        self._path = path
        self._title = title
        self._refs, self._message = bookpages.list_pages(self._path)
        self._token = bookpages.register(self._path, self._refs) if self._refs else ""
        try:
            self._custom = self._db.get_book_cover(self._path) is not None
        except sqlite3.Error:
            self._custom = False
        self.stateChanged.emit()
        return True

    @Slot()
    def close(self):
        if self._token:
            bookpages.unregister(self._token)
        self._path, self._refs, self._token, self._title, self._message = "", [], "", "", ""
        self._custom = False
        self.stateChanged.emit()

    def _forget_old(self, old):
        if old and covers._in_covers_dir(old):
            covers._discard(old)

    @Slot(int, result=bool)
    def choose(self, index: int) -> bool:
        """Use page `index` as the cover of the open file."""
        if not self._path or not 0 <= index < len(self._refs):
            return False
        image = bookpages.read_page(self._path, self._refs[index], bookpages.CHOSEN_EDGE)
        if image.isNull():
            return False
        if image.hasAlphaChannel():
            image = _on_white(image)
        target = covers._new_cover_path("book:" + self._path, ".jpg")
        if not image.save(target, "JPEG", 92):
            covers._discard(target)
            return False
        try:
            old = self._db.get_book_cover(self._path)
            self._db.set_book_cover(self._path, target)
        except sqlite3.Error as e:
            logger.error("Could not save the cover of %s: %s", self._path, e)
            covers._discard(target)
            return False
        self._forget_old(old)
        thumbModel.forget_thumbnails(self._path)
        self._custom = True
        self.stateChanged.emit()
        self.coverChanged.emit(self._path)
        return True

    @Slot(result=bool)
    def useAutomatic(self) -> bool:
        """Forget the hand-picked page: the cover is chosen automatically again."""
        if not self._path:
            return False
        try:
            old = self._db.get_book_cover(self._path)
            self._db.clear_book_cover(self._path)
        except sqlite3.Error as e:
            logger.error("Could not reset the cover of %s: %s", self._path, e)
            return False
        self._forget_old(old)
        thumbModel.forget_thumbnails(self._path)
        self._custom = False
        self.stateChanged.emit()
        self.coverChanged.emit(self._path)
        return True
