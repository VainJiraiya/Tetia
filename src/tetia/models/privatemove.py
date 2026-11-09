# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Moving files into a private profile (no Qt Quick): out of the open profile's library, into a folder of the other
profile (inside its vault, for a vault profile), taking their tags, favorite and rating with them, and leaving no
trace behind.

One file at a time, so a stop or a failure never leaves one half moved:
  1. it is copied into the destination under a temporary name, checked (size and fingerprint) and named
  2. the files that go with it come too: a downloader's metadata, subtitles
  3. its row goes into the other profile's library, with its tags (and their categories and sources)
  4. the original is deleted, not sent to the Trash, which would keep a copy outside the vault
  5. its row in this profile's library (tags, progress, places on boards) and its thumbnails go
A file that can't be copied and checked is left where it was.
"""
import logging
import os
import shutil
from pathlib import Path

from tetia.models import scanner

logger = logging.getLogger(__name__)

TEMPORARY = ".tetia-moving-"
SUBTITLES = (".srt", ".vtt", ".ass", ".ssa", ".sub")


def companions(folder: str, name: str) -> list:
    """The files beside `name` that belong to it: gallery-dl's and yt-dlp's metadata, subtitles."""
    stem = os.path.splitext(name)[0]
    try:
        listed = os.listdir(folder)
    except OSError:
        return []
    out = []
    for other in listed:
        if other == name:
            continue
        if other in (name + ".json", stem + ".json", stem + ".info.json"):
            out.append(other)
        elif other.startswith(stem + ".") and os.path.splitext(other)[1].lower() in SUBTITLES:
            out.append(other)
    return out


def free_name(folder: str, name: str) -> str:
    """`name`, or "name (2).ext" and so on if the destination already has one."""
    stem, ext = os.path.splitext(name)
    candidate, n = name, 2
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = "%s (%d)%s" % (stem, n, ext)
        n += 1
    return candidate


def _copy_checked(source: str, target: str):
    """Copy `source` to `target` through a temporary name; raises OSError if the copy is not the same file."""
    folder, name = os.path.split(target)
    temporary = os.path.join(folder, TEMPORARY + name)
    try:
        shutil.copyfile(source, temporary)
        shutil.copystat(source, temporary)
        size = os.path.getsize(source)
        if os.path.getsize(temporary) != size or scanner.fingerprint(temporary) != scanner.fingerprint(source):
            raise OSError("the copy does not match the original")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


def _carry_row(source_db, target_db, row, target_path: str, target_name: str):
    """The file's row in the other profile's library: what it is, and its favorite, rating, size and tags."""
    media_id, _, _ = target_db.upsert_media(os.path.realpath(target_path), target_name, row["kind"], row["size"],
                                            row["mtime"], row["content_hash"])
    target_db.conn.execute("UPDATE media SET favorite = ?, rating = ?, width = ?, height = ? WHERE id = ?",
                           (row["favorite"], row["rating"], row["width"], row["height"], media_id))
    target_db.conn.commit()
    tags = source_db.conn.execute(
        "SELECT t.name, c.name AS category, mt.source FROM media_tag mt JOIN tag t ON t.id = mt.tag_id "
        "JOIN tag_category c ON c.id = t.category_id WHERE mt.media_id = ?", (row["id"],)).fetchall()
    for tag in tags:
        tag_id = target_db.get_or_create_tag(tag["name"], tag["category"])
        if tag_id is not None:
            target_db.insert_media_tags([media_id], tag_id, tag["source"])
    return media_id


def move(source_db, target_db, folder: str, media_ids, forget_thumbnails=None, stop=None, progress=None) -> dict:
    """Move these files (by their ids in `source_db`) into `folder`, recording them in `target_db`.
    {"moved": [source ids], "failed": [(file name, why)]}. `forget_thumbnails(path)` drops a file's thumbnails;
    `stop()` is asked between files; `progress(done, total)` is told after each."""
    moved, failed = [], []
    ids = [int(i) for i in media_ids]
    for done, media_id in enumerate(ids, 1):
        if stop is not None and stop():
            break
        row = source_db.conn.execute(
            "SELECT id, path, name, kind, size, mtime, content_hash, favorite, rating, width, height "
            "FROM media WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            continue
        source = row["path"]
        name = row["name"]
        if not os.path.isfile(source):
            failed.append((name, "it is no longer there"))
            continue
        source_folder = os.path.dirname(source)
        target_name = free_name(folder, name)
        target = os.path.join(folder, target_name)
        try:
            _copy_checked(source, target)
        except OSError as e:
            failed.append((name, "it could not be copied (%s)" % (e.strerror or e)))
            continue
        old_stem, new_stem = os.path.splitext(name)[0], os.path.splitext(target_name)[0]
        extras = companions(source_folder, name)
        for extra in extras:
            try:
                _copy_checked(os.path.join(source_folder, extra), os.path.join(folder, new_stem + extra[len(old_stem):]))
            except OSError:
                pass                                   # (the file itself matters; a lost subtitle is no reason to stop)
        try:
            _carry_row(source_db, target_db, row, target, target_name)
        except Exception as e:
            logger.error("Recording a moved file failed: %s", type(e).__name__)
            failed.append((name, "it was copied, but could not be added to the private library; the original stays"))
            try:
                os.remove(target)
            except OSError:
                pass
            continue
        try:
            os.remove(source)
        except OSError as e:
            failed.append((name, "it was copied, but the original could not be deleted (%s)" % (e.strerror or e)))
            continue
        for extra in extras:
            try:
                os.remove(os.path.join(source_folder, extra))
            except OSError:
                pass
        # its row and everything hanging on it; a tag only it had goes too (a tag's name says as much as a file's)
        tag_ids = [r[0] for r in source_db.conn.execute("SELECT tag_id FROM media_tag WHERE media_id = ?", (media_id,))]

        def forget_here():
            source_db.conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
            source_db._prune_unused_tags(tag_ids)
        source_db._write(forget_here)
        if forget_thumbnails is not None:
            forget_thumbnails(source)
        moved.append(media_id)
        if progress is not None:
            progress(done, len(ids))
    return {"moved": moved, "failed": failed}


def library_folders(target_db) -> list:
    """The other profile's library folders, as [{path, name, category}] (paths, not file:// addresses)."""
    from tetia.models import covers
    out = []
    for row in target_db.conn.execute("SELECT path, category FROM folders ORDER BY path"):
        path = covers.folder_key(row["path"])
        out.append({"path": path, "name": Path(path).name or path, "category": row["category"]})
    return out
