# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The metadata panel's backend: reads one media item's metadata off the UI thread."""
import logging
import sqlite3

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Property, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import metadata
from tetia.models.database import get_database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)


class _Done(QObject):
    finished = Signal(int, list)


class _Job(QRunnable):
    """ffprobe, zip and PDF reading can take a moment, so they run on a worker thread."""

    def __init__(self, request: int, path: str, kind: str, done: _Done):
        super().__init__()
        self._request, self._path, self._kind, self._done = request, path, kind, done

    def run(self):
        try:
            sections = metadata.read_metadata(self._path, self._kind)
        except Exception as e:      # noqa: BLE001 - never let a worker die silently
            logger.warning("Metadata job failed for %s: %s", self._path, e)
            sections = []
        self._done.finished.emit(self._request, sections)


@QmlElement
class MetadataModel(QObject):
    sectionsChanged = Signal()
    loadingChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()
        self._sections = []
        self._loading = False
        self._request = 0
        self._done = _Done(self)
        self._done.finished.connect(self._on_finished)

    @Property(list, notify=sectionsChanged)
    def sections(self):
        return self._sections

    @Property(bool, notify=loadingChanged)
    def loading(self):
        return self._loading

    def _set_loading(self, value: bool):
        if value != self._loading:
            self._loading = value
            self.loadingChanged.emit()

    @Slot(int)
    def load(self, media_id: int):
        """Read the metadata of this media item (a negative id just clears the panel)."""
        self._request += 1
        row = None
        if media_id >= 0:
            try:
                row = self._db.get_media_rows([media_id]).get(media_id)
            except sqlite3.Error as e:
                logger.error("Could not look up media %s: %s", media_id, e)
        if row is None:
            self._sections = []
            self.sectionsChanged.emit()
            self._set_loading(False)
            return
        self._set_loading(True)
        QThreadPool.globalInstance().start(_Job(self._request, row["path"], row["kind"], self._done))

    @Slot(int, list)
    def _on_finished(self, request: int, sections: list):
        if request != self._request:        # the user moved on to another file
            return
        self._sections = sections
        self.sectionsChanged.emit()
        self._set_loading(False)
