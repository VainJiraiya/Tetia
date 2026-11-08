# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
from pathlib import Path

import sqlite3
import os

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QmlElement

from tetia.models import trash
from tetia.models.database import get_database

logger = logging.getLogger(__name__)


QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1


def _trash(path: str) -> "trash.Outcome":
    """Move one file to the system trash (see trash.py for what happens in a Flatpak).
    Kept separate so tests can swap it out."""
    return trash.move_to_trash(path)


@QmlElement
class MediaActions(QObject):
    """File-level actions on media items (as opposed to tagging)."""

    trashProblemChanged = Signal()

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        self._db = get_database()
        self._trash_reason = ""

    # Why the last moveToTrash left files behind, for the dialog QML shows ('' if it did not,
    # or if the cause has nothing to explain)
    @Property(str, notify=trashProblemChanged)
    def trashProblem(self) -> str:
        return trash.explain(self._trash_reason)

    @Property(str, notify=trashProblemChanged)
    def trashFixCommand(self) -> str:
        return trash.fix_command(self._trash_reason)

    def _set_trash_reason(self, reason: str):
        if reason != self._trash_reason:
            self._trash_reason = reason
            self.trashProblemChanged.emit()

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
        first_reason = ""
        for media_id in ids:
            path = paths.get(media_id)
            if path is None:
                continue  # not in the database
            if Path(path).exists():
                outcome = _trash(path)
                if not outcome.ok:
                    logger.error("Could not move to trash (%s): %s", outcome.reason, path)
                    first_reason = first_reason or outcome.reason
                    continue
            removed.append(media_id)
        self._set_trash_reason(first_reason)

        if removed:
            try:
                self._db.delete_media(removed)
            except sqlite3.Error as e:
                logger.error("Trashed files but failed to delete rows: %s", e)
        return removed

    # ---- the file itself (a menu's "Show in file manager", "Copy path", "Rename...") ---------------------------

    @staticmethod
    def _local(location: str) -> str:
        return QUrl(location).toLocalFile() if location.startswith("file:") else location

    @Slot(list)
    def showInFileManager(self, locations: list):
        """Open the file manager on these files' folder with them selected (Dolphin and others do this through
        org.freedesktop.FileManager1); without one, just open the folder."""
        uris = [QUrl.fromLocalFile(self._local(l)).toString() for l in locations]
        if not uris:
            return
        manager = QDBusInterface("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                                 "org.freedesktop.FileManager1", QDBusConnection.sessionBus())
        if manager.isValid():
            reply = manager.call("ShowItems", uris, "")
            if not reply.errorName():
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self._local(locations[0]))))

    @Slot(list)
    def copyPaths(self, locations: list):
        """Put these files' paths on the clipboard, one per line."""
        QGuiApplication.clipboard().setText("\n".join(self._local(l) for l in locations))

    @Slot(str, str, result=str)
    def rename(self, location: str, new_name: str) -> str:
        """Rename a file on disk, in its folder. Returns what went wrong, or "" (the folder's next scan recognises
        the file by its contents, so its tags, favorite and progress stay with it)."""
        path = self._local(location)
        new_name = new_name.strip()
        if not new_name or "/" in new_name or new_name in (".", ".."):
            return "That is not a file name"
        target = os.path.join(os.path.dirname(path), new_name)
        if target == path:
            return ""
        if os.path.exists(target):
            return "There is already a file called \u201C%s\u201D here" % new_name
        try:
            os.rename(path, target)
        except OSError as e:
            return "Couldn't rename it: %s" % e.strerror
        return ""

