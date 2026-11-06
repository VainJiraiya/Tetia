# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The page of one show (a video folder shown as a series): poster, description, seasons and episodes."""
import logging
import os
import sqlite3

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtQml import QmlElement

from tetia.models import covers, episodes, series
from tetia.models.database import get_database
from tetia.models.scanner import VIDEO_EXTENSIONS

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


def _uri(path: str) -> str:
    return QUrl.fromLocalFile(path).toString(QUrl.FullyEncoded)


@QmlElement
class ShowModel(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._folder = ""
        self._seasons: list = []
        self._description = ""
        self._poster = ""

    def _meta(self) -> dict:
        return self._db.get_collection_meta(self._folder) if self._folder else {}

    @Slot(str)
    def load(self, folder: str):
        """Read the show at `folder` (a path or file:// URI)."""
        self._folder = covers.folder_key(folder)
        self._seasons = [
            {"name": g["name"], "number": g["number"],
             "episodes": [{"uri": _uri(e["path"]), "path": e["path"], "title": e["title"], "number": e["number"],
                           "season": e["season"] if e["season"] is not None else -1} for e in g["episodes"]]}
            for g in episodes.seasons(self._folder)]
        meta = self._meta()
        self._description = meta.get("description") or ""
        self._poster = covers.tile_picture(self._folder, VIDEO_EXTENSIONS, lambda p: self._db.get_collection_meta(
            covers.folder_key(p)))
        self.changed.emit()

    @Property(str, notify=changed)
    def title(self):
        return os.path.basename(self._folder.rstrip(os.sep))

    @Property(str, notify=changed)
    def folderUri(self):
        return covers.folder_uri(self._folder) if self._folder else ""

    @Property(str, notify=changed)
    def poster(self):
        """A picture or video file for the poster (the tile's own picture)."""
        return self._poster

    @Property(str, notify=changed)
    def description(self):
        return self._description

    @Property("QVariantList", notify=changed)
    def seasons(self):
        return self._seasons

    @Property(int, notify=changed)
    def episodeCount(self):
        return sum(len(s["episodes"]) for s in self._seasons)

    @Slot(str)
    def setDescription(self, text: str):
        try:
            self._db.set_collection_description(self._folder, text.strip())
        except sqlite3.Error as e:
            logger.error("Failed to save the description of %s: %s", self._folder, e)
            return
        self._description = text.strip()
        self.changed.emit()

    @Slot(str, result=str)
    def play(self, which: str) -> str:
        """The episode to start: "resume" (where it was left), "first", "next" or "previous"; remembered as the
        last one opened. '' if the show has no episode."""
        return series.open_series(self._db, self._folder, which)

    @Slot(str)
    def played(self, episode_uri: str):
        """An episode was started from the list: resume from it next time."""
        path = QUrl(episode_uri).toLocalFile()
        try:
            self._db.set_collection_last_read(self._folder, path)
        except sqlite3.Error as e:
            logger.error("Failed to remember the episode for %s: %s", self._folder, e)
        self.changed.emit()

    @Property(str, notify=changed)
    def resumeTitle(self):
        """Which episode "Resume" starts, for the button: "S01E03 · title", or '' before any was played."""
        last = self._meta().get("last_read") or ""
        for group in self._seasons:
            for e in group["episodes"]:
                if e["path"] == last:
                    return ("S%02dE%02d" % (e["season"], e["number"]) if e["season"] >= 0 else "E%02d" % e["number"])
        return ""
