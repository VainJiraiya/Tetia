# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tags read from the files themselves (no Qt Quick): a comic's ComicInfo.xml, a downloader's metadata beside a
picture. Readers turn what they find into an Imported; this applies it to a file or a series.

Imported tags are marked as such (media_tag.source, folder_tag.source = 'import'), so the next import of the same
file replaces them, and they never mix with the user's own: a tag the user gave is never removed by an import,
and one the user gives that an import gave first becomes theirs. A content rating, a description and a series
format are only filled in where none was set; an import never overrides a choice.
"""
import logging
import os
import sqlite3
from dataclasses import dataclass, field

from tetia.models import covers, reader
from tetia.models.tag_query import CATEGORIES
from tetia.models.tagModel import normalize_tag

logger = logging.getLogger(__name__)


@dataclass
class Imported:
    tags: list = field(default_factory=list)    # [(category, name)]: category one of tag_query.CATEGORIES
    rating: int | None = None                   # 0 general, 1 suggestive, 2 mature, 3 explicit
    description: str = ""
    format: str = ""                            # a series' format (reader.FORMATS)

    def __bool__(self):
        return bool(self.tags or self.rating is not None or self.description or self.format)


def _tag_ids(db, imported: Imported) -> list:
    """The ids of the imported tags, made where they don't exist yet (a name that can't be a tag is skipped)."""
    ids = []
    for category, name in imported.tags:
        if category not in CATEGORIES:
            continue
        try:
            tag_id = db.get_or_create_tag(normalize_tag(name), category)
        except ValueError:
            continue
        if tag_id is not None and tag_id not in ids:
            ids.append(tag_id)
    return ids


def apply_to_file(db, media_id: int, imported: Imported):
    """Replace a file's imported tags with these, and fill in its rating if it has none (one transaction)."""
    def _do():
        old = [r[0] for r in db.conn.execute(
            "SELECT tag_id FROM media_tag WHERE media_id = ? AND source = 'import'", (int(media_id),))]
        db.conn.execute("DELETE FROM media_tag WHERE media_id = ? AND source = 'import'", (int(media_id),))
        for tag_id in _tag_ids(db, imported):
            db.conn.execute("INSERT OR IGNORE INTO media_tag (media_id, tag_id, source) VALUES (?, ?, 'import')",
                            (int(media_id), tag_id))
        if imported.rating is not None and 0 <= imported.rating <= 3:
            db.conn.execute("UPDATE media SET rating = ? WHERE id = ? AND rating IS NULL",
                            (int(imported.rating), int(media_id)))
        db._prune_unused_tags(old)
    try:
        db._write(_do)
    except sqlite3.Error as e:
        logger.error("Importing tags failed: %s", e)


def apply_to_series(db, folder: str, imported: Imported, tag_ids=None):
    """The same for a series (a folder shown as one item): its imported tags replaced (by these tag ids, when
    given), and its rating, description and format filled in where none was set."""
    key = covers.folder_key(folder)
    tagged = os.path.realpath(key)                      # (series tags are kept by the folder's real path)

    def _do():
        old = [r[0] for r in db.conn.execute(
            "SELECT tag_id FROM folder_tag WHERE folder = ? AND source = 'import'", (tagged,))]
        db.conn.execute("DELETE FROM folder_tag WHERE folder = ? AND source = 'import'", (tagged,))
        for tag_id in tag_ids if tag_ids is not None else _tag_ids(db, imported):
            db.conn.execute("INSERT OR IGNORE INTO folder_tag (folder, tag_id, source) VALUES (?, ?, 'import')",
                            (tagged, tag_id))
        meta = db.get_collection_meta(key)
        if imported.rating is not None and 0 <= imported.rating <= 3 and meta["rating"] is None:
            db.set_collection_rating(key, int(imported.rating))
        if imported.description and not meta["description"]:
            db.set_collection_description(key, imported.description)
        if imported.format in reader.FORMATS and not meta["format"]:
            db.set_collection_format(key, imported.format)
        db._prune_unused_tags(old)
    try:
        db._write(_do)
    except sqlite3.Error as e:
        logger.error("Importing the tags of a series failed: %s", e)
    covers.notifier.changed.emit(key)


def forget_file(db, media_id: int):
    """Take away what imports gave a file (its own tags stay)."""
    apply_to_file(db, media_id, Imported())


def shared(per_item: list) -> Imported:
    """What every one of several imports has in common (the chapters of a series: what they all say belongs to
    the series): the tags all of them have, and the rating, description and format if they all agree."""
    if not per_item:
        return Imported()
    tags = [t for t in per_item[0].tags if all(t in other.tags for other in per_item[1:])]

    def agreed(attr, empty):
        values = {getattr(i, attr) for i in per_item}
        return values.pop() if len(values) == 1 else empty
    return Imported(tags=tags, rating=agreed("rating", None), description=agreed("description", ""),
                    format=agreed("format", ""))


def update_series_from_chapters(db, folder: str, details: Imported = None):
    """A series' imported tags are what every chapter's import gave (the series, its writer...), worked out from
    the library rather than from what one scan read, so a new chapter alone never replaces them. `details`
    (rating, description, format) fill in what the series lacks."""
    from tetia.models import series
    key = covers.folder_key(folder)
    if not db.get_collection_meta(key)["is_series"]:
        return
    per_chapter = []
    for path in series.chapters(key):
        found = db.get_media_by_path(os.path.realpath(path))
        if found is None:
            continue
        ids = {r[0] for r in db.conn.execute(
            "SELECT tag_id FROM media_tag WHERE media_id = ? AND source = 'import'", (found[0],))}
        if ids:
            per_chapter.append(ids)
    shared_ids = sorted(set.intersection(*per_chapter)) if per_chapter else []
    apply_to_series(db, key, details or Imported(), tag_ids=shared_ids)
