# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The QML face of tag imports: the switch that turns them on and off, and "Re-import tags" for files and folders
(which also reaches files scanned before imports existed). A re-import reads ComicInfo.xml and gallery-dl's
metadata again on a worker thread with a database connection of its own; its replaces each file's imported tags
(a file that no longer says anything loses them) and works a series' out again."""
import logging
import os
import threading
import weakref

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import comicinfo, gallerydl, profiles, tagimport
from tetia.models.database import Database, get_database
from tetia.models.scanner import ALL_MEDIA_EXTENSIONS, COMIC_EXTENSIONS

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

SETTING = "import.tags"


def reimport_folder(db, folder: str, names, listed: set, stop=None) -> int:
    """Import again the tags of these files of `folder` that are in the library; then the folder's, if it is a
    series. How many files were looked at."""
    found, count = [], 0
    for name in names:
        if stop is not None and stop.is_set():
            break
        extension = os.path.splitext(name)[1].lower()
        if name.startswith(".") or extension not in ALL_MEDIA_EXTENSIONS:
            continue
        row = db.get_media_by_path(os.path.realpath(os.path.join(folder, name)))
        if row is None:
            continue                                      # not in the library (yet): its scan will import it
        info = comicinfo.read(os.path.join(folder, name)) if extension in COMIC_EXTENSIONS else tagimport.Imported()
        if not info:
            info = gallerydl.read(folder, name, listed)
        tagimport.apply_to_file(db, row[0], info)
        if info:
            found.append(info)
        count += 1
    common = tagimport.shared(found)
    tagimport.update_series_from_chapters(db, folder, tagimport.Imported(
        rating=common.rating, description=common.description, format=common.format))
    return count


@QmlElement
class TagImportService(QObject):
    enabledChanged = Signal()
    busyChanged = Signal()
    finished = Signal(int)              # how many files were looked at
    _done = Signal(int)                 # (from the worker)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._stop = threading.Event()
        self._done.connect(self._on_done)
        stop = weakref.WeakMethod(self.stop)
        profiles.add_release_hook(lambda: stop() and stop()(), order=0)

    @Property(bool, notify=enabledChanged)
    def enabled(self) -> bool:
        return get_database().get_setting(SETTING, "on") != "off"

    @enabled.setter
    def enabled(self, value: bool):
        if bool(value) != self.enabled:
            get_database().set_setting(SETTING, "on" if value else "off")
            self.enabledChanged.emit()

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @Slot(list)
    def reimport(self, locations: list):
        """Import again the tags of these files and folders (paths or file:// addresses; a folder with everything
        below it), in the background."""
        if self.busy:
            return
        paths = [QUrl(str(l)).toLocalFile() or str(l) for l in locations or []]
        self._stop = threading.Event()
        stop = self._stop

        def work():
            db = None
            count = 0
            try:
                db = Database()
                for path in paths:
                    if stop.is_set():
                        break
                    if os.path.isdir(path):
                        for folder, dirs, files in os.walk(path):
                            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                            count += reimport_folder(db, folder, sorted(files), set(files), stop)
                            if stop.is_set():
                                break
                    elif os.path.isfile(path):
                        folder = os.path.dirname(path)
                        try:
                            listed = set(os.listdir(folder))
                        except OSError:
                            listed = set()
                        count += reimport_folder(db, folder, [os.path.basename(path)], listed, stop)
            except Exception:
                logger.exception("Importing tags again failed")
            finally:
                if db is not None:
                    db.close()
            if not stop.is_set():
                self._done.emit(count)

        self._thread = threading.Thread(target=work, name="tag-reimport", daemon=True)
        self._thread.start()
        self.busyChanged.emit()

    def _on_done(self, count: int):
        self.busyChanged.emit()
        self.finished.emit(count)

    def stop(self):
        """Before a vault is locked: stop, and wait for the file being read."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
