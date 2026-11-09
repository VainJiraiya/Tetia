# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reads one folder into the database: the part of a scan that both the media
grid (MediaModel) and the background indexer share, so a file is recognised the
same way (including renames) whichever one sees it first."""
import hashlib
import os
import threading
from pathlib import Path
from urllib.parse import quote_from_bytes

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImageIOHandler, QImageReader

from tetia.models import covers

# Defines sets of allowed file extensions for images and videos
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv"}

# Comic/manga archive formats
COMIC_EXTENSIONS = {".cbz", ".cbr", ".cb7", ".cbt"}

# Ebook formats. A PDF is indexed as an ebook (so `type:ebook`, the Books tab and
# the Favorites grouping treat it as one), because PDF documents are the common case.
EBOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw", ".azw3", ".fb2", ".djvu"}

# What the Manga tab lists: comic archives, plus PDFs (a lot of manga is distributed
# as PDF). A PDF therefore shows in the Manga tab of a folder the user filed under
# Manga, and in the Books tab of a folder filed under Books.
MANGA_TAB_EXTENSIONS = COMIC_EXTENSIONS | {".pdf"}
ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | COMIC_EXTENSIONS | EBOOK_EXTENSIONS

# The files each category (tab) of a folder lists, for the picture on a folder tile
CATEGORY_EXTENSIONS = {
    "photos": IMAGE_EXTENSIONS,
    "videos": VIDEO_EXTENSIONS,
    "manga": MANGA_TAB_EXTENSIONS,
    "books": EBOOK_EXTENSIONS,
}


def kind_from_ext(ext: str) -> str:
    if ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in VIDEO_EXTENSIONS:
        return "video"
    elif ext in COMIC_EXTENSIONS:
        return "comic"
    elif ext in EBOOK_EXTENSIONS:
        return "ebook"
    return "image"


def image_size(path: str):
    """(width, height) of an image as it is shown (an EXIF quarter turn swaps them), read from the file's header
    only; None if it can't be read."""
    return _shown_size(QImageReader(path))


def _shown_size(reader: QImageReader):
    size = reader.size()
    if not size.isValid() or size.isEmpty():
        return None
    width, height = size.width(), size.height()
    if reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
        width, height = height, width
    return width, height


def _size_from_head(head: bytes):
    """image_size from the first bytes of the file (None when its header goes on past them: a JPEG with a big
    EXIF or colour profile)."""
    buffer = QBuffer()
    buffer.setData(QByteArray(head))
    buffer.open(QIODevice.ReadOnly)
    return _shown_size(QImageReader(buffer))


# The fingerprint that tells a file again after a rename: SHA-1 of its size, its first and its last 64 KB, marked
# "v2:". It was 1 MB at each end; on a hard drive (worse in a vault) the two big reads cost a new file most of its
# time, and 64 KB tells pictures and videos apart as well. Rows keep the fingerprint they were given until their
# file changes, so both kinds live side by side (see _old_fingerprint).
FINGERPRINT_BYTES = 64 * 1024
FINGERPRINT_PREFIX = "v2:"


def _probe(path: str, size: int, want_picture: bool):
    """One open of a new file: (fingerprint, (width, height) or None). The picture's size comes from the bytes
    already read when its header fits in them."""
    if size == 0:
        return FINGERPRINT_PREFIX + hashlib.sha1(b"empty").hexdigest(), None
    try:
        with open(path, "rb") as f:
            head = f.read(FINGERPRINT_BYTES)
            tail = b""
            if size > FINGERPRINT_BYTES:
                f.seek(-FINGERPRINT_BYTES, 2)
                tail = f.read(FINGERPRINT_BYTES)
    except OSError:
        return "", None
    found = FINGERPRINT_PREFIX + hashlib.sha1(str(size).encode() + head + tail).hexdigest()
    picture = None
    if want_picture:
        picture = _size_from_head(head) or image_size(path)
    return found, picture


def fingerprint(path: str) -> str:
    """The fingerprint of a file (see FINGERPRINT_BYTES); "" if it can't be read."""
    try:
        size = os.stat(path).st_size
    except OSError:
        return ""
    return _probe(path, size, False)[0]


def _old_fingerprint(path: str, size: int) -> str:
    """The fingerprint before v2 (1 MB at each end, no mark), to recognise a renamed file whose row still has it."""
    if size == 0:
        return hashlib.sha1(b"empty").hexdigest()
    data = str(size).encode()
    try:
        with open(path, "rb") as f:
            data += f.read(1024 * 1024)
            if size > 1024 * 1024:
                f.seek(-1024 * 1024, 2)
                data += f.read(1024 * 1024)
    except OSError:
        return ""
    return hashlib.sha1(data).hexdigest()


class ScanStopped(Exception):
    """The scan was asked to stop (before it changed anything)."""


def _uri_prefix(folder_directory: Path) -> str:
    """The file:// address of a folder, to put a file's quoted name after: the same address Path.as_uri gives the
    file, without its cost (it was most of the time spent listing a folder of thousands of files)."""
    return "file://" + quote_from_bytes(os.fsencode(str(folder_directory).rstrip("/")))


def _item(media_id, prefix: str, name: str, size, mtime, kind, favorite, rating, width, height) -> dict:
    return {
        "media_id": media_id,
        "uniform_resource_identifier": prefix + "/" + quote_from_bytes(os.fsencode(name)),
        "file_name": name,
        "size": size,
        "mtime": mtime,
        "is_video": kind == "video",
        "is_comic": kind == "comic",
        "is_book": kind == "ebook",
        "is_favorite": favorite,
        "rating": rating,
        "width": width or 0,
        "height": height or 0,
    }


def _split(items):
    lists = ([], [], [], [])
    for item in items:
        lists[1 if item["is_video"] else 2 if item["is_comic"] else 3 if item["is_book"] else 0].append(item)
    return lists


def known_items(db, folder_directory: Path):
    """What the library already knows is directly inside this folder (no file is read): the same four lists as
    scan_folder, so a page can show them at once while the folder is scanned in the background."""
    prefix = str(folder_directory.resolve()).rstrip("/") + "/"
    upper = prefix[:-1] + chr(ord("/") + 1)
    rows = db.conn.execute(
        "SELECT id, path, name, kind, size, mtime, favorite, rating, width, height FROM media "
        "WHERE missing = 0 AND path >= ? AND path < ?", (prefix, upper)).fetchall()
    rows = [r for r in rows if "/" not in r["path"][len(prefix):] and not r["name"].startswith(".")]
    rows.sort(key=lambda r: covers.natural_key(r["name"]))
    # addressed through the folder as it was asked for (a link stays a link), as a scan addresses them
    uri_prefix = _uri_prefix(folder_directory)
    return _split(_item(r["id"], uri_prefix, r["name"], r["size"], r["mtime"], r["kind"], r["favorite"],
                        r["rating"], r["width"], r["height"]) for r in rows)


# One scan of a folder at a time: the background indexer and an open page often reach the same folder together,
# and the second one then finds everything already fingerprinted instead of reading the files again
_folder_locks: dict[str, threading.Lock] = {}
_folder_locks_guard = threading.Lock()


def _folder_lock(directory: Path) -> threading.Lock:
    with _folder_locks_guard:
        return _folder_locks.setdefault(str(directory), threading.Lock())


def scan_folder(db, folder_directory: Path, hash_fn, should_stop=None):
    """scan_folder_unlocked, one at a time per folder (a second caller waits, then has little left to do)."""
    lock = _folder_lock(folder_directory.resolve())
    while not lock.acquire(timeout=0.1):
        if should_stop is not None and should_stop():
            raise ScanStopped()
    try:
        return scan_folder_unlocked(db, folder_directory, hash_fn, should_stop)
    finally:
        lock.release()


def _gone_with_old_fingerprints(db, scan_directory: str, listed: set) -> bool:
    """Whether a file of this folder seen by the last scan is gone now and its row has a fingerprint from before v2:
    then a new file here may be it, renamed, and is fingerprinted the old way too."""
    prefix = scan_directory.rstrip("/") + "/"
    rows = db.conn.execute(
        "SELECT path, content_hash FROM media WHERE missing = 0 AND path >= ? AND path < ?",
        (prefix, prefix[:-1] + chr(ord("/") + 1))).fetchall()
    return any(r["path"] not in listed and "/" not in r["path"][len(prefix):]
               and r["content_hash"] and not r["content_hash"].startswith(FINGERPRINT_PREFIX) for r in rows)


def scan_folder_unlocked(db, folder_directory: Path, hash_fn, should_stop=None):
    """Upsert every media file directly inside `folder_directory` into the
    database (one transaction) and mark vanished ones missing. Returns four
    lists of item dicts: images, videos, comics, books.

    The folder is listed once (one stat per file). New and changed files are read
    before the transaction, in the order they lie on the disk (by inode), each
    opened once when `hash_fn` is `fingerprint`: the same read gives a picture's
    size. Another `hash_fn` (tests) is called as it is, with the size read apart.

    `should_stop` (a function) is asked between files while new ones are read and
    fingerprinted, which takes the time on a slow drive; if it says yes, ScanStopped
    is raised before anything was written."""
    scan_directory = folder_directory.resolve()
    real_folder = str(scan_directory)
    standard = hash_fn is fingerprint
    uri_prefix = _uri_prefix(folder_directory)

    # 1. One listing. A file's real path is the real folder's plus its name, except for a link (followed). An
    # unreadable folder raises here, before anything is written (it is not taken for an empty one).
    entries = []          # (name, extension, real path, size, mtime, inode)
    with os.scandir(folder_directory) as listing:
        for entry in listing:
            extension = os.path.splitext(entry.name)[1].lower()
            # Hidden files are left out: macOS leaves "._Name.mp4" resource-fork stubs next to copied files
            if entry.name.startswith(".") or extension not in ALL_MEDIA_EXTENSIONS:
                continue
            try:
                if not entry.is_file():
                    continue
                info = entry.stat()
                real = os.path.realpath(entry.path) if entry.is_symlink() else os.path.join(real_folder, entry.name)
                entries.append((entry.name, extension, real, info.st_size, int(info.st_mtime), entry.inode()))
            except OSError:
                continue                           # gone while being listed

    # What the library has for this folder, in one query (a link's target elsewhere is looked up alone): a file
    # whose size and mtime match its row is unchanged, and costs no more than a comparison
    prefix = real_folder.rstrip("/") + "/"
    rows = {r["path"]: r for r in db.conn.execute(
        "SELECT id, path, name, kind, size, mtime, content_hash, favorite, rating, width, height, missing "
        "FROM media WHERE path >= ? AND path < ?", (prefix, prefix[:-1] + chr(ord("/") + 1)))
        if "/" not in r["path"][len(prefix):]}

    def row_of(real):
        if real in rows or real.startswith(prefix):
            return rows.get(real)
        return db.conn.execute(
            "SELECT id, path, name, kind, size, mtime, content_hash, favorite, rating, width, height, missing "
            "FROM media WHERE path = ?", (real,)).fetchone()

    def unchanged(row, size, mtime):
        return row is not None and row["size"] == size and row["mtime"] == mtime and row["content_hash"]

    def picture_of(row):
        return (row["width"], row["height"]) if row is not None and row["width"] is not None else None

    # 2. Read new and changed files BEFORE the transaction opens (reading takes a while on a slow drive, and the
    # write lock must not be held that long: the indexer thread and the UI scan share the database), in the order
    # they lie on the disk.
    memo, sizes, old = {}, {}, {}
    old_style = standard and _gone_with_old_fingerprints(db, real_folder, {e[2] for e in entries})
    for name, extension, real, size, mtime, _ in sorted(entries, key=lambda e: e[5]):
        if should_stop is not None and should_stop():
            raise ScanStopped()
        is_image = extension in IMAGE_EXTENSIONS
        row = row_of(real)
        stored = row["content_hash"] if unchanged(row, size, mtime) else None
        stored_size = picture_of(row) if (stored and is_image) else None
        need_size = is_image and not stored_size
        picture = None
        if not stored:
            if standard:
                memo[real], picture = _probe(real, size, need_size)
            else:
                memo[real] = hash_fn(real)
                picture = image_size(real) if need_size else None
            if old_style and row is None:
                old[real] = _old_fingerprint(real, size)
        elif need_size:
            picture = image_size(real)
        if is_image:
            sizes[real] = (stored_size, False) if stored_size else (picture, True)

    temporary_images_list = []
    temporary_videos_list = []
    temporary_comics_list = []
    temporary_books_list = []
    scanned_paths = set()
    claimed_ids = set()

    # 3. One transaction for the whole scan; database helpers used here never commit.
    # IMMEDIATE takes the write lock now and waits for it (the busy timeout). A plain
    # BEGIN starts with reads, and if the other connection commits meanwhile, SQLite
    # refuses to turn that stale read into a write and fails at once with
    # "database is locked", whatever the timeout.
    db.conn.execute("BEGIN IMMEDIATE")
    try:
        for name, extension, real, size, mtime, _ in sorted(entries, key=lambda e: covers.natural_key(e[0])):
            is_image = extension in IMAGE_EXTENSIONS
            is_video = extension in VIDEO_EXTENSIONS
            is_comic = extension in COMIC_EXTENSIONS
            is_book = extension in EBOOK_EXTENSIONS
            scanned_paths.add(real)
            kind = kind_from_ext(extension)
            row = row_of(real)

            # A file just as the library has it: nothing to write
            if (unchanged(row, size, mtime) and not row["missing"] and row["name"] == name and row["kind"] == kind
                    and not sizes.get(real, (None, False))[1]):
                item_metadata = _item(row["id"], uri_prefix, name, size, mtime, kind, row["favorite"], row["rating"],
                                      *(picture_of(row) or (0, 0)))
                (temporary_images_list if is_image else temporary_videos_list if is_video
                 else temporary_comics_list if is_comic else temporary_books_list).append(item_metadata)
                continue

            # Don't rehash files whose size and mtime are unchanged
            content_hash = (row["content_hash"] if unchanged(row, size, mtime) else None) or memo.get(real) \
                or hash_fn(real)

            # A path with no row yet may be a renamed file: look for a row with
            # the same fingerprint whose file is gone, and take over its id/favorite/rating.
            # Only same-folder renames are reconciled (moves between folders are
            # treated as new files).
            moved = None
            if row is None:
                candidate = db.find_missing_by_hash(content_hash, scanned_paths, claimed_ids)
                if candidate is None and old.get(real):
                    candidate = db.find_missing_by_hash(old[real], scanned_paths, claimed_ids)
                if candidate and Path(candidate["path"]).parent == scan_directory:
                    moved = db.claim_move(
                        candidate["id"], real, name,
                        kind, size, mtime, content_hash
                    )
                    if moved is not None:
                        claimed_ids.add(candidate["id"])

            if moved is not None:
                media_id, favorite, rating = moved
            else:
                # Inserts a new row, or updates the existing row in place
                media_id, favorite, rating = db.upsert_media(
                    real, name,
                    kind, size, mtime, content_hash
                )

            picture, fresh = sizes.get(real, (None, False))
            if picture is not None and fresh:
                db.set_media_size(media_id, *picture)
            elif is_video:
                picture = db.get_media_size(media_id)        # learned by the background probe, if it ran

            item_metadata = _item(media_id, uri_prefix, name, size, mtime, kind, favorite, rating,
                                  *(picture or (0, 0)))

            # Sorts item into whichever list matches its extension
            if is_image:
                temporary_images_list.append(item_metadata)
            elif is_video:
                temporary_videos_list.append(item_metadata)
            elif is_comic:
                temporary_comics_list.append(item_metadata)
            elif is_book:
                temporary_books_list.append(item_metadata)

        # Mark rows in this folder whose files were not seen as missing
        db.mark_missing(real_folder, scanned_paths)

        db.conn.commit()

    except Exception:
        db.conn.rollback()
        raise

    return (temporary_images_list, temporary_videos_list,
            temporary_comics_list, temporary_books_list)
