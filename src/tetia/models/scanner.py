# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reads one folder into the database: the part of a scan that both the media
grid (MediaModel) and the background indexer share, so a file is recognised the
same way (including renames) whichever one sees it first."""
from pathlib import Path

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


def scan_folder(db, folder_directory: Path, hash_fn):
    """Upsert every media file directly inside `folder_directory` into the
    database (one transaction) and mark vanished ones missing. Returns four
    lists of item dicts: images, videos, comics, books."""
    scan_directory = folder_directory.resolve()

    temporary_images_list = []
    temporary_videos_list = []
    temporary_comics_list = []
    temporary_books_list = []

    scanned_paths = set()
    claimed_ids = set()

    # Hash new and changed files BEFORE the transaction opens: reading a
    # couple of MB per file can take a while, and the write lock must not be
    # held that long (the indexer thread and the UI scan share the database).
    memo = {}
    try:
        for entry in folder_directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in ALL_MEDIA_EXTENSIONS:
                path = str(entry.resolve())
                info = entry.stat()
                if not db.get_stored_hash(path, info.st_size, int(info.st_mtime)):
                    memo[path] = hash_fn(path)
    except OSError:
        pass
    real_hash_fn = hash_fn
    hash_fn = lambda path: memo[path] if path in memo else real_hash_fn(path)

    # One transaction for the whole scan; database helpers used here never commit.
    # IMMEDIATE takes the write lock now and waits for it (the busy timeout). A plain
    # BEGIN starts with reads, and if the other connection commits meanwhile, SQLite
    # refuses to turn that stale read into a write and fails at once with
    # "database is locked", whatever the timeout.
    db.conn.execute("BEGIN IMMEDIATE")
    try:
        # Iterates over every file in the target directory and collects media metadata
        for directory_item in sorted(
            folder_directory.iterdir(), key=lambda entry: covers.natural_key(entry.name)
        ):
            # Checks if the current item is an actual file (not a subfolder)
            if directory_item.is_file():
                file_extension = directory_item.suffix.lower()

                is_image = file_extension in IMAGE_EXTENSIONS
                is_video = file_extension in VIDEO_EXTENSIONS
                is_comic = file_extension in COMIC_EXTENSIONS
                is_book = file_extension in EBOOK_EXTENSIONS

                # Skips anything that doesn't match a supported extension
                if not (is_image or is_video or is_comic or is_book):
                    continue

                abs_path = str(directory_item.resolve())
                scanned_paths.add(abs_path)
                stat_result = directory_item.stat()
                file_size = stat_result.st_size
                file_mtime = int(stat_result.st_mtime)
                kind = kind_from_ext(file_extension)

                # Don't rehash files whose size and mtime are unchanged
                content_hash = db.get_stored_hash(
                    abs_path, file_size, file_mtime
                ) or hash_fn(abs_path)

                # A path with no row yet may be a renamed file: look for a row with
                # the same hash whose file is gone, and take over its id/favorite/rating.
                # Only same-folder renames are reconciled (moves between folders are
                # treated as new files).
                moved = None
                if db.get_media_by_path(abs_path) is None:
                    candidate = db.find_missing_by_hash(
                        content_hash, scanned_paths, claimed_ids
                    )
                    if candidate and Path(candidate["path"]).parent == scan_directory:
                        moved = db.claim_move(
                            candidate["id"], abs_path, directory_item.name,
                            kind, file_size, file_mtime, content_hash
                        )
                        if moved is not None:
                            claimed_ids.add(candidate["id"])

                if moved is not None:
                    media_id, favorite, rating = moved
                else:
                    # Inserts a new row, or updates the existing row in place
                    media_id, favorite, rating = db.upsert_media(
                        abs_path, directory_item.name,
                        kind, file_size, file_mtime, content_hash
                    )

                item_metadata = {
                    "media_id": media_id,
                    "uniform_resource_identifier": directory_item.as_uri(),
                    "file_name": directory_item.name,
                    "size": file_size,
                    "mtime": file_mtime,
                    "is_video": is_video,
                    "is_comic": is_comic,
                    "is_book": is_book,
                    "is_favorite": favorite,
                    "rating": rating,
                }

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
        db.mark_missing(str(scan_directory), scanned_paths)

        db.conn.commit()

    except Exception:
        db.conn.rollback()
        raise


    return (temporary_images_list, temporary_videos_list,
            temporary_comics_list, temporary_books_list)
