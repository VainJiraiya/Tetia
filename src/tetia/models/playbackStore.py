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


def progress_fraction(position: float, duration: float, finished: bool) -> float:
    """How much of a video was watched, for a bar: 1 once watched, 0 when not started (or stopped at the very start)."""
    if finished:
        return 1.0
    if duration <= 0 or position < RESUME_FROM:
        return 0.0
    return min(1.0, position / duration)


def _path(location: str) -> str:
    return QUrl(location).toLocalFile() if location.startswith("file:") else location


def picture_size(width: float, height: float, rotate: float):
    """(width, height) of a video as shown: a quarter turn in its metadata (phone videos) swaps them."""
    if not width or not height:
        return None
    width, height = int(round(width)), int(round(height))
    return (height, width) if int(rotate or 0) % 180 == 90 else (width, height)


class Prober(QObject):
    """Learns, in the background, how long each video is and the size of its picture, for videos the library
    does not know that of yet: one mpv opens each file once. Shared by everything that shows videos (one
    thread, one queue); `learned` is emitted (on the main thread) after each file."""
    learned = Signal()

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._thread = None
        profiles.add_release_hook(self.stop, order=0)

    def needs(self, path: str) -> bool:
        db = get_database()
        found = db.get_media_by_path(os.path.realpath(path))
        if found is None:
            return False
        record = db.get_playback(found[0])
        return not record or record["duration"] <= 0 or db.get_media_size(found[0]) is None

    def request(self, paths: list):
        """Queue the videos among `paths` (local paths) whose length or picture size is not known yet."""
        # by its real path: mpv reports a file under its cleaned-up name (no "..", links followed), and the wait for
        # the file to be loaded compares the two
        wanted = [os.path.realpath(p) for p in paths if self.needs(p)]
        if not wanted or not mpv.available():
            return
        with self._lock:
            self._queue.extend(p for p in wanted if p not in self._queue)
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._worker, name="video-probe", daemon=True)
            self._thread.start()

    def stop(self):
        """Stop and wait (before a vault is locked: it holds the files open)."""
        self._stop.set()
        with self._lock:
            self._queue.clear()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=15)

    def _wait(self, engine, read, seconds):
        end = time.time() + seconds
        while time.time() < end and not self._stop.is_set():
            value = read()
            if value is not None:
                return value
            time.sleep(0.02)
        return None

    def _worker(self):
        db = engine = None
        try:
            db = Database()       # a connection of its own: sqlite connections are per-thread
            engine = mpv.Mpv({"vo": "null", "ao": "null", "terminal": "no", "idle": "yes", "hwdec": "no",
                              "audio-display": "no", "sub-auto": "no", "audio-file-auto": "no", "load-scripts": "no",
                              "pause": "yes"})
            while not self._stop.is_set():
                with self._lock:
                    if not self._queue:
                        self._thread = None       # under the lock: request() starts a new one if it queues more now
                        return
                    path = self._queue.pop(0)
                found = db.get_media_by_path(os.path.realpath(path))
                if found is None or not engine.command("loadfile", path, "replace"):
                    continue
                # until the new file is the current one, mpv still answers for the one before it; a file it can't
                # open leaves it idle (no need to wait the full time for that)
                started = time.time()

                def length_or_failed():
                    if os.path.realpath(engine.get("path") or "") == path:
                        return engine.get_double("duration")
                    if time.time() - started > 0.3 and engine.get_flag("idle-active"):
                        return -1.0
                    return None
                length = self._wait(engine, length_or_failed, 5)
                if length is None or length < 0:
                    continue
                # the shown size comes with the first decoded frame; the stream's own size is the fallback
                size = self._wait(engine, lambda: picture_size(engine.get_double("video-params/dw"),
                                                               engine.get_double("video-params/dh"),
                                                               engine.get_double("video-params/rotate")), 1.5)
                if size is None:
                    size = picture_size(engine.get_double("width"), engine.get_double("height"), 0) or (0, 0)
                try:
                    if length > 0:
                        db.set_duration(found[0], length)
                    db.set_media_size(found[0], *size)     # (0, 0): no picture (sound only); not asked again
                except sqlite3.Error as e:
                    logger.warning("Saving what was learned about a video failed: %s", e)
                    continue
                self.learned.emit()
        except Exception:
            logger.exception("Learning about videos failed")
        finally:
            if engine is not None:
                engine.close()
            if db is not None:
                db.close()


_prober = None


def prober() -> Prober:
    global _prober
    if _prober is None:
        _prober = Prober()
    return _prober


@QmlElement
class PlaybackStore(QObject):
    durationsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        prober().learned.connect(self.durationsChanged)

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

    @Slot(str)
    def restart(self, location: str):
        """Start over (the "Play from beginning" of a video stopped partway): the position goes, the length stays."""
        media_id = self._media_id(location)
        if media_id is None:
            return
        record = self._db.get_playback(media_id)
        try:
            self._db.clear_playback(media_id)
            if record and record["duration"] > 0:
                self._db.set_duration(media_id, record["duration"])
                if record["finished"]:
                    self._db.set_playback(media_id, 0, record["duration"], True)    # watching again does not unwatch it
        except sqlite3.Error as e:
            logger.error("Failed to restart %s: %s", location, e)

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
            fraction = progress_fraction(position, duration, finished)
            out.append({"uri": loc, "position": position, "duration": duration, "finished": finished,
                        "fraction": fraction})
        return out

    @Slot(list)
    def probe(self, locations: list):
        """Find out how long these videos are, in the background (those not known yet); emits durationsChanged."""
        prober().request([_path(loc) for loc in locations])

    def stop_probe(self):
        prober().stop()
