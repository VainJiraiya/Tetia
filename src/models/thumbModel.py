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

# RFC 2396 "mark" characters that glib's g_filename_to_uri() (and therefore
# KDE's thumbnail cache) leaves unescaped, on top of normal unreserved chars.
# Qt's QUrl.FullyEncoded uses the stricter RFC 3986 set and encodes these,
# which breaks the MD5 match for names containing e.g. "(1)".
_URI_SAFE = "/-_.!~*'()"

def _local_path_to_thumb_uri(path: str) -> str:
    abs_path = str(Path(path).resolve())
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


class ThumbnailProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        self.thumbnails_base = Path.home() / ".cache" / "thumbnails"
        self.cache_dirs = [
            self.thumbnails_base / "x-large",
            self.thumbnails_base / "large",
            self.thumbnails_base / "normal",
        ]

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

        uri = _local_path_to_thumb_uri(local_path)
        uri_md5 = hashlib.md5(uri.encode("utf-8")).hexdigest()
        cached_thumb_name = f"{uri_md5}.png"

        # 1. Try all cache directories
        for cache_dir in self.cache_dirs:
            thumb_file = cache_dir / cached_thumb_name
            print(f"CHECKING {thumb_file}")
            if thumb_file.exists():
                img = QImage(str(thumb_file))
                if not img.isNull():
                    print(f"[CACHE HIT] {cache_dir, id_string}")
                    size.setWidth(img.width())
                    size.setHeight(img.height())
                    return img

        # 2. Generate fallback (preserve aspect ratio)
        target_size = requested_size if requested_size.isValid() else QSize(256, 256)

        if _is_video(local_path):
            img = _extract_video_frame(local_path, target_size)
        else:
            reader = QImageReader(local_path)
            orig_size = reader.size()

            if orig_size.isValid():
                scaled_size = orig_size.scaled(target_size, Qt.KeepAspectRatio)
            else:
                scaled_size = target_size

            reader.setScaledSize(scaled_size)
            img = reader.read()

        if not img.isNull():
            print(f"[CACHE MISS]{id_string, local_path}")
            size.setWidth(img.width())
            size.setHeight(img.height())
            _save_thumbnail(self.thumbnails_base, uri, uri_md5, img, local_path)
        else:
            print(f"[ERROR READING] {local_path}")
            size.setWidth(target_size.width())
            size.setHeight(target_size.height())

        return img