# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickImageProvider

from tetia.models import profiles

# Characters left unescaped when building the thumbnail-cache URI. The MD5 of
# this URI is the cache filename, so it has to match what Dolphin/KDE hashes
# or lookups miss. This is the RFC 2396 path set that glib's
# g_filename_to_uri() uses: the unreserved chars ("-_.!~*'()" plus
# alphanumerics, the last few handled by quote() itself) PLUS the pchar extras
# ":@&=+$," and the ";" path-parameter delimiter. Leaving any of those out
# percent-encodes them (e.g. "," -> %2C), which changes the hash for every
# filename containing that character. "[", "]", "^", "#", "%", "?", spaces and
# non-ASCII are escaped by everyone, so they stay out of this set.
_URI_SAFE = "/-_.!~*'():@&=+$,;"

def _local_path_to_thumb_uri(path: str) -> str:
    # abspath, not resolve(): the cache key is the path as Dolphin sees it,
    # and resolve() follows symlinks, which would change the hash.
    abs_path = os.path.abspath(path)
    return "file://" + quote(abs_path, safe=_URI_SAFE)


# Adjust/import from mediaModel.py's own extension list if you'd rather keep
# a single source of truth. Kept as a plain set here so this module has no
# hard dependency on mediaModel.
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv",
}


def _is_video(local_path: str) -> bool:
    return Path(local_path).suffix.lower() in VIDEO_EXTENSIONS


def _extract_video_frame(local_path: str, target_size: QSize) -> QImage:
    """Grab a representative frame from a video file via ffmpegthumbnailer
    and return it as a QImage. Returns a null QImage on any failure
    (missing ffmpegthumbnailer, unreadable file, decode error, etc) --
    callers should treat that the same as a failed QImageReader.read().

    Uses ffmpegthumbnailer rather than calling ffmpeg directly so that
    thumbnails generated here visually match KDE's own video thumbnails
    (film-strip border via -f), rather than looking like plain, undecorated
    frames next to ones Dolphin/KDE already generated. Its default seek
    position (10% into the video) also avoids the common issue of frame 0
    being a blank/fade-in frame.
    """
    if shutil.which("ffmpegthumbnailer") is None:
        print("[VIDEO THUMB] ffmpegthumbnailer not found on PATH")
        return QImage()

    width = target_size.width() if target_size.isValid() else 256
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)

    try:
        result = subprocess.run(
            [
                "ffmpegthumbnailer",
                "-i", local_path,
                "-o", tmp_path,
                "-s", str(width),
                "-f",  # film-strip overlay, matches KDE's own default look
            ],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            print(f"[VIDEO THUMB] ffmpegthumbnailer failed for {local_path}: {result.stderr.strip()}")
            return QImage()

        img = QImage(tmp_path)
        return img  # null QImage if it wrote nothing usable
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[VIDEO THUMB] extraction error for {local_path}: {exc}")
        return QImage()
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _size_tier_dir(base: Path, pixel_size: QSize) -> Path:
    """Map an actual generated thumbnail's pixel size to the freedesktop
    spec's named tier directory. Tiers are keyed on the LONGER edge of the
    image, matching the spec's square-canvas convention."""
    dim = max(pixel_size.width(), pixel_size.height())
    if dim <= 128:
        return base / "normal"
    elif dim <= 256:
        return base / "large"
    elif dim <= 512:
        return base / "x-large"
    else:
        return base / "xx-large"


def _save_thumbnail(base: Path, uri: str, uri_md5: str, img: QImage, local_path: str) -> bool:
    """Write a generated thumbnail into the shared freedesktop thumbnail
    cache so other spec-compliant apps (Dolphin, Gwenview, GNOME apps, etc.)
    can reuse it, and so this provider gets a cache hit next time too.

    Returns True on a successful write, False if anything prevented saving
    (missing source file, failed encode, etc). Never raises.
    """
    tier_dir = _size_tier_dir(base, img.size())
    try:
        tier_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    dest = tier_dir / f"{uri_md5}.png"

    try:
        st = Path(local_path).stat()
    except OSError:
        # Source file vanished between read and save; don't cache garbage.
        return False

    fd, tmp_path = tempfile.mkstemp(dir=tier_dir, suffix=".png.tmp")
    os.close(fd)

    try:
        # Embed the spec-required tEXt metadata so other readers can verify
        # this thumbnail still matches the current file (mtime check) and
        # know what it was generated from.
        out_img = img.copy()
        out_img.setText("Thumb::URI", uri)
        out_img.setText("Thumb::MTime", str(int(st.st_mtime)))
        out_img.setText("Thumb::Size", str(st.st_size))

        if not out_img.save(tmp_path, "PNG"):
            return False

        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, dest)  # atomic within the same directory
        return True
    except OSError:
        return False
    finally:
        # If save/replace failed partway, clean up the leftover temp file.
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# The freedesktop thumbnail sizes, smallest first: (directory, longer edge in pixels)
_TIERS = (("normal", 128), ("large", 256), ("x-large", 512))


class ThumbnailProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        # General shares the system cache; a private profile only ever uses its own
        self.thumbnails_base = profiles.thumbnail_base()

    def _lookup_dirs(self, hint: int) -> list:
        """Cache folders to try, best first, as (folder, edge). With no size hint:
        biggest first (the original behaviour). With a hint (the picture's size on
        screen): the smallest tier that is big enough, then bigger ones, then
        smaller ones, so a tiny tile does not decode a 512 pixel thumbnail when
        a 128 one exists."""
        if hint <= 0:
            return [(self.thumbnails_base / name, edge) for name, edge in reversed(_TIERS)]
        want = next((i for i, (_, edge) in enumerate(_TIERS) if edge >= hint), len(_TIERS) - 1)
        order = [want] + list(range(want + 1, len(_TIERS))) + list(range(want - 1, -1, -1))
        return [(self.thumbnails_base / _TIERS[i][0], _TIERS[i][1]) for i in order]

    @staticmethod
    def _generate(local_path: str, target_size: QSize) -> QImage:
        """Make a thumbnail of an image or a video (null for anything else)."""
        if _is_video(local_path):
            return _extract_video_frame(local_path, target_size)
        reader = QImageReader(local_path)
        orig_size = reader.size()
        if orig_size.isValid():
            reader.setScaledSize(orig_size.scaled(target_size, Qt.KeepAspectRatio))
        else:
            reader.setScaledSize(target_size)
        return reader.read()

    @staticmethod
    def _big_enough(img: QImage, wanted_edge: int, local_path: str) -> bool:
        """Whether a cached thumbnail is as big as its tier promises. Older
        versions saved smaller pictures (320 pixels) in the x-large folder, which
        look blurry on a big tile. Videos (the real size is unknowable) and files
        Tetia cannot draw itself (comics, PDFs) are always accepted."""
        if max(img.width(), img.height()) >= 0.9 * wanted_edge:
            return True
        return _is_video(local_path) or not QImageReader(local_path).canRead()

    def requestImage(self, id_string: str, requested_size: QSize, size: QSize):
        # id_string may arrive either as a plain local path or as a file:// URI
        # depending on how QML built the "image://provider/..." source string.
        q = QUrl(id_string)
        if q.scheme() == "file":
            local_path = q.toLocalFile()
        elif q.scheme():  # some other scheme, unlikely but be safe
            local_path = q.toLocalFile() or id_string
        else:
            local_path = id_string

        if not os.path.exists(local_path):
            print(f"[THUMB] path does not exist: id={id_string!r} -> {local_path!r}")

        uri = _local_path_to_thumb_uri(local_path)
        uri_md5 = hashlib.md5(uri.encode("utf-8")).hexdigest()
        cached_thumb_name = f"{uri_md5}.png"

        # The size the picture will be shown at, if the tile said ("sourceSize" in QML)
        hint = max(requested_size.width(), requested_size.height()) if requested_size.isValid() else 0
        folders = self._lookup_dirs(hint)
        wanted_edge = folders[0][1] if hint > 0 else 0

        # 1. Try the cache folders. With a hint, a hit that is too small is kept as a
        # fallback while the wanted size is made.
        fallback = QImage()
        for cache_dir, edge in folders:
            thumb_file = cache_dir / cached_thumb_name
            if not thumb_file.exists():
                continue
            img = QImage(str(thumb_file))
            if img.isNull():
                continue
            if hint <= 0 or (edge >= wanted_edge and self._big_enough(img, wanted_edge, local_path)):
                size.setWidth(img.width())
                size.setHeight(img.height())
                return img
            if max(img.width(), img.height()) > max(fallback.width(), fallback.height()):
                fallback = img

        # 2. Generate (preserve aspect ratio). A hint asks for the whole tier size, so
        # the file lands in the right freedesktop folder for other apps to reuse.
        target_size = QSize(wanted_edge, wanted_edge) if hint > 0 else QSize(256, 256)
        img = self._generate(local_path, target_size)

        if not img.isNull() and max(img.width(), img.height()) >= max(fallback.width(), fallback.height()):
            size.setWidth(img.width())
            size.setHeight(img.height())
            _save_thumbnail(self.thumbnails_base, uri, uri_md5, img, local_path)
            return img
        if not fallback.isNull():
            size.setWidth(fallback.width())
            size.setHeight(fallback.height())
            return fallback

        size.setWidth(target_size.width())
        size.setHeight(target_size.height())
        return img
