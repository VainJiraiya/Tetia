# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The QML face of boards.py: what the board tiles, the board page and the menus ask for. Every change emits
`changed` (with the board's id), so the pages that show boards reload."""
import logging
import sqlite3

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import boards
from tetia.models.database import get_database
from tetia.models.searchModel import _Resolver

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


@QmlElement
class BoardService(QObject):
    changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

    def _db(self):
        return get_database()

    def _try(self, what, fn, fallback=None):
        try:
            return fn()
        except (sqlite3.Error, ValueError) as e:
            logger.error("%s failed: %s", what, e)
            return fallback

    def _summary(self, db, board):
        ids = boards.members(db, _Resolver(db), board["id"])
        return {"id": board["id"], "name": board["name"], "query": board["query"], "tab": board["tab"],
                "layout": board["layout"] or "", "count": len(ids), "collage": boards.collage(db, board["id"], ids)}

    @Slot(str, result=list)
    def boards(self, tab: str) -> list:
        """The boards of a tab, each {id, name, query, tab, layout, count, collage: [three picture paths]}."""
        db = self._db()
        return self._try("Listing boards", lambda: [self._summary(db, b) for b in boards.all_boards(db, tab)], [])

    @Slot(result=list)
    def allBoards(self) -> list:
        db = self._db()
        return self._try("Listing boards", lambda: [self._summary(db, b) for b in boards.all_boards(db)], [])

    @Slot(int, result="QVariantMap")
    def info(self, board_id: int) -> dict:
        db = self._db()
        board = self._try("Reading a board", lambda: boards.get(db, board_id))
        return self._summary(db, board) if board else {}

    @Slot(int, result=list)
    def memberIds(self, board_id: int) -> list:
        db = self._db()
        return self._try("Reading a board", lambda: boards.members(db, _Resolver(db), board_id), [])

    @Slot(str, str, str, result=int)
    def create(self, name: str, query: str, tab: str) -> int:
        board_id = self._try("Making a board", lambda: boards.create(self._db(), name, query, tab), -1)
        if board_id >= 0:
            self.changed.emit(board_id)
        return board_id

    def _change(self, board_id, what, fn):
        if self._try(what, fn, False) is not False:
            self.changed.emit(board_id)

    @Slot(int, str)
    def rename(self, board_id: int, name: str):
        if name.strip():
            self._change(board_id, "Renaming a board", lambda: boards.update(self._db(), board_id, name=name.strip()))

    @Slot(int, str)
    def setQuery(self, board_id: int, query: str):
        self._change(board_id, "Changing a board's search", lambda: boards.update(self._db(), board_id, query=query.strip()))

    @Slot(int, str)
    def setLayout(self, board_id: int, layout: str):
        self._change(board_id, "Changing a board's layout",
                     lambda: boards.update(self._db(), board_id, layout=layout or None))

    @Slot(int, int)
    def setCover(self, board_id: int, media_id: int):
        self._change(board_id, "Changing a board's cover",
                     lambda: boards.update(self._db(), board_id, cover_media_id=media_id if media_id >= 0 else None))

    @Slot(int, list)
    def addMedia(self, board_id: int, media_ids: list):
        """Put these files on the board by hand."""
        self._change(board_id, "Adding to a board", lambda: boards.pin(self._db(), board_id, media_ids, True))

    @Slot(int, list)
    def removeMedia(self, board_id: int, media_ids: list):
        """Take these files off the board, whatever its search finds."""
        self._change(board_id, "Taking off a board", lambda: boards.pin(self._db(), board_id, media_ids, False))

    @Slot(int)
    def remove(self, board_id: int):
        """Delete a board (no file is touched)."""
        self._change(board_id, "Deleting a board", lambda: boards.delete(self._db(), board_id))
