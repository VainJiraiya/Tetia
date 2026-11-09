# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import weakref
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickImageProvider

from tetia import timing
from tetia.models import bookcovers, profiles, thumbPack

logger = logging.getLogger(__name__)

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
        _warn_once("ffmpegthumbnailer is not installed: videos have no thumbnails")
        return QImage()

    width = target_size.width() if target_size.isValid() else 256
    # The frame comes back on standard output ("-o -"), never through a file: a temporary file would sit in the
    # system's temp folder, outside a private profile's vault. Its error text names the video, so it is not shown.
    try:
        result = subprocess.run(
            [
                "ffmpegthumbnailer",
                "-i", local_path,
                "-o", "-",
                "-c", "png",
                "-s", str(width),
                "-f",  # film-strip overlay, matches KDE's own default look
            ],
            capture_output=True, timeout=20,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("A video thumbnail could not be made (%s)", type(exc).__name__)
        return QImage()
    if result.returncode != 0 or not result.stdout:
        logger.warning("ffmpegthumbnailer could not read a video (exit code %d)", result.returncode)
        return QImage()
    return QImage.fromData(result.stdout, "PNG")  # null QImage if it wrote nothing usable


_warned = set()


def _warn_once(message: str):
    if message not in _warned:
        _warned.add(message)
        logger.warning(message)


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
    tell it is stale); None if the file is gone. A thumbnail already marked with its picture's own size
    (Thumb::Image::Width/Height: as big as that picture allows) keeps the mark."""
    try:
        st = Path(local_path).stat()
    except OSError:
        return None
    out_img = img.copy()
    out_img.setText("Thumb::URI", uri)
    out_img.setText("Thumb::MTime", str(int(st.st_mtime)))
    out_img.setText("Thumb::Size", str(st.st_size))
    return out_img


def _source_edge(img: QImage) -> int:
    """The longer side of the picture a thumbnail was made from, when it says (Thumb::Image::Width/Height); 0
    when it does not."""
    try:
        return max(int(img.text("Thumb::Image::Width")), int(img.text("Thumb::Image::Height")))
    except ValueError:
        return 0


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
    for provider in list(_providers):
        provider.forget_memory(local_path)
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


# The providers there are, so forget_thumbnails can clear what they keep in memory
_providers = weakref.WeakSet()

# Thumbnails kept in memory, decoded: Qt's own image cache keeps only a few that are off screen, so going back to a
# tab or to Home asked the disk for every picture again (seconds, in a vault on a hard drive)
MEMORY_BUDGET = 192 * 1024 * 1024


def _local_path_of(id_string: str) -> str:
    """The file a thumbnail is asked for: id_string is a file:// address or a plain path, perhaps with the "?v=<n>"
    QML adds after a cover is changed by hand (not part of the file's name)."""
    id_string = re.sub(r"\?v=\d+$", "", id_string)
    if id_string.startswith(NO_STRIP):
        id_string = id_string[len(NO_STRIP):]
    q = QUrl(id_string)
    if q.scheme() == "file":
        return q.toLocalFile()
    if q.scheme():  # some other scheme, unlikely but be safe
        return q.toLocalFile() or id_string
    return id_string


class ThumbnailProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        _providers.add(self)
        self._memory = OrderedDict()      # (id, tier) -> (image, the file's mtime, its path), oldest first
        self._memory_bytes = 0
        self._memory_lock = threading.Lock()
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

    # ---- in memory

    def _remember(self, key, image: QImage, local_path: str):
        if image.isNull():
            return
        with self._memory_lock:
            old = self._memory.pop(key, None)
            if old is not None:
                self._memory_bytes -= old[0].sizeInBytes()
            self._memory[key] = (image, self._mtime(local_path), local_path)
            self._memory_bytes += image.sizeInBytes()
            while self._memory_bytes > MEMORY_BUDGET and len(self._memory) > 1:
                _, (dropped, _, _) = self._memory.popitem(last=False)
                self._memory_bytes -= dropped.sizeInBytes()

    def _recall(self, key):
        """A thumbnail kept in memory, if its file has not changed since (a stat, which the kernel answers from
        memory once the file was seen)."""
        with self._memory_lock:
            entry = self._memory.get(key)
        if entry is None:
            return None
        image, mtime, local_path = entry
        if self._mtime(local_path) != mtime:
            return None
        with self._memory_lock:
            if key in self._memory:
                self._memory.move_to_end(key)
        return image

    def forget_memory(self, local_path: str):
        with self._memory_lock:
            for key in [k for k, v in self._memory.items() if v[2] == local_path]:
                self._memory_bytes -= self._memory.pop(key)[0].sizeInBytes()

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

    def _read_cached(self, cache_dir: Path, uri_md5: str, packed: dict):
        """One tier's cached thumbnail (null if there is none) and where it was: "pack" in a private profile,
        "folder" for the freedesktop folders. A thumbnail an older Tetia left as a file in a private profile is
        moved into the pack the first time it is used ("moved in")."""
        thumb_file = cache_dir / f"{uri_md5}.png"
        if self._pack is None:
            return (QImage(str(thumb_file)) if thumb_file.exists() else QImage()), "folder"
        data = packed.get(cache_dir.name)
        if data:
            return QImage.fromData(data, "PNG"), "pack"
        if not self._legacy:
            return QImage(), "pack"
        try:
            data = thumb_file.read_bytes()
        except OSError:
            return QImage(), "pack"
        img = QImage.fromData(data, "PNG")
        if not img.isNull() and self._pack.put(uri_md5, cache_dir.name, data):
            try:
                thumb_file.unlink()
            except OSError:
                pass
        return img, "moved in"

    def _good_enough(self, img: QImage, edge: int, wanted_edge: int, local_path: str) -> bool:
        """Whether a cached thumbnail will do for a tile wanting `wanted_edge` pixels: one from a big enough tier
        (see _big_enough), or one marked as big as its picture allows (a book's small cover page: covers are never
        scaled up, so it used to be made again from the archive on every request)."""
        source = _source_edge(img)
        if source and max(img.width(), img.height()) >= 0.9 * min(wanted_edge, source):
            return True
        return edge >= wanted_edge and self._big_enough(img, wanted_edge, local_path)

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
        started = time.perf_counter()
        local_path = _local_path_of(id_string)
        hint = max(requested_size.width(), requested_size.height()) if requested_size.isValid() else 0
        key = (id_string, hint)
        outcome = "memory"
        try:
            image = self._recall(key)
            if image is None:
                # "nostrip/<file>": a video's thumbnail without the film strip ffmpegthumbnailer draws on its sides.
                # The strip is as wide as the thumbnail's width allows (1/16 of it on a wide video, its long side / 32
                # on a tall one), so tiles of one height showed strips of very different sizes; a tile asks for it
                # cropped off. The cached file keeps it (the cache is shared with other apps and stays standard).
                if id_string.startswith(NO_STRIP):
                    image, outcome = self._request_image(id_string[len(NO_STRIP):], size, requested_size)
                    image = without_film_strip(image)
                else:
                    image, outcome = self._request_image(id_string, size, requested_size)
                self._remember(key, image, local_path)
            if not image.isNull():
                size.setWidth(image.width())
                size.setHeight(image.height())
            return image
        finally:
            if timing.ENABLED:
                kind = "video" if _is_video(local_path) else "book" if bookcovers.is_book(local_path) else "image"
                timing.record("thumb %s: %s" % (kind, outcome), (time.perf_counter() - started) * 1000)
            with self._idle:
                self._active -= 1
                self._idle.notify_all()

    def _request_image(self, id_string: str, size: QSize, requested_size: QSize):
        """(the thumbnail, how it was found or made: see timing)."""
        local_path = _local_path_of(id_string)
        uri = _local_path_to_thumb_uri(local_path)
        uri_md5 = hashlib.md5(uri.encode("utf-8")).hexdigest()

        # The size the picture will be shown at, if the tile said ("sourceSize" in QML)
        hint = max(requested_size.width(), requested_size.height()) if requested_size.isValid() else 0
        folders = self._lookup_dirs(hint)
        wanted_edge = folders[0][1] if hint > 0 else 0

        # 1. Try the cache folders. With a hint, a hit that is too small is kept as a
        # fallback while the wanted size is made.
        fallback = QImage()
        stale = False
        packed = self._pack.get(uri_md5) if self._pack is not None else {}
        for cache_dir, edge in folders:
            img, where = self._read_cached(cache_dir, uri_md5, packed)
            if img.isNull():
                continue
            if not self._fresh(img, local_path):
                stale = True
                continue
            if hint <= 0 or self._good_enough(img, edge, wanted_edge, local_path):
                return img, where
            if max(img.width(), img.height()) > max(fallback.width(), fallback.height()):
                fallback = img

        # 2. Generate (preserve aspect ratio). A hint asks for the whole tier size, so
        # the file lands in the right freedesktop folder for other apps to reuse.
        made = "remade (too small)" if not fallback.isNull() else "remade (stale)" if stale else "made"
        target_size = QSize(wanted_edge, wanted_edge) if hint > 0 else QSize(256, 256)
        modified = self._mtime(local_path)
        is_book = bookcovers.is_book(local_path)
        if is_book and self._unreadable.get(local_path) == modified:
            img = QImage()
        else:
            img = self._generate(local_path, target_size)
            if img.isNull() and is_book:
                self._unreadable[local_path] = modified

        if not img.isNull() and max(img.width(), img.height()) >= max(fallback.width(), fallback.height()):
            if is_book and hint > 0 and max(img.width(), img.height()) < 0.9 * wanted_edge:
                # a cover is never scaled up: this is as big as its page allows, so it will do from now on
                img.setText("Thumb::Image::Width", str(img.width()))
                img.setText("Thumb::Image::Height", str(img.height()))
            if self._pack is not None:
                _pack_thumbnail(self._pack, uri, uri_md5, img, local_path)
            else:
                _save_thumbnail(self.thumbnails_base, uri, uri_md5, img, local_path)
            return img, made
        if not fallback.isNull():
            return fallback, "too small, kept"

        size.setWidth(target_size.width())
        size.setHeight(target_size.height())
        return img, "failed"
