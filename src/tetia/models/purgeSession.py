# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The state of one purge: a deck of images, each kept or marked for the trash.

The images wait in order. The one on top is `current`; deciding it (keep or trash) sends it off
and brings the next waiting one up, and undo brings back the last one decided. Browsing moves
between the images that are still waiting without deciding. Nothing here touches a file: the
trash is only asked for once the user has reviewed the marked images (see the review dialog).
"""
import logging
import sqlite3

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models.database import get_database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

KEEP, TRASH = "keep", "trash"


@QmlElement
class PurgeSession(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._items = {}        # media id -> {"id", "uri", "name", "favorite"}
        self._order = []        # every media id, in the order they are shown
        self._decision = {}     # media id -> "keep" | "trash"
        self._history = []      # media ids in the order they were decided, for undo
        self._pos = 0           # index of the current image among the waiting ones

    # ---- what is waiting ------------------------------------------------------

    def _waiting(self) -> list:
        return [i for i in self._order if i not in self._decision]

    def _current(self):
        waiting = self._waiting()
        return waiting[self._pos] if 0 <= self._pos < len(waiting) else None

    def _clamp(self):
        waiting = self._waiting()
        self._pos = max(0, min(self._pos, len(waiting) - 1)) if waiting else 0

    def _item(self, key, default=""):
        current = self._current()
        return self._items[current][key] if current is not None else default

    # ---- properties for QML --------------------------------------------------------

    @Property(int, notify=changed)
    def total(self):
        return len(self._order)

    @Property(int, notify=changed)
    def pending(self):
        return len(self._waiting())

    @Property(int, notify=changed)
    def trashCount(self):
        return sum(1 for d in self._decision.values() if d == TRASH)

    @Property(int, notify=changed)
    def keepCount(self):
        return sum(1 for d in self._decision.values() if d == KEEP)

    @Property(int, notify=changed)
    def currentId(self):
        current = self._current()
        return -1 if current is None else current

    @Property(str, notify=changed)
    def currentUri(self):
        return self._item("uri")

    @Property(str, notify=changed)
    def currentName(self):
        return self._item("name")

    @Property(bool, notify=changed)
    def currentFavorite(self):
        return bool(self._item("favorite", False))

    @Property(str, notify=changed)
    def nextUri(self):
        """The picture after the current one, so the view can load it ahead of time."""
        waiting = self._waiting()
        index = self._pos + 1
        return self._items[waiting[index]]["uri"] if index < len(waiting) else ""

    @Property(bool, notify=changed)
    def canUndo(self):
        return bool(self._history)

    @Property(bool, notify=changed)
    def canGoBack(self):
        return self._pos > 0

    @Property(bool, notify=changed)
    def canGoForward(self):
        return self._pos < len(self._waiting()) - 1

    @Property(bool, notify=changed)
    def hasProgress(self):
        """Whether anything has been decided yet (cancelling then deserves a question)."""
        return bool(self._decision)

    # ---- actions ---------------------------------------------------------------------------

    @Slot(list, result=bool)
    def start(self, media_ids: list) -> bool:
        """Begin with these media items (in this order). False if none of them is usable."""
        self._items, self._order, self._decision, self._history, self._pos = {}, [], {}, [], 0
        ids = []
        for value in media_ids or []:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        try:
            rows = self._db.get_media_rows(ids)
        except sqlite3.Error as e:
            logger.error("Could not load the images to purge: %s", e)
            rows = {}
        for media_id in ids:
            row = rows.get(media_id)
            if row is None or media_id in self._items:
                continue
            self._items[media_id] = {
                "id": media_id,
                "uri": QUrl.fromLocalFile(row["path"]).toString(QUrl.FullyEncoded),
                "name": row["name"],
                "favorite": bool(row["favorite"]),
            }
            self._order.append(media_id)
        self.changed.emit()
        return bool(self._order)

    @Slot(str)
    def decide(self, decision: str):
        """Keep or trash the current image; the next waiting one comes up."""
        current = self._current()
        if current is None or decision not in (KEEP, TRASH):
            return
        self._decision[current] = decision
        self._history.append(current)
        self._clamp()                   # the next waiting image now sits at the same position
        self.changed.emit()

    @Slot()
    def undo(self):
        """Bring back the image decided last."""
        if not self._history:
            return
        media_id = self._history.pop()
        self._decision.pop(media_id, None)
        self._pos = self._waiting().index(media_id)
        self.changed.emit()

    @Slot()
    def goForward(self):
        if self._pos < len(self._waiting()) - 1:
            self._pos += 1
            self.changed.emit()

    @Slot()
    def goBack(self):
        if self._pos > 0:
            self._pos -= 1
            self.changed.emit()

    @Slot(result=list)
    def trashItems(self) -> list:
        """The images marked for the trash, in the order they were shown, for the review."""
        return [dict(self._items[i]) for i in self._order if self._decision.get(i) == TRASH]

    @Slot(int)
    def keepInstead(self, media_id: int):
        """In the review: keep an image after all."""
        if self._decision.get(media_id) == TRASH:
            self._decision[media_id] = KEEP
            self.changed.emit()

    @Slot(list)
    def forget(self, media_ids: list):
        """Drop images that have left the library (they were moved to the trash)."""
        gone = set()
        for value in media_ids or []:
            try:
                gone.add(int(value))
            except (TypeError, ValueError):
                continue
        self._order = [i for i in self._order if i not in gone]
        for media_id in gone:
            self._items.pop(media_id, None)
            self._decision.pop(media_id, None)
        self._history = [i for i in self._history if i not in gone]
        self._clamp()
        self.changed.emit()
