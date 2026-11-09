# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Downloads with gallery-dl (pictures, galleries, booru searches) and yt-dlp (videos), whichever are installed (as a
command, or as a Python module, as a Flatpak bundles them): paste an address, choose a library folder, and the files
land there with their metadata beside them, so the scan that follows brings them in with their tags (see gallerydl,
tagimport). An address of a video site goes to yt-dlp, anything else to gallery-dl; with one of them, it takes all.

Both are run as separate programs and never imported: gallery-dl is GPL-2.0-only. Each reads its own configuration
as always (logins, cookies, file names); Tetia passes only where to save and to write the metadata. Downloads run one at a time, in the order they were added: a hard drive only slows down when
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
from PySide6.QtGui import QDesktopServices
from PySide6.QtQml import QmlElement

from tetia.models import boards, profiles
from tetia.models.database import Database, get_database
from tetia.models.scanner import fingerprint, scan_folder

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

WAITING, DOWNLOADING, DONE, FAILED, CANCELLED = "waiting", "downloading", "done", "failed", "cancelled"


GALLERY_DL, YT_DLP = "gallery-dl", "yt-dlp"

# Where yt-dlp is the tool (videos); anything else goes to gallery-dl, which also takes the videos of the sites it
# knows (X, Reddit, Instagram...)
VIDEO_SITES = ("youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "dailymotion.com", "tiktok.com", "bilibili.com",
               "nicovideo.jp", "streamable.com", "rumble.com", "odysee.com", "bitchute.com", "peertube")


def _command(program: str, module: str):
    exe = shutil.which(program)
    if exe:
        return [exe]
    if importlib.util.find_spec(module) is not None:     # (only looked up, never imported: run in its own process)
        return [sys.executable, "-m", module]
    return None


def gallery_dl_command():
    """How to run gallery-dl here: the command, or its Python module; None if neither is installed."""
    return _command("gallery-dl", "gallery_dl")


def yt_dlp_command():
    return _command("yt-dlp", "yt_dlp")


def tool_commands() -> dict:
    return {GALLERY_DL: gallery_dl_command(), YT_DLP: yt_dlp_command()}


def tool_for(url: str, tools: dict) -> str:
    """The tool for an address: yt-dlp for a video site (or when gallery-dl is missing), else gallery-dl."""
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    video = any(host == site or host.endswith("." + site) or site in host for site in VIDEO_SITES)
    if tools.get(YT_DLP) and (video or not tools.get(GALLERY_DL)):
        return YT_DLP
    return GALLERY_DL if tools.get(GALLERY_DL) else ""


def command_for(base: list, url: str, folder: str, tool: str = GALLERY_DL, first: int = 0, last: int = 0,
                height: int = 0) -> list:
    """A tool's arguments for one download: straight into `folder`, with its metadata beside each file, printing the
    path of every file it saved (so they can be counted). `first`/`last` (1-based, 0: open) keep only those results
    of a search, gallery or playlist; `height` caps a video's resolution (yt-dlp; 0: the best there is)."""
    span = "%s-%s" % (first or "", last or "") if (first or last) else ""
    if tool == YT_DLP:
        extra = ["--playlist-items", span.replace("-", ":")] if span else []
        extra += ["-S", "res:%d" % height] if height > 0 else []
        return base + ["--write-info-json", "--write-subs", "--no-simulate", "--print", "after_move:filepath",
                       "--no-colors", "-P", folder, "-o", "%(title)s [%(id)s].%(ext)s"] + extra + ["--", url]
    extra = ["--range", span] if span else []
    # extractor.tags: the boorus that only give one string of tags (Gelbooru, Moebooru...) fetch each post's page
    # for their categories (tags_artist, tags_character, tags_copyright, tags_general), so the import can sort them
    # (one more request a post; a site's own setting in the user's configuration still wins)
    return base + ["--write-metadata", "--no-colors", "-o", "extractor.tags=true", "-D", folder] + extra + ["--", url]


def clean_folder_name(name: str) -> str:
    """A name usable as one new folder ("" if not): no path separators, not "." or "..", no leading dot."""
    name = (name or "").strip().replace("/", "-").replace("\\", "-")
    return "" if name in ("", ".", "..") or name.startswith(".") else name[:120]


@QmlElement
class DownloadService(QObject):
    jobsChanged = Signal()
    downloaded = Signal(str)            # a folder that new files came into (its page reloads)
    boardFilled = Signal(int)           # a board that downloaded files were put on
    maxHeightChanged = Signal()
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
        return any(tool_commands().values())

    @Property("QStringList", constant=True)
    def tools(self) -> list:
        """The download tools installed ("gallery-dl", "yt-dlp")."""
        return [name for name, command in tool_commands().items() if command]

    @Property("QVariantList", notify=jobsChanged)
    def jobs(self) -> list:
        """[{id, url, folder, tool, state, files, message}], oldest first."""
        with self._lock:
            return [dict(job) for job in self._jobs]

    @Property(bool, notify=jobsChanged)
    def busy(self) -> bool:
        with self._lock:
            return any(job["state"] in (WAITING, DOWNLOADING) for job in self._jobs)

    @Slot(str, str, result=int)
    def add(self, url: str, folder: str) -> int:
        return self.addWith(url, folder, "")

    @Slot(str, str, str, result=int)
    def addWith(self, url: str, folder: str, tool: str) -> int:
        return self.download(url, folder, tool, {})

    @Slot(str, str, str, "QVariantMap", result=int)
    def download(self, url: str, folder: str, tool: str, options) -> int:
        """Queue a download of `url` into `folder` (a path or a file:// address) with `tool` ("" chooses by the
        address); its id, or 0 if it can't be. `options` (all optional):
            subfolder   a new folder of that name inside `folder`, to save into instead
            board       a board's id to put the files on, or boardName: a new board of that name (in `tab`)
            first/last  only those results (1-based); height: the highest video resolution (yt-dlp)"""
        options = dict(options or {})
        url = (url or "").strip()
        path = QUrl(folder).toLocalFile() or folder
        tools = tool_commands()
        tool = tool if tools.get(tool) else tool_for(url, tools)
        if not url or not path or not os.path.isdir(path) or self._closed or not tool:
            return 0
        sub = clean_folder_name(str(options.get("subfolder") or ""))
        if sub:
            path = os.path.join(path, sub)
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                return 0

        def number(key):
            try:
                return max(0, int(options.get(key) or 0))
            except (TypeError, ValueError):
                return 0
        height = number("height") if "height" in options else self.maxHeight
        with self._lock:
            job = {"id": self._next_id, "url": url, "folder": path, "tool": tool, "state": WAITING, "files": 0,
                   "message": "", "first": number("first"), "last": number("last"), "height": height,
                   "board": number("board"), "boardName": str(options.get("boardName") or "").strip(),
                   "tab": str(options.get("tab") or "")}
            self._next_id += 1
            self._jobs.append(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="downloads", daemon=True)
                self._worker.start()
            self._wake.notify_all()
        self.jobsChanged.emit()
        return job["id"]

    @Property(int, notify=maxHeightChanged)
    def maxHeight(self) -> int:
        """The highest video resolution yt-dlp fetches by default (0: the best there is); remembered."""
        try:
            return int(get_database().get_setting("download.height", "0") or 0)
        except ValueError:
            return 0

    @maxHeight.setter
    def maxHeight(self, value: int):
        if int(value) != self.maxHeight:
            get_database().set_setting("download.height", str(int(value)))
            self.maxHeightChanged.emit()

    # ---- the tools' own configuration (logins, API keys, file names): opened, never read for its values

    @staticmethod
    def _config_file(tool: str) -> str:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(base, "gallery-dl", "config.json") if tool == GALLERY_DL else os.path.join(base, "yt-dlp", "config")

    @Slot(str, result=bool)
    def hasConfig(self, tool: str) -> bool:
        return os.path.isfile(self._config_file(tool))

    @Slot(result="QStringList")
    def gallerySites(self) -> list:
        """The sites gallery-dl's configuration has a section for (their names only, never what is in them)."""
        import json
        try:
            with open(self._config_file(GALLERY_DL), "rb") as f:
                extractor = json.loads(f.read()).get("extractor", {})
        except (OSError, ValueError, AttributeError):
            return []
        return sorted(k for k, v in extractor.items() if isinstance(v, dict) and not k.startswith("#")) \
            if isinstance(extractor, dict) else []

    @Slot(str)
    def openConfig(self, tool: str):
        """Open a tool's configuration in the text editor, made first if there is none (gallery-dl's own starting
        file; an empty one, with a pointer to the options, for yt-dlp)."""
        path = self._config_file(tool)
        if not os.path.isfile(path):
            try:
                if tool == GALLERY_DL and gallery_dl_command():
                    subprocess.run(gallery_dl_command() + ["--config-create"], stdin=subprocess.DEVNULL,
                                   capture_output=True, timeout=30)
                if not os.path.isfile(path):
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w") as f:
                        f.write("{}\n" if tool == GALLERY_DL else
                                "# yt-dlp options, one per line (see yt-dlp --help), for example:\n# --cookies-from-browser firefox\n")
            except (OSError, subprocess.SubprocessError):
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

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
            state, files, message, saved = self._download(job)
            board = 0
            if saved:
                board = self._scan(job, saved)        # in with their tags (and on their board), before the page is told
            self._update.emit(job["id"], state, files, message)
            if board:
                self.boardFilled.emit(board)

    def _download(self, job: dict):
        base = tool_commands().get(job["tool"])
        if base is None:
            return FAILED, 0, "%s is not installed" % job["tool"], []
        files, last_error, saved = 0, "", []
        try:
            process = subprocess.Popen(command_for(base, job["url"], job["folder"], job["tool"], job["first"],
                                                   job["last"], job["height"]), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       errors="replace", cwd=job["folder"])
        except OSError as e:
            return FAILED, 0, "%s could not be started (%s)" % (job["tool"], type(e).__name__), []
        with self._lock:
            self._process = process
            if job["id"] in self._cancelled or self._closed:
                process.terminate()                   # cancelled while it was starting
        errors = []
        reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
        reader.start()
        for line in process.stdout:
            line = line.strip()
            if line.startswith("# "):                 # "# path": already there, skipped (still the board's)
                saved.append(line[2:].strip())
            elif line:
                saved.append(line)
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
            return CANCELLED, files, "", saved
        if process.returncode != 0:
            return (FAILED, files, _short(last_error) or "%s stopped (exit code %d)" % (job["tool"], process.returncode),
                    saved)
        return DONE, files, "", saved

    def _scan(self, job: dict, saved: list) -> int:
        """Scan the folder the files came into, then put them on the board asked for (made now if new): its id,
        or 0."""
        db = None
        board = 0
        try:
            db = Database()
            scan_folder(db, Path(job["folder"]), fingerprint)
            if job["board"] or job["boardName"]:
                ids = []
                for path in saved:
                    found = db.get_media_by_path(os.path.realpath(path))
                    if found is not None and found[0] not in ids:
                        ids.append(found[0])
                if ids:
                    board = job["board"] if job["board"] and boards.get(db, job["board"]) else \
                        boards.create(db, job["boardName"] or "Downloads", "", job["tab"])
                    boards.pin(db, board, ids)
        except Exception:
            logger.exception("Scanning a download failed")
        finally:
            if db is not None:
                db.close()
        return board

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
    """A tool's error line without its prefix (gallery-dl's "[site][error]", yt-dlp's "ERROR: [site] id:"), short
    enough for a list."""
    text = line.strip()
    if text.startswith("ERROR:"):
        text = text[len("ERROR:"):].strip()
    while text.startswith("["):
        text = text.split("]", 1)[-1].strip()
    return text[:200]
