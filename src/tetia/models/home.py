# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Home (no Qt): what you are in the middle of, what you pinned, your favorites and what came in lately.

Nothing here is picked for you: Continue is what you opened and did not finish (manga and books, and long
videos only: a clip is never resumed), Pinned is what you pinned, Favorites what you starred, Recently added the
files Tetia saw last. There is no banner.
"""
import os
from pathlib import Path

from tetia.models import boards, covers, series
from tetia.models.playbackStore import CLIP_SECONDS

PIN_KINDS = ("board", "folder", "tag")


def pin(db, kind: str, ref: str):
    if kind not in PIN_KINDS:
        raise ValueError("cannot pin a %r" % kind)
    db._write(lambda: db.conn.execute(
        "INSERT OR IGNORE INTO pin (kind, ref, position) VALUES (?, ?, (SELECT COALESCE(MAX(position), 0) + 1 FROM pin))",
        (kind, str(ref))))


def unpin(db, kind: str, ref: str):
    db._write(lambda: db.conn.execute("DELETE FROM pin WHERE kind = ? AND ref = ?", (kind, str(ref))))


def is_pinned(db, kind: str, ref: str) -> bool:
    return db.conn.execute("SELECT 1 FROM pin WHERE kind = ? AND ref = ?", (kind, str(ref))).fetchone() is not None


def pins(db) -> list:
    return [dict(r) for r in db.conn.execute("SELECT kind, ref FROM pin ORDER BY position")]


def _minutes_left(position, duration):
    left = max(0, int(round((duration - position) / 60)))
    return "%d h %d min left" % divmod(left, 60) if left >= 60 else "%d min left" % left


def _series_of(db, path: str) -> str:
    """The series folder a file belongs to: its folder, or for a show with season folders the one above ('' for
    none)."""
    folder = os.path.dirname(path)
    for _ in range(2):
        if db.get_collection_meta(covers.folder_key(folder))["is_series"]:
            return folder
        folder = os.path.dirname(folder)
    return ""


def _roots(db):
    return boards.library_roots(db)


def continue_items(db, limit: int = 8) -> list:
    """Manga and books partway (a series where its next chapter is) and long videos partway (a series of them as
    one), most recent first: [{kind: series|book|video|show, path, name, cover, where, fraction}]."""
    found, seen = [], set()
    roots = _roots(db)
    for row in db.recent_reading():
        path = row["path"]
        if not boards.in_library(path, roots):
            continue                                # (its library folder was removed)
        folder = _series_of(db, path)
        if folder:
            if folder in seen:
                continue
            seen.add(folder)
            progress = series.progress(db, folder)
            if progress["finished"] or not progress["total"]:
                continue
            at = min(progress["total"] - progress["left"] + 1, progress["total"])
            found.append({"kind": "series", "path": folder, "name": os.path.basename(folder), "cover": path,
                          "where": "Chapter %d of %d" % (at, progress["total"]), "fraction": progress["fraction"],
                          "when": row["updated"] or ""})
        elif not row["finished"]:
            total = row["total"] or 0
            found.append({"kind": "book", "path": path, "name": Path(path).stem, "cover": path,
                          "where": ("Page %d of %d" % (row["page"] + 1, total)) if total else "",
                          "fraction": (row["page"] + 1) / total if total else 0.0, "when": row["updated"] or ""})
    for row in db.recent_watching(CLIP_SECONDS):
        path = row["path"]
        if not boards.in_library(path, roots):
            continue
        folder = _series_of(db, path)
        show = bool(folder)
        key = folder if show else path
        if key in seen:
            continue
        seen.add(key)
        found.append({"kind": "show" if show else "video", "path": folder if show else path,
                      "name": os.path.basename(folder) if show else Path(path).stem, "cover": path,
                      "where": ((_episode_label(Path(path).stem, os.path.basename(folder)) + " · ") if show else "")
                               + _minutes_left(row["position"], row["duration"]),
                      "fraction": row["position"] / row["duration"] if row["duration"] else 0.0,
                      "when": row["updated"] or ""})
    found.sort(key=lambda item: item["when"], reverse=True)
    return found[:limit]


def _episode_label(stem: str, show: str) -> str:
    """"Starfall - S01E02 - The Signal" in the show Starfall: "S01E02 - The Signal"."""
    if show and stem.lower().startswith(show.lower()):
        stem = stem[len(show):].lstrip(" -_.\u2013\u2014")
    return stem or show


def _tag_collage(db, name: str) -> tuple:
    """(how many files have the tag, three of its mildest pictures)."""
    tag_id = db.resolve_tag_id(name)
    if tag_id is None:
        return 0, []
    rows = db.conn.execute(
        "SELECT m.path, m.rating FROM media_tag t JOIN media m ON m.id = t.media_id "
        "WHERE t.tag_id = ? AND m.missing = 0 AND m.kind IN ('image', 'video')", (tag_id,)).fetchall()
    count = db.conn.execute("SELECT COUNT(*) FROM media_tag WHERE tag_id = ?", (tag_id,)).fetchone()[0]
    mild = sorted(rows, key=lambda r: (r["rating"] if r["rating"] is not None else 0.5, covers.natural_key(r["path"])))
    return count, [r["path"] for r in mild[:3]]


def pinned_items(db, resolver) -> list:
    """What is pinned, ready for its tile: [{kind: board|folder|series|tag, ref, name, sub, cover, collage, badge,
    fraction, finished}]. A pin whose board or folder is gone is left out."""
    out = []
    for p in pins(db):
        kind, ref = p["kind"], p["ref"]
        if kind != "board":
            continue                     # Pinned is for boards; folders, series and files are on Home as favorites
        item = {"kind": kind, "ref": ref, "cover": "", "collage": [], "badge": "", "fraction": 0.0, "finished": False}
        if kind == "board":
            board = boards.get(db, int(ref))
            if board is None:
                continue
            ids = boards.members(db, resolver, board["id"])
            item.update(name=board["name"], sub="Board · %d" % len(ids), collage=boards.collage(db, board["id"], ids))
        elif kind == "tag":
            count, collage = _tag_collage(db, ref)
            item.update(name=ref, sub="Tag · %d" % count, collage=collage)
        else:
            folder = covers.folder_key(ref)
            if not os.path.isdir(folder):
                continue
            meta = db.get_collection_meta(folder)
            cover = covers.tile_picture(folder, covers.ANY_PICTURE_EXTENSIONS,
                                        lambda f: db.get_collection_meta(covers.folder_key(f)), set())
            item.update(name=os.path.basename(folder.rstrip(os.sep)), cover=cover or "")
            if meta["is_series"]:
                progress = series.progress(db, folder)
                item.update(kind="series", sub="Series · %d" % progress["total"],
                            badge=str(progress["left"]) if progress["left"] and not progress["finished"] else "",
                            fraction=progress["fraction"], finished=progress["finished"])
            else:
                item.update(sub="Folder")
        out.append(item)
    return out


def favorite_covers(db, limit: int = 40) -> list:
    """Starred folders, series, comics and books, as covers: [{kind: folder|series|book, path, name, cover}]."""
    out = []
    roots = _roots(db)
    for row in db.get_favorite_collections():
        folder = covers.folder_key(row["path"])
        if not os.path.isdir(folder) or not boards.in_library(os.path.realpath(folder) + os.sep, roots):
            continue
        cover = covers.tile_picture(folder, covers.ANY_PICTURE_EXTENSIONS,
                                    lambda f: db.get_collection_meta(covers.folder_key(f)), set())
        out.append({"kind": "series" if row["is_series"] else "folder", "path": folder,
                    "name": os.path.basename(folder.rstrip(os.sep)), "cover": cover or ""})
    out.sort(key=lambda item: covers.natural_key(item["name"]))
    for row in db.conn.execute(
            "SELECT path, name FROM media WHERE favorite = 1 AND missing = 0 AND kind IN ('comic', 'ebook') "
            "ORDER BY name COLLATE NOCASE"):
        if boards.in_library(row["path"], roots):
            out.append({"kind": "book", "path": row["path"], "name": Path(row["name"]).stem, "cover": row["path"]})
    return out[:limit]


def favorite_files(db, limit: int = 40) -> list:
    """Starred pictures and videos, as the Favorites row shows them: [{id, path, name, kind, aspect}]."""
    rows = db.conn.execute(
        "SELECT id, path, name, kind, width, height FROM media WHERE favorite = 1 AND missing = 0 "
        "AND kind IN ('image', 'video') ORDER BY added_at DESC, id DESC LIMIT ?", (int(limit) * 4,)).fetchall()
    roots = _roots(db)
    return [_file(dict(r)) for r in rows if boards.in_library(r["path"], roots)][:limit]


def recent_files(db, limit: int = 150) -> list:
    roots = _roots(db)
    return [_file(r) for r in db.recently_added(("image", "video"), limit * 4) if boards.in_library(r["path"], roots)][:limit]


def _file(row: dict) -> dict:
    width, height = row.get("width") or 0, row.get("height") or 0
    aspect = width / height if width > 0 and height > 0 else (16 / 9 if row["kind"] == "video" else 1.0)
    return {"id": row["id"], "path": row["path"], "name": row["name"], "kind": row["kind"], "aspect": aspect}


# What each tab holds, for the Library cards
_TABS = (("photos", "Images", ("image",), "image", "images"),
         ("videos", "Videos", ("video",), "video", "videos"),
         ("manga", "Manga", ("comic",), "item", "items"),
         ("books", "EBooks", ("ebook",), "book", "books"))


def library_summary(db) -> list:
    """One card per tab that has library folders: [{tab, name, sub ("2,412 images"), collage (three pictures,
    the mildest-rated first)}]. Facts about the library, nothing picked for the user."""
    out = []
    for tab, name, kinds, one, many in _TABS:
        roots = [covers.folder_key(f["path"]).rstrip(os.sep) + os.sep for f in db.get_folders_by_category(tab)]
        if not roots:
            continue
        where = " OR ".join("(path >= ? AND path < ?)" for _ in roots)
        params = [bound for r in roots for bound in (r, r[:-1] + chr(ord(os.sep) + 1))]
        marks = ",".join("?" * len(kinds))
        count = db.conn.execute(
            f"SELECT COUNT(*) FROM media WHERE missing = 0 AND kind IN ({marks}) AND ({where})",
            (*kinds, *params)).fetchone()[0]
        rows = db.conn.execute(
            f"SELECT path FROM media WHERE missing = 0 AND kind IN ({marks}) AND ({where}) "
            f"ORDER BY COALESCE(rating, 0.5), added_at DESC LIMIT 3", (*kinds, *params)).fetchall()
        out.append({"tab": tab, "name": name, "sub": "%s %s" % (f"{count:,}", one if count == 1 else many),
                    "collage": [r["path"] for r in rows]})
    return out

