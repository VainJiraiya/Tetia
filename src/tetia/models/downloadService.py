# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Downloads with gallery-dl, when it is installed (the gallery-dl command, or its Python module as a Flatpak
bundles it): paste an address, choose a library folder, and the files land there with gallery-dl's metadata beside
them, so the scan that follows brings them in with their tags (see gallerydl, tagimport).

gallery-dl reads its own configuration as always (logins, cookies, file names); Tetia passes only where to save and
to write the metadata. Downloads run one at a time, in the order they were added: a hard drive only slows down when
written in several places at once. gallery-dl prints each file it saved, so a download counts its files; it says
nothing of how many will come. Locking a vault stops them first.
"""
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
import threading
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import profiles
from tetia.models.database import Database
from tetia.models.scanner import fingerprint, scan_folder

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

WAITING, DOWNLOADING, DONE, FAILED, CANCELLED = "waiting", "downloading", "done", "failed", "cancelled"


def gallery_dl_command():
    """How to run gallery-dl here: the command, or its Python module; None if neither is installed."""
    exe = shutil.which("gallery-dl")
    if exe:
        return [exe]
    if importlib.util.find_spec("gallery_dl") is not None:
        return [sys.executable, "-m", "gallery_dl"]
    return None


def command_for(base: list, url: str, folder: str) -> list:
    """gallery-dl's arguments for one download: straight into `folder`, with its metadata beside each file."""
    return base + ["--write-metadata", "--no-colors", "-D", folder, "--", url]


@QmlElement
class DownloadService(QObject):
    jobsChanged = Signal()
    downloaded = Signal(str)            # a folder that new files came into (its page reloads)
    _update = Signal(int, str, int, str)  # (job id, state, files, message) from the worker

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: list[dict] = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._worker = None
        self._process = None
        self._cancelled: set[int] = set()
        self._closed = False
        self._update.connect(self._on_update)
        stop = weakref.WeakMethod(self.stop)
        profiles.add_release_hook(lambda: stop() and stop()(), order=0)

    # ---- for QML

    @Property(bool, constant=True)
    def available(self) -> bool:
        return gallery_dl_command() is not None

    @Property("QVariantList", notify=jobsChanged)
    def jobs(self) -> list:
        """[{id, url, folder, state, files, message}], oldest first."""
        with self._lock:
            return [dict(job) for job in self._jobs]

    @Property(bool, notify=jobsChanged)
    def busy(self) -> bool:
        with self._lock:
            return any(job["state"] in (WAITING, DOWNLOADING) for job in self._jobs)

    @Slot(str, str, result=int)
    def add(self, url: str, folder: str) -> int:
        """Queue a download of `url` into `folder` (a path or a file:// address); its id, or 0 if it can't be."""
        url = (url or "").strip()
        path = QUrl(folder).toLocalFile() or folder
        if not url or not path or not os.path.isdir(path) or self._closed or gallery_dl_command() is None:
            return 0
        with self._lock:
            job = {"id": self._next_id, "url": url, "folder": path, "state": WAITING, "files": 0, "message": ""}
            self._next_id += 1
            self._jobs.append(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="downloads", daemon=True)
                self._worker.start()
            self._wake.notify_all()
        self.jobsChanged.emit()
        return job["id"]

    @Slot(int)
    def cancel(self, job_id: int):
        with self._lock:
            for job in self._jobs:
                if job["id"] == job_id and job["state"] in (WAITING, DOWNLOADING):
                    self._cancelled.add(job_id)
                    if job["state"] == WAITING:
                        job["state"] = CANCELLED
                    elif self._process is not None:
                        self._process.terminate()
        self.jobsChanged.emit()

    @Slot()
    def clearFinished(self):
        with self._lock:
            self._jobs = [job for job in self._jobs if job["state"] in (WAITING, DOWNLOADING)]
        self.jobsChanged.emit()

    # ---- the worker

    def _on_update(self, job_id: int, state: str, files: int, message: str):
        folder = ""
        with self._lock:
            for job in self._jobs:
                if job["id"] == job_id:
                    job["state"], job["files"], job["message"] = state, files, message
                    folder = job["folder"]
        self.jobsChanged.emit()
        if state in (DONE, FAILED, CANCELLED) and files > 0:
            self.downloaded.emit(folder)

    def _next(self):
        with self._lock:
            while not self._closed:
                for job in self._jobs:
                    if job["state"] == WAITING:
                        job["state"] = DOWNLOADING
                        return dict(job)
                if not self._wake.wait(timeout=30):
                    return None                       # idle: the thread ends (a new download starts another)
            return None

    def _run(self):
        while True:
            job = self._next()
            if job is None:
                return
            self._update.emit(job["id"], DOWNLOADING, 0, "")
            state, files, message = self._download(job)
            if files:
                self._scan(job["folder"])             # in with their tags, before the page is told
            self._update.emit(job["id"], state, files, message)

    def _download(self, job: dict):
        base = gallery_dl_command()
        if base is None:
            return FAILED, 0, "gallery-dl is not installed"
        files, last_error = 0, ""
        try:
            process = subprocess.Popen(command_for(base, job["url"], job["folder"]), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       errors="replace", cwd=job["folder"])
        except OSError as e:
            return FAILED, 0, "gallery-dl could not be started (%s)" % type(e).__name__
        with self._lock:
            self._process = process
            if job["id"] in self._cancelled or self._closed:
                process.terminate()                   # cancelled while it was starting
        errors = []
        reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
        reader.start()
        for line in process.stdout:
            line = line.strip()
            if line and not line.startswith("#"):     # "# path": already there, skipped
                files += 1
                self._update.emit(job["id"], DOWNLOADING, files, "")
        process.wait()
        reader.join(timeout=5)
        with self._lock:
            self._process = None
            cancelled = job["id"] in self._cancelled or self._closed
        for line in errors:
            if "error" in line.lower():
                last_error = line.strip()
        if cancelled:
            return CANCELLED, files, ""
        if process.returncode != 0:
            return FAILED, files, _short(last_error) or "gallery-dl stopped (exit code %d)" % process.returncode
        return DONE, files, ""

    def _scan(self, folder: str):
        db = None
        try:
            db = Database()
            scan_folder(db, Path(folder), fingerprint)
        except Exception:
            logger.exception("Scanning a download failed")
        finally:
            if db is not None:
                db.close()

    def stop(self):
        """Before a vault is locked: nothing new starts, the download under way is stopped and waited for."""
        with self._lock:
            self._closed = True
            if self._process is not None:
                self._process.terminate()
            self._wake.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=15)


def _short(line: str) -> str:
    """gallery-dl's error line without its "[site][error]" prefix, short enough for a list."""
    text = line.split("]", 2)[-1].strip() if line.startswith("[") else line
    return text[:200]
