# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import weakref
from pathlib import Path
from urllib.parse import quote
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickImageProvider

from tetia.models import bookcovers, profiles, thumbPack

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


def _tagged(img: QImage, uri: str, local_path: str):
    """The thumbnail with the spec's tEXt metadata (what it was made from, and that file's mtime, so a reader can
    tell it is stale); None if the file is gone."""
    try:
        st = Path(local_path).stat()
    except OSError:
        return None
    out_img = img.copy()
    out_img.setText("Thumb::URI", uri)
    out_img.setText("Thumb::MTime", str(int(st.st_mtime)))
    out_img.setText("Thumb::Size", str(st.st_size))
    return out_img


def _pack_thumbnail(pack, uri: str, uri_md5: str, img: QImage, local_path: str) -> bool:
    """Keep a generated thumbnail in a private profile's pack (see thumbPack), as the PNG the folders would hold."""
    out_img = _tagged(img, uri, local_path)
    if out_img is None:
        return False
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not out_img.save(buffer, "PNG"):
        return False
    buffer.close()
    return pack.put(uri_md5, _size_tier_dir(Path(), img.size()).name, bytes(data))


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

    out_img = _tagged(img, uri, local_path)
    if out_img is None:
        # Source file vanished between read and save; don't cache garbage.
        return False

    fd, tmp_path = tempfile.mkstemp(dir=tier_dir, suffix=".png.tmp")
    os.close(fd)

    try:
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
_TIERS = (("normal", 128), ("large", 256), ("x-large", 512), ("xx-large", 1024))


def forget_thumbnails(local_path: str):
    """Delete every cached thumbnail of a file, so the next request makes a fresh one
    (used when its cover is changed by hand)."""
    uri_md5 = hashlib.md5(_local_path_to_thumb_uri(local_path).encode("utf-8")).hexdigest()
    pack = thumbPack.pack()
    if pack is not None:
        pack.forget(uri_md5)
    name = uri_md5 + ".png"
    base = profiles.thumbnail_base()
    for tier in [t for t, _ in _TIERS] + ["xx-large"]:
        try:
            (base / tier / name).unlink()
        except OSError:
            pass


NO_STRIP = "nostrip/"


def _strip_width(gray: bytes, stride: int, width: int, height: int, from_left: bool) -> int:
    """How many columns on one side are a film strip: dark columns, with the sprocket holes (light squares at
    regular steps) in some of them. 0 if there is none."""
    rows = range(0, height, 2)
    limit = int(width * 0.15)
    band, holes = 0, 0
    while band < limit:
        x = band if from_left else width - 1 - band
        values = [gray[y * stride + x] for y in rows]
        dark = sum(1 for v in values if v < 40)
        if dark < 0.5 * len(values):
            break                                   # a column of the picture itself
        if max(values) > 150:                       # the bright middle of the holes (their edges are soft)
            holes += 1
        band += 1
    # only a band with holes in it is a strip (a dark edge of the picture alone is left as it is)
    return band if band >= 3 and holes >= max(2, band // 4) else 0


def without_film_strip(image: QImage) -> QImage:
    """A video thumbnail without the film strip a thumbnailer drew on its sides (ffmpegthumbnailer's, Dolphin's:
    each draws its own, of its own width), found in the picture itself."""
    if image.isNull() or image.width() < 32:
        return image
    gray = image.convertToFormat(QImage.Format_Grayscale8)
    width, height = gray.width(), gray.height()
    stride = gray.bytesPerLine()
    data = bytes(gray.constBits())[:stride * height]
    left = _strip_width(data, stride, width, height, True)
    right = _strip_width(data, stride, width, height, False)
    if not left and not right:
        return image
    return image.copy(left, 0, width - left - right, height)


class ThumbnailProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        # General shares the system cache; a private profile only ever uses its own
        self.thumbnails_base = profiles.thumbnail_base()
        # ...and keeps them in one file (thumbPack); its old thumbnail folders are read, and moved in, until empty
        self._pack = thumbPack.pack()
        self._legacy = self._pack is not None and any((self.thumbnails_base / t).is_dir() for t, _ in _TIERS)
        # comics, EPUBs and PDFs that could not be read, {path: mtime}: not tried again
        # while the file is unchanged, so scrolling past a damaged one stays cheap
        self._unreadable = {}
        # Pictures are read on a loader thread of Qt's. When a vault is about to be locked that thread may be in the
        # middle of one (several seconds, from a hard drive), so it is told to stop and waited for (release hook).
        self._closed = False
        self._active = 0
        self._idle = threading.Condition()
        release = weakref.WeakMethod(self.release)
        profiles.add_release_hook(lambda: release() and release()(), order=0)

    def release(self, timeout: float = 15.0):
        """Stop making thumbnails: later requests get nothing, and the ones under way are waited for."""
        with self._idle:
            self._closed = True
            self._idle.wait_for(lambda: self._active == 0, timeout=timeout)

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
        """Make a thumbnail of an image, a video, a comic, an EPUB or a PDF (null for anything else)."""
        if _is_video(local_path):
            return _extract_video_frame(local_path, target_size)
        if bookcovers.is_book(local_path):
            return bookcovers.make_cover(local_path, max(target_size.width(), target_size.height()))
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
        look blurry on a big tile. Only files Tetia can draw itself are worth
        making again: pictures, comics, EPUBs and PDFs. A video is accepted as it
        is (its real size is unknowable) and so is anything else (Dolphin's)."""
        if max(img.width(), img.height()) >= 0.9 * wanted_edge:
            return True
        if _is_video(local_path):
            return True
        return not (bookcovers.is_book(local_path) or QImageReader(local_path).canRead())

    def _read_cached(self, cache_dir: Path, uri_md5: str, packed: dict) -> QImage:
        """One tier's cached thumbnail (null if there is none): from the pack in a private profile, else from the
        freedesktop folder. A thumbnail an older Tetia left as a file in a private profile is moved into the pack
        the first time it is used."""
        thumb_file = cache_dir / f"{uri_md5}.png"
        if self._pack is None:
            return QImage(str(thumb_file)) if thumb_file.exists() else QImage()
        data = packed.get(cache_dir.name)
        if data:
            return QImage.fromData(data, "PNG")
        if not self._legacy:
            return QImage()
        try:
            data = thumb_file.read_bytes()
        except OSError:
            return QImage()
        img = QImage.fromData(data, "PNG")
        if not img.isNull() and self._pack.put(uri_md5, cache_dir.name, data):
            try:
                thumb_file.unlink()
            except OSError:
                pass
        return img

    @staticmethod
    def _mtime(local_path: str):
        try:
            return int(os.stat(local_path).st_mtime)
        except OSError:
            return None

    def _fresh(self, img: QImage, local_path: str) -> bool:
        """The spec's staleness test: a thumbnail made from an older version of the file
        carries its Thumb::MTime and is not used (it is made again)."""
        recorded = img.text("Thumb::MTime")
        current = self._mtime(local_path)
        if not recorded or current is None:
            return True
        try:
            return int(recorded) == current
        except ValueError:
            return True

    def requestImage(self, id_string: str, size: QSize, requested_size: QSize):
        # Qt's order: the image's size is an OUTPUT (set below) and the size QML asked for (sourceSize) comes last.
        # This used to be declared the other way round, so the size QML asked for was never seen.
        with self._idle:
            if self._closed:
                return QImage()
            self._active += 1
        try:
            # "nostrip/<file>": a video's thumbnail without the film strip ffmpegthumbnailer draws on its sides. The
            # strip is as wide as the thumbnail's width allows (1/16 of it on a wide video, its long side / 32 on a
            # tall one), so tiles of one height showed strips of very different sizes; a tile asks for it cropped
            # off. The cached file keeps it (the cache is shared with other apps and stays standard).
            if id_string.startswith(NO_STRIP):
                image = self._request_image(id_string[len(NO_STRIP):], size, requested_size)
                image = without_film_strip(image)
                if not image.isNull():
                    size.setWidth(image.width())
                    size.setHeight(image.height())
                return image
            return self._request_image(id_string, size, requested_size)
        finally:
            with self._idle:
                self._active -= 1
                self._idle.notify_all()

    def _request_image(self, id_string: str, size: QSize, requested_size: QSize):
        # QML adds "?v=<n>" after a cover is changed by hand, so its image cache reloads
        # the picture; the number is not part of the file's name
        id_string = re.sub(r"\?v=\d+$", "", id_string)
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

        # The size the picture will be shown at, if the tile said ("sourceSize" in QML)
        hint = max(requested_size.width(), requested_size.height()) if requested_size.isValid() else 0
        folders = self._lookup_dirs(hint)
        wanted_edge = folders[0][1] if hint > 0 else 0

        # 1. Try the cache folders. With a hint, a hit that is too small is kept as a
        # fallback while the wanted size is made.
        fallback = QImage()
        packed = self._pack.get(uri_md5) if self._pack is not None else {}
        for cache_dir, edge in folders:
            img = self._read_cached(cache_dir, uri_md5, packed)
            if img.isNull() or not self._fresh(img, local_path):
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
        modified = self._mtime(local_path)
        if bookcovers.is_book(local_path) and self._unreadable.get(local_path) == modified:
            img = QImage()
        else:
            img = self._generate(local_path, target_size)
            if img.isNull() and bookcovers.is_book(local_path):
                self._unreadable[local_path] = modified

        if not img.isNull() and max(img.width(), img.height()) >= max(fallback.width(), fallback.height()):
            size.setWidth(img.width())
            size.setHeight(img.height())
            if self._pack is not None:
                _pack_thumbnail(self._pack, uri, uri_md5, img, local_path)
            else:
                _save_thumbnail(self.thumbnails_base, uri, uri_md5, img, local_path)
            return img
        if not fallback.isNull():
            size.setWidth(fallback.width())
            size.setHeight(fallback.height())
            return fallback

        size.setWidth(target_size.width())
        size.setHeight(target_size.height())
        return img
