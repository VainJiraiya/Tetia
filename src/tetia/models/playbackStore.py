# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the player remembers about a video: where it was stopped, how long it is, and whether it was watched.

Short videos (clips, under `CLIP_SECONDS`) are not tracked at all: they loop, and always start from the beginning.
A longer one resumes where it stopped, unless it was stopped right at the start or nearly at the end (then it
starts over, and a video watched to the end stays marked as watched). Plain functions at the top, no Qt, so the
rules are easy to test; `PlaybackStore` is the QML face of them.
"""
import logging
import os
import sqlite3
import threading
import time

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import mpv, profiles
from tetia.models.database import Database, get_database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

CLIP_SECONDS = 15 * 60       # shorter than this loops and is never resumed
RESUME_FROM = 30             # stopped before this many seconds: start over
FINISHED_AT = 0.95           # watched this much of it: it counts as watched
REWIND = 3                   # resume a few seconds early, to pick the thread up again


def tracked(duration: float) -> bool:
    return duration >= CLIP_SECONDS


def is_finished(position: float, duration: float) -> bool:
    return tracked(duration) and position >= duration * FINISHED_AT


def resume_position(position: float, duration: float, finished: bool) -> float:
    """Where to start a video that has a record: 0 for a clip, a watched video, or one stopped at the very start."""
    if not tracked(duration) or finished or is_finished(position, duration) or position < RESUME_FROM:
        return 0.0
    return max(0.0, position - REWIND)


def _path(location: str) -> str:
    return QUrl(location).toLocalFile() if location.startswith("file:") else location


@QmlElement
class PlaybackStore(QObject):
    durationsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._thread = None
        profiles.add_release_hook(self.stop_probe, order=0)

    @Property(float, constant=True)
    def clipSeconds(self):
        return float(CLIP_SECONDS)

    def _media_id(self, location: str):
        found = self._db.get_media_by_path(os.path.realpath(_path(location)))
        return found[0] if found else None

    # ---- the player's side ---------------------------------------------------------------------

    @Slot(str, result=float)
    def resumeFor(self, location: str) -> float:
        """Where to start this video (seconds)."""
        media_id = self._media_id(location)
        record = self._db.get_playback(media_id) if media_id is not None else None
        if not record:
            return 0.0
        return resume_position(record["position"], record["duration"], record["finished"])

    @Slot(str, float, float)
    def save(self, location: str, position: float, duration: float):
        """Remember where a video is (clips are not remembered)."""
        if not tracked(duration) or position < 0:
            return
        media_id = self._media_id(location)
        if media_id is None:
            return
        try:
            self._db.set_playback(media_id, position, duration, is_finished(position, duration))
        except sqlite3.Error as e:
            logger.error("Failed to remember the position in %s: %s", location, e)

    @Slot(str, float)
    def markFinished(self, location: str, duration: float = 0.0):
        """The video played to its end."""
        media_id = self._media_id(location)
        if media_id is None:
            return
        record = self._db.get_playback(media_id)
        length = duration or (record["duration"] if record else 0.0)
        if not tracked(length):
            return
        try:
            self._db.set_playback(media_id, 0, length, True)
        except sqlite3.Error as e:
            logger.error("Failed to mark %s watched: %s", location, e)

    @Slot(str, bool)
    def setWatched(self, location: str, watched: bool):
        """By hand: mark a video watched (whatever its length), or unwatched. A length already known is kept."""
        media_id = self._media_id(location)
        if media_id is None:
            return
        record = self._db.get_playback(media_id)
        length = record["duration"] if record else 0.0
        try:
            self._db.clear_playback(media_id)
            if watched:
                self._db.set_playback(media_id, 0, length, True)
            elif length > 0:
                self._db.set_duration(media_id, length)
        except sqlite3.Error as e:
            logger.error("Failed to mark %s: %s", location, e)

    @Slot(str)
    def forget(self, location: str):
        """Back to unwatched, from the start."""
        media_id = self._media_id(location)
        if media_id is not None:
            self._db.clear_playback(media_id)

    # ---- the show page's side ------------------------------------------------------------------

    @Slot(list, result=list)
    def episodes(self, locations: list) -> list:
        """[{uri, position, duration, finished, fraction}] for each of these files ('duration' 0: not known yet)."""
        ids = {loc: self._media_id(loc) for loc in locations}
        records = self._db.get_playback_many([i for i in ids.values() if i is not None])
        out = []
        for loc in locations:
            record = records.get(ids[loc]) if ids[loc] is not None else None
            position = record["position"] if record else 0.0
            duration = record["duration"] if record else 0.0
            finished = bool(record and record["finished"])
            fraction = 1.0 if finished else (min(1.0, position / duration) if duration > 0 and position >= RESUME_FROM else 0.0)
            out.append({"uri": loc, "position": position, "duration": duration, "finished": finished,
                        "fraction": fraction})
        return out

    @Slot(list)
    def probe(self, locations: list):
        """Find out how long these videos are, in the background (those not known yet); emits durationsChanged."""
        wanted = []
        for loc in locations:
            media_id = self._media_id(loc)
            if media_id is None:
                continue
            record = self._db.get_playback(media_id)
            if not record or record["duration"] <= 0:
                wanted.append(_path(loc))
        if not wanted or not mpv.available():
            return
        with self._lock:
            self._queue.extend(p for p in wanted if p not in self._queue)
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._probe_worker, name="duration-probe", daemon=True)
            self._thread.start()

    def stop_probe(self):
        """Stop the probe and wait for it (before a vault is locked: it holds the files open)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=15)

    def _probe_worker(self):
        db = engine = None
        try:
            db = Database()       # a connection of its own: sqlite connections are per-thread
            engine = mpv.Mpv({"vo": "null", "ao": "null", "terminal": "no", "idle": "yes", "hwdec": "no",
                              "audio-display": "no", "sub-auto": "no", "audio-file-auto": "no", "load-scripts": "no",
                              "pause": "yes"})
            while not self._stop.is_set():
                with self._lock:
                    if not self._queue:
                        self._thread = None       # under the lock: probe() starts a new one if it queues more now
                        return
                    path = self._queue.pop(0)
                found = db.get_media_by_path(os.path.realpath(path))
                if found is None or not engine.command("loadfile", path, "replace"):
                    continue
                end = time.time() + 5
                length = None
                while time.time() < end and not self._stop.is_set():
                    # until the new file is the current one, mpv still answers for the one before it
                    if engine.get("path") == path:
                        length = engine.get_double("duration")
                        if length is not None:
                            break
                    time.sleep(0.02)
                if length and length > 0:
                    try:
                        db.set_duration(found[0], length)
                    except sqlite3.Error as e:
                        logger.warning("Saving a length failed: %s", e)
                        continue
                    self.durationsChanged.emit()
        except Exception:
            logger.exception("Finding video lengths failed")
        finally:
            if engine is not None:
                engine.close()
            if db is not None:
                db.close()
