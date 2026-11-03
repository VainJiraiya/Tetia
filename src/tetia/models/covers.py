"""Folder ("collection") covers.

A cover is one of:
- a copy of an image kept in the app's own covers folder, so it survives the
  original being moved. Used for images, for "Choose cover image..." and for
  videos (a full-size frame grabbed with ffmpeg, no film-strip overlay);
- the path of a manga/book file itself, which the thumbnail provider already
  renders as its first page.

Plain module, not a QML element, so main.py needs no changes.
"""
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal

from tetia.models.database import app_data_dir, get_database

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    ".ico", ".svg", ".avif", ".heic", ".heif", ".jxl",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv",
}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


class _CoverNotifier(QObject):
    """One shared signal, so every model that shows collections hears about a
    change made anywhere (the media grid sets a cover, the folder grid redraws
    that tile). The argument is the folder's key (see folder_key)."""
    changed = Signal(str)


notifier = _CoverNotifier()


# ---- Paths ---------------------------------------------------------------

def natural_key(name: str):
    """Sort key that orders digit runs by value ("Chapter 2" < "Chapter 10")."""
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", name)]


def folder_key(path_or_uri: str) -> str:
    """The one spelling of a folder's path used as its database key: a plain,
    normalised local path. Accepts a file:// URI (the form stored in the
    `folders` table) or a plain path (what MediaModel.folderPath holds)."""
    text = (path_or_uri or "").strip()
    if not text:
        return ""
    if text.startswith("file:"):
        text = QUrl(text).toLocalFile() or text
    return os.path.normpath(text)


def folder_uri(key: str) -> str:
    """A file:// URI for a folder key, in the same form FilePicker produces."""
    return QUrl.fromLocalFile(key).toString()


def covers_dir() -> Path:
    path = app_data_dir() / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _in_covers_dir(path: str) -> bool:
    try:
        return Path(path).resolve().parent == covers_dir().resolve()
    except OSError:
        return False


def _new_cover_path(key: str, suffix: str) -> str:
    # A fresh name every time, so a replaced cover never hits a stale thumbnail
    digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:12]
    return str(covers_dir() / f"{digest}_{uuid.uuid4().hex[:8]}{suffix}")


# ---- What a folder tile shows ---------------------------------------------

def first_media_file(local_dir: str, extensions=None, seen=None, depth: int = 0) -> str:
    """The picture for a folder with no cover: the first matching file in
    natural name order, else the first one found inside its subfolders (same
    order), so a folder holding only subfolders borrows a child's picture.
    `seen` (resolved paths) breaks symlink loops; the walk is depth-capped."""
    extensions = extensions or MEDIA_EXTENSIONS
    seen = set() if seen is None else seen
    try:
        real = os.path.realpath(local_dir)
        if real in seen or depth > 8 or not os.path.isdir(local_dir):
            return ""
        seen.add(real)
        files, dirs = [], []
        for entry in os.listdir(local_dir):
            if entry.startswith("."):
                continue
            full_path = os.path.join(local_dir, entry)
            if os.path.isdir(full_path):
                dirs.append(entry)
            elif os.path.isfile(full_path) and Path(entry).suffix.lower() in extensions:
                files.append(entry)
        if files:
            return os.path.join(local_dir, min(files, key=natural_key))
        for entry in sorted(dirs, key=natural_key):
            found = first_media_file(os.path.join(local_dir, entry), extensions, seen, depth + 1)
            if found:
                return found
    except OSError:
        pass
    return ""


def hero_path(key: str, cover_path=None) -> str:
    """The picture for a folder tile: its cover if one is set and still on
    disk, otherwise the first media file inside."""
    if cover_path and os.path.exists(cover_path):
        return cover_path
    return first_media_file(key)


# ---- Setting and clearing -------------------------------------------------

def _store(key: str, new_cover, db) -> bool:
    """Save the cover, delete the previous copy we made, tell the models."""
    try:
        old = db.get_collection_meta(key)["cover_path"]
        db.set_collection_cover(key, new_cover)
    except sqlite3.Error as e:
        logger.error("Failed to save cover for %s: %s", key, e)
        return False
    if old and old != new_cover and _in_covers_dir(old):
        try:
            os.remove(old)
        except OSError:
            pass
    notifier.changed.emit(key)
    return True


def _discard(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def set_cover_from_file(folder: str, image_path: str, db=None) -> bool:
    """Use any image file as the folder's cover (copied into the covers folder)."""
    db = db or get_database()
    key = folder_key(folder)
    src = folder_key(image_path)
    if not key or not src or not os.path.isfile(src):
        return False
    dest = _new_cover_path(key, Path(src).suffix.lower() or ".img")
    try:
        shutil.copyfile(src, dest)
    except OSError as e:
        logger.error("Could not copy cover %s: %s", src, e)
        return False
    if not _store(key, dest, db):
        _discard(dest)
        return False
    return True


def set_cover_from_media(folder: str, media_path: str, kind: str, db=None) -> bool:
    """Use a media item from the folder as its cover.

    image  -> copied as is.
    video  -> a frame grabbed with ffmpeg.
    comic/ebook -> the file itself; its thumbnail is the first page.
    """
    db = db or get_database()
    key = folder_key(folder)
    if not key or not media_path or not os.path.isfile(media_path):
        return False
    if kind == "image":
        return set_cover_from_file(key, media_path, db)
    if kind == "video":
        dest = _new_cover_path(key, ".jpg")
        if not _grab_video_frame(media_path, dest):
            _discard(dest)
            return False
        if not _store(key, dest, db):
            _discard(dest)
            return False
        return True
    return _store(key, media_path, db)


def clear_cover(folder: str, db=None) -> bool:
    """Go back to the default cover (first media file in the folder)."""
    key = folder_key(folder)
    if not key:
        return False
    return _store(key, None, db or get_database())


# ---- Video frames ---------------------------------------------------------

def _video_duration(src: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", src],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _grab_video_frame(src: str, dest: str) -> bool:
    """Write one full-size JPEG frame, about 10% into the video (capped at a
    minute) so it skips intros and black frames. Falls back to the first frame.
    Blocks for a moment; seeking before decoding keeps it quick."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.error("ffmpeg not found; cannot grab a video frame for a cover")
        return False
    duration = _video_duration(src)
    seeks = [min(duration * 0.1, 60.0), 0.0] if duration > 2 else [0.0]
    for seek in seeks:
        cmd = [ffmpeg, "-v", "error", "-y", "-ss", f"{seek:.2f}", "-i", src,
               "-frames:v", "1", "-q:v", "2", dest]
        try:
            subprocess.run(cmd, capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("ffmpeg failed on %s: %s", src, e)
            continue
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return True
    return False
