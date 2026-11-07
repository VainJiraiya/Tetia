# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Boards (no Qt): a saved tag search dressed as a collection.

A board gathers: its files are what its search finds (it follows the tags, so a file tagged later joins it by
itself), plus files put on it by hand, less files taken off it by hand. Nothing moves and a file can be on any
number of boards; a virtual folder is the opposite (it tidies: a file is in one place). A board belongs to the tab
it was made in (its search only looks in that tab's library folders) or, made from a search across the library, to
none ("").

Its cover is a collage of three pictures: the one chosen by hand first, then the files with the mildest content
rating (unrated counts as a little more than general), so what Tetia picks by itself is never the spiciest.
"""
import os
import sqlite3

from tetia.models import covers, tag_query

LAYOUTS = ("rows", "columns", "grid")
COVER_KINDS = ("image", "video")


def create(db, name: str, query: str = "", tab: str = "") -> int:
    def _do():
        return db.conn.execute(
            "INSERT INTO board (name, query, tab, created) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (name.strip() or "Board", query.strip(), tab)).lastrowid
    return db._write(_do)


def get(db, board_id: int):
    row = db.conn.execute("SELECT id, name, query, tab, layout, cover_media_id FROM board WHERE id = ?",
                          (int(board_id),)).fetchone()
    return dict(row) if row else None


def all_boards(db, tab=None) -> list:
    """Every board (of one tab when `tab` is given), by name."""
    if tab is None:
        rows = db.conn.execute("SELECT id, name, query, tab, layout, cover_media_id FROM board").fetchall()
    else:
        rows = db.conn.execute("SELECT id, name, query, tab, layout, cover_media_id FROM board WHERE tab = ?",
                               (tab,)).fetchall()
    return sorted((dict(r) for r in rows), key=lambda b: covers.natural_key(b["name"]))


def update(db, board_id: int, **fields):
    """Change a board's name, query, layout or cover_media_id."""
    allowed = {k: v for k, v in fields.items() if k in ("name", "query", "layout", "cover_media_id")}
    if "layout" in allowed and allowed["layout"] not in LAYOUTS + (None,):
        raise ValueError("unknown layout: %r" % allowed["layout"])
    if not allowed:
        return
    sets = ", ".join(f"{k} = ?" for k in allowed)
    db._write(lambda: db.conn.execute(f"UPDATE board SET {sets} WHERE id = ?", (*allowed.values(), int(board_id))))


def delete(db, board_id: int):
    """Delete a board. It holds no files, so nothing else changes."""
    db._write(lambda: db.conn.execute("DELETE FROM board WHERE id = ?", (int(board_id),)))


def pin(db, board_id: int, media_ids, added: bool = True):
    """Put files on a board by hand (added) or take them off it (not added), whatever its search says."""
    rows = [(int(board_id), int(m), 1 if added else 0) for m in media_ids]
    db._write(lambda: db.conn.executemany(
        "INSERT INTO board_pin (board_id, media_id, added) VALUES (?, ?, ?) "
        "ON CONFLICT(board_id, media_id) DO UPDATE SET added = excluded.added", rows))


def unpin(db, board_id: int, media_ids):
    """Forget what was done by hand to these files: the search decides again."""
    rows = [(int(board_id), int(m)) for m in media_ids]
    db._write(lambda: db.conn.executemany("DELETE FROM board_pin WHERE board_id = ? AND media_id = ?", rows))


def _pins(db, board_id):
    rows = db.conn.execute("SELECT media_id, added FROM board_pin WHERE board_id = ?", (int(board_id),)).fetchall()
    return {r["media_id"] for r in rows if r["added"]}, {r["media_id"] for r in rows if not r["added"]}


def _ranges(db, tab):
    folders = [f["path"] for f in db.get_folders_by_category(tab)] if tab else db.get_all_folders()
    return [tag_query.scope_range(os.path.realpath(covers.folder_key(f))) for f in folders]


def members(db, resolver, board_id: int) -> list:
    """The ids of the files on a board, in natural path order: what its search finds in its tab's library, plus
    what was put on it by hand, less what was taken off it."""
    board = get(db, board_id)
    if board is None:
        return []
    added, removed = _pins(db, board_id)
    found = []
    if board["query"]:
        ranges = _ranges(db, board["tab"])
        if ranges:
            sql, params = tag_query.build_sql(tag_query.parse(board["query"]), resolver, ranges)
            try:
                found = db.run_media_query(sql, params)
            except sqlite3.Error:
                found = []
    paths = dict(found)                                  # (the search leaves out files gone from the disk)
    extra = [m for m in added if m not in paths]
    if extra:
        gone = {r[0] for r in db.conn.execute(
            f"SELECT id FROM media WHERE missing = 1 AND id IN ({','.join('?' * len(extra))})", extra).fetchall()}
        for media_id, row in db.get_media_rows([m for m in extra if m not in gone]).items():
            paths[media_id] = row["path"]
    return [m for m in sorted(paths, key=lambda m: covers.natural_key(paths[m])) if m not in removed]


def collage(db, board_id: int, member_ids: list, count: int = 3) -> list:
    """The paths of the pictures on a board's cover: the one chosen by hand, then the mildest-rated pictures."""
    board = get(db, board_id)
    rows = db.get_media_rows(member_ids)
    pictures = [rows[m] | {"id": m} for m in member_ids if m in rows and rows[m]["kind"] in COVER_KINDS]
    mildness = lambda r: (r["rating"] if r["rating"] is not None else 0.5)
    chosen = []
    if board and board["cover_media_id"] in rows:
        chosen.append(rows[board["cover_media_id"]]["path"])
    for row in sorted(pictures, key=mildness):          # a stable sort keeps the natural order among equals
        if row["path"] not in chosen:
            chosen.append(row["path"])
        if len(chosen) >= count:
            break
    return chosen
