# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The page of one show (a video folder shown as a series): poster, description, seasons and episodes."""
import logging
import os
import sqlite3

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot, QUrl
from PySide6.QtQml import QmlElement

from tetia.models import covers, episodes, series
from tetia.models.playbackStore import PlaybackStore
from tetia.models.database import get_database
from tetia.models.scanner import VIDEO_EXTENSIONS

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


def _uri(path: str) -> str:
    return QUrl.fromLocalFile(path).toString(QUrl.FullyEncoded)


def format_length(seconds: float) -> str:
    """"45 s", "24 min", "1 h 05 min"; '' when the length is not known."""
    if seconds <= 0:
        return ""
    if seconds < 60:
        return "%d s" % round(seconds)
    minutes = round(seconds / 60)
    return "%d min" % minutes if minutes < 60 else "%d h %02d min" % divmod(minutes, 60)


def format_clock(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "%d:%02d:%02d" % (hours, minutes, secs) if hours else "%d:%02d" % (minutes, secs)


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
        self._store = PlaybackStore(self)
        # lengths arrive one by one from the background probe: show them in batches
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(400)
        self._refresh.timeout.connect(self._refresh_progress)
        self._store.durationsChanged.connect(self._refresh.start)

    def _episodes(self):
        return [e for g in self._seasons for e in g["episodes"]]

    def _decorate(self):
        """Put each episode's progress (watched, how far, how long) next to its name."""
        rows = {r["uri"]: r for r in self._store.episodes([e["uri"] for e in self._episodes()])}
        for e in self._episodes():
            row = rows[e["uri"]]
            e["fraction"], e["finished"], e["length"] = row["fraction"], row["finished"], format_length(row["duration"])

    def _refresh_progress(self):
        self._decorate()
        self.changed.emit()

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
        self._decorate()
        self._store.probe([e["uri"] for e in self._episodes()])         # lengths of the ones not played, in the background
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

    def _resume_episode(self):
        """The episode "Resume" starts (the one last played, or the next if it was watched to the end), or None
        before anything was played."""
        last = self._meta().get("last_read") or ""
        if not last:
            return None
        path = series.skip_finished(self._db, self._folder, last)
        return next((e for e in self._episodes() if e["path"] == path), None)

    @Property(str, notify=changed)
    def resumeTitle(self):
        """Which episode "Resume" starts, for the button: "S01E03", or '' before any was played."""
        e = self._resume_episode()
        if e is None:
            return ""
        return "S%02dE%02d" % (e["season"], e["number"]) if e["season"] >= 0 else "E%02d" % e["number"]

    @Property(str, notify=changed)
    def resumeAt(self):
        """Where in that episode it picks up ("12:10"), or '' when it starts from the beginning."""
        e = self._resume_episode()
        seconds = self._store.resumeFor(e["uri"]) if e else 0
        return format_clock(seconds) if seconds > 0 else ""

    @Slot(str, bool)
    def markWatched(self, episode_uri: str, watched: bool):
        self._store.setWatched(episode_uri, watched)
        self._refresh_progress()
