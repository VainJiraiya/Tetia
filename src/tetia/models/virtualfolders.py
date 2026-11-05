# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Virtual folders: folders that exist only in Tetia, to sort a library without touching the disk.

A virtual folder is created inside a real library folder (its `home`) and may hold, from the home folder or
anywhere below it: files, whole subfolders (a series, a one-file folder, an ordinary subfolder, shown as tiles)
and other virtual folders. Where a thing is shown is exclusive, like a file in a real folder: placing it in a
virtual folder takes it out of the grid it was in. Taking it out again puts it one level up, or back in its
real folder at the top. Nothing here moves, renames or deletes a file.

No Qt Quick in this module, so the rules are testable on their own (tests/test_virtualfolders.py).
"""
import logging
import os
import re
import sqlite3

from tetia.models import covers

logger = logging.getLogger(__name__)

MAX_NAME = 100


class VirtualFolderError(Exception):
    """Something the user can be told in a sentence."""


# ---- paths ------------------------------------------------------------------------------------------------

def _real(path: str) -> str:
    return os.path.realpath(path) if path else ""


def under(path: str, home: str) -> bool:
    """Whether `path` is `home` or inside it (both as real paths)."""
    return bool(home) and (path == home or path.startswith(home.rstrip(os.sep) + os.sep))


def strictly_under(path: str, home: str) -> bool:
    return under(path, home) and path != home


def clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        raise VirtualFolderError("Give the virtual folder a name.")
    if len(name) > MAX_NAME:
        raise VirtualFolderError(f"A virtual folder's name can have at most {MAX_NAME} characters.")
    return name


# ---- the folders themselves -------------------------------------------------------------------------------

def get(db, vid: int):
    row = db.conn.execute(
        "SELECT id, name, home, parent_id, cover_media_id FROM virtual_folder WHERE id = ?", (int(vid),)).fetchone()
    return dict(row) if row else None


def roots_at(db, home: str) -> list:
    """The virtual folders shown directly in the real folder `home` (its top-level ones), by name."""
    rows = db.conn.execute(
        "SELECT id, name, home, parent_id, cover_media_id FROM virtual_folder WHERE parent_id IS NULL AND home = ?",
        (_real(home),)).fetchall()
    return sorted((dict(r) for r in rows), key=lambda r: covers.natural_key(r["name"]))


def children_of(db, vid: int) -> list:
    rows = db.conn.execute(
        "SELECT id, name, home, parent_id, cover_media_id FROM virtual_folder WHERE parent_id = ?", (int(vid),)).fetchall()
    return sorted((dict(r) for r in rows), key=lambda r: covers.natural_key(r["name"]))


def has_roots_under(db, folder: str) -> bool:
    """Whether a top-level virtual folder was made in `folder` or below it: such a folder must stay visible
    in its parent's grid, or the virtual folder inside would be unreachable."""
    real = _real(folder)
    if not real:
        return False
    row = db.conn.execute(
        "SELECT 1 FROM virtual_folder WHERE parent_id IS NULL AND (home = ? OR substr(home, 1, ?) = ?) LIMIT 1",
        (real, len(real.rstrip(os.sep)) + 1, real.rstrip(os.sep) + os.sep)).fetchone()
    return row is not None


def _siblings(db, parent_id, home: str, exclude=None) -> list:
    if parent_id is None:
        rows = db.conn.execute("SELECT id, name FROM virtual_folder WHERE parent_id IS NULL AND home = ?", (home,))
    else:
        rows = db.conn.execute("SELECT id, name FROM virtual_folder WHERE parent_id = ?", (int(parent_id),))
    return [r["name"].casefold() for r in rows.fetchall() if r["id"] != exclude]


def _unique_name(db, parent_id, home: str, name: str, exclude=None) -> str:
    taken = set(_siblings(db, parent_id, home, exclude))
    if name.casefold() not in taken:
        return name
    n = 2
    while f"{name} ({n})".casefold() in taken:
        n += 1
    return f"{name} ({n})"


def create(db, name: str, home: str, parent_id=None) -> int:
    """A new, empty virtual folder in the real folder `home`, or inside the virtual folder `parent_id`
    (it then shares that folder's home). Returns its id."""
    name = clean_name(name)
    if parent_id is not None:
        parent = get(db, parent_id)
        if parent is None:
            raise VirtualFolderError("That virtual folder no longer exists.")
        home = parent["home"]
    else:
        home = _real(home)
        if not home:
            raise VirtualFolderError("Open a folder first.")
    if name.casefold() in _siblings(db, parent_id, home):
        raise VirtualFolderError(f"There is already a virtual folder called “{name}” here.")

    def _do():
        return db.conn.execute(
            "INSERT INTO virtual_folder (name, home, parent_id) VALUES (?, ?, ?)", (name, home, parent_id)).lastrowid
    return db._write(_do)


def rename(db, vid: int, name: str):
    name = clean_name(name)
    vf = get(db, vid)
    if vf is None:
        raise VirtualFolderError("That virtual folder no longer exists.")
    if name.casefold() in _siblings(db, vf["parent_id"], vf["home"], exclude=vf["id"]):
        raise VirtualFolderError(f"There is already a virtual folder called “{name}” here.")
    db._write(lambda: db.conn.execute("UPDATE virtual_folder SET name = ? WHERE id = ?", (name, int(vid))))


def descendants(db, vid: int) -> list:
    """The ids of every virtual folder inside `vid`, at any depth."""
    rows = db.conn.execute(
        "WITH RECURSIVE d(id) AS (SELECT id FROM virtual_folder WHERE parent_id = ? "
        "UNION ALL SELECT v.id FROM virtual_folder v JOIN d ON v.parent_id = d.id) SELECT id FROM d", (int(vid),))
    return [r["id"] for r in rows.fetchall()]


def crumbs(db, vid: int) -> list:
    """[(id, name)] from the outermost virtual folder down to `vid`."""
    chain = []
    seen = set()
    current = get(db, vid)
    while current is not None and current["id"] not in seen:
        seen.add(current["id"])
        chain.append((current["id"], current["name"]))
        current = get(db, current["parent_id"]) if current["parent_id"] is not None else None
    return list(reversed(chain))


def delete(db, vid: int):
    """Delete a virtual folder. What was in it is given back: to the folder it was in, or at the top level to
    where it really is. No file is touched."""
    vf = get(db, vid)
    if vf is None:
        return
    parent = vf["parent_id"]

    def _do():
        for child in children_of(db, vf["id"]):
            db.conn.execute("UPDATE virtual_folder SET parent_id = ?, name = ? WHERE id = ?",
                            (parent, _unique_name(db, parent, vf["home"], child["name"], exclude=child["id"]), child["id"]))
        if parent is None:
            db.conn.execute("DELETE FROM media_placement WHERE vfolder_id = ?", (vf["id"],))
            db.conn.execute("DELETE FROM folder_placement WHERE vfolder_id = ?", (vf["id"],))
        else:
            db.conn.execute("UPDATE media_placement SET vfolder_id = ? WHERE vfolder_id = ?", (parent, vf["id"]))
            db.conn.execute("UPDATE folder_placement SET vfolder_id = ? WHERE vfolder_id = ?", (parent, vf["id"]))
        db.conn.execute("DELETE FROM virtual_folder WHERE id = ?", (vf["id"],))
    db._write(_do)


# ---- what is in a virtual folder ----------------------------------------------------------------------------

def member_rows(db, vid: int) -> list:
    """[{id, path, name, kind, favorite, rating}] for the files placed directly in `vid` (files that are
    missing from the disk are left out), in natural name order."""
    rows = db.conn.execute(
        "SELECT m.id, m.path, m.name, m.kind, m.favorite, m.rating FROM media_placement p "
        "JOIN media m ON m.id = p.media_id WHERE p.vfolder_id = ? AND m.missing = 0", (int(vid),)).fetchall()
    return sorted((dict(r) for r in rows), key=lambda r: covers.natural_key(r["name"]))


def member_folders(db, vid: int) -> list:
    rows = db.conn.execute("SELECT folder FROM folder_placement WHERE vfolder_id = ?", (int(vid),)).fetchall()
    return sorted((r["folder"] for r in rows), key=lambda p: covers.natural_key(os.path.basename(p)))


def subtree_media(db, vid: int) -> list:
    """Paths and kinds of every file in `vid` and the virtual folders inside it."""
    rows = db.conn.execute(
        "WITH RECURSIVE d(id) AS (SELECT ? UNION ALL SELECT v.id FROM virtual_folder v JOIN d ON v.parent_id = d.id) "
        "SELECT m.id, m.path, m.kind FROM media_placement p JOIN media m ON m.id = p.media_id "
        "WHERE p.vfolder_id IN (SELECT id FROM d) AND m.missing = 0", (int(vid),)).fetchall()
    return [dict(r) for r in rows]


def subtree_folders(db, vid: int) -> list:
    rows = db.conn.execute(
        "WITH RECURSIVE d(id) AS (SELECT ? UNION ALL SELECT v.id FROM virtual_folder v JOIN d ON v.parent_id = d.id) "
        "SELECT folder FROM folder_placement WHERE vfolder_id IN (SELECT id FROM d)", (int(vid),)).fetchall()
    return [r["folder"] for r in rows]


def placement_of_media(db, media_id: int):
    row = db.conn.execute("SELECT vfolder_id FROM media_placement WHERE media_id = ?", (int(media_id),)).fetchone()
    return row["vfolder_id"] if row else None


def placed_media_ids(db, media_ids) -> set:
    """Which of these files are placed in a virtual folder (and so are not shown in their real folder)."""
    ids = [int(i) for i in media_ids]
    found = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        found.update(r[0] for r in db.conn.execute(
            f"SELECT media_id FROM media_placement WHERE media_id IN ({marks})", chunk))
    return found


def placed_paths_under(db, folder: str) -> set:
    """The paths of the placed files that really lie in `folder` or below it."""
    real = _real(folder).rstrip(os.sep) + os.sep
    rows = db.conn.execute(
        "SELECT m.path FROM media_placement p JOIN media m ON m.id = p.media_id WHERE substr(m.path, 1, ?) = ?",
        (len(real), real))
    return {r[0] for r in rows}


def placed_folder_keys(db) -> set:
    return {r[0] for r in db.conn.execute("SELECT folder FROM folder_placement")}


def folder_placement(db, key: str):
    row = db.conn.execute("SELECT vfolder_id FROM folder_placement WHERE folder = ?", (key,)).fetchone()
    return row["vfolder_id"] if row else None


# ---- moving things in and out ------------------------------------------------------------------------------

def place_media(db, vid: int, media_ids) -> tuple:
    """Put files in a virtual folder (taking them out of wherever they were). (moved, skipped): a file is
    skipped if it is not inside the virtual folder's home folder."""
    vf = get(db, vid)
    if vf is None:
        raise VirtualFolderError("That virtual folder no longer exists.")
    paths = db.get_media_paths(media_ids)
    ok = [i for i, p in paths.items() if under(_real(p), vf["home"])]

    def _do():
        db.conn.executemany(
            "INSERT INTO media_placement (media_id, vfolder_id) VALUES (?, ?) "
            "ON CONFLICT(media_id) DO UPDATE SET vfolder_id = excluded.vfolder_id", [(i, vf["id"]) for i in ok])
    db._write(_do)
    return len(ok), len(list(media_ids)) - len(ok)


def place_folders(db, vid: int, folder_keys) -> tuple:
    """Put real folders (tiles) in a virtual folder. A folder must lie below the virtual folder's home."""
    vf = get(db, vid)
    if vf is None:
        raise VirtualFolderError("That virtual folder no longer exists.")
    keys = [covers.folder_key(k) for k in folder_keys]
    ok = [k for k in keys if strictly_under(_real(k), vf["home"])]

    def _do():
        db.conn.executemany(
            "INSERT INTO folder_placement (folder, vfolder_id) VALUES (?, ?) "
            "ON CONFLICT(folder) DO UPDATE SET vfolder_id = excluded.vfolder_id", [(k, vf["id"]) for k in ok])
    db._write(_do)
    return len(ok), len(keys) - len(ok)


def place_vfolders(db, vid: int, child_ids) -> tuple:
    """Move virtual folders into another one. Not into themselves or what they hold, not out of their
    home's reach, and not onto a name already used there (the moved one then gets a number)."""
    target = get(db, vid)
    if target is None:
        raise VirtualFolderError("That virtual folder no longer exists.")
    moved = skipped = 0
    for child_id in child_ids:
        child = get(db, child_id)
        if (child is None or child["id"] == target["id"] or target["id"] in descendants(db, child["id"])
                or not under(child["home"], target["home"])):
            skipped += 1
            continue
        name = _unique_name(db, target["id"], target["home"], child["name"], exclude=child["id"])
        db._write(lambda c=child, n=name: db.conn.execute(
            "UPDATE virtual_folder SET parent_id = ?, name = ? WHERE id = ?", (target["id"], n, c["id"])))
        moved += 1
    return moved, skipped


def unplace_media(db, media_ids) -> int:
    """Take files out of the virtual folder they are in: up into the folder it is in, or (from a top-level
    virtual folder) back to their real folder. Returns how many moved."""
    count = 0

    def _do():
        nonlocal count
        for media_id in media_ids:
            vid = placement_of_media(db, media_id)
            if vid is None:
                continue
            vf = get(db, vid)
            if vf is not None and vf["parent_id"] is not None:
                db.conn.execute("UPDATE media_placement SET vfolder_id = ? WHERE media_id = ?", (vf["parent_id"], int(media_id)))
            else:
                db.conn.execute("DELETE FROM media_placement WHERE media_id = ?", (int(media_id),))
            count += 1
    db._write(_do)
    return count


def unplace_folders(db, folder_keys) -> int:
    count = 0

    def _do():
        nonlocal count
        for raw in folder_keys:
            key = covers.folder_key(raw)
            vid = folder_placement(db, key)
            if vid is None:
                continue
            vf = get(db, vid)
            if vf is not None and vf["parent_id"] is not None:
                db.conn.execute("UPDATE folder_placement SET vfolder_id = ? WHERE folder = ?", (vf["parent_id"], key))
            else:
                db.conn.execute("DELETE FROM folder_placement WHERE folder = ?", (key,))
            count += 1
    db._write(_do)
    return count


def unplace_vfolders(db, child_ids) -> int:
    """Move virtual folders up one level (out of a top-level virtual folder they stay in their home)."""
    count = 0
    for child_id in child_ids:
        child = get(db, child_id)
        if child is None or child["parent_id"] is None:
            continue
        parent = get(db, child["parent_id"])
        grand = parent["parent_id"] if parent else None
        name = _unique_name(db, grand, child["home"], child["name"], exclude=child["id"])
        db._write(lambda c=child, g=grand, n=name: db.conn.execute(
            "UPDATE virtual_folder SET parent_id = ?, name = ? WHERE id = ?", (g, n, c["id"])))
        count += 1
    return count


# ---- where a selection can go ------------------------------------------------------------------------------

def targets(db, media_ids=(), folder_keys=(), exclude_vfolders=()) -> list:
    """The virtual folders a selection can be put in, as [{id, name, depth, home}] in tree order: those whose
    home folder holds every selected thing. (A virtual folder being moved is not offered itself, nor anything
    inside it.)"""
    paths = [_real(p) for p in db.get_media_paths(media_ids).values()]
    folders = [_real(covers.folder_key(k)) for k in folder_keys]
    banned = set(int(i) for i in exclude_vfolders)
    for vid in list(banned):
        banned.update(descendants(db, vid))
    rows = [dict(r) for r in db.conn.execute("SELECT id, name, home, parent_id FROM virtual_folder")]
    covering = {}
    for row in rows:
        if row["id"] in banned:
            continue
        home = row["home"]
        if all(under(p, home) for p in paths) and all(strictly_under(f, home) for f in folders) \
                and all(under(_real(get(db, b)["home"]), home) for b in exclude_vfolders if get(db, b)):
            covering[row["id"]] = row
    children = {}
    top = []
    for row in covering.values():
        if row["parent_id"] in covering:
            children.setdefault(row["parent_id"], []).append(row)
        else:
            top.append(row)
    ordered = []

    def walk(row, depth):
        ordered.append({"id": row["id"], "name": row["name"], "depth": depth, "home": row["home"]})
        for child in sorted(children.get(row["id"], []), key=lambda r: covers.natural_key(r["name"])):
            walk(child, depth + 1)
    for row in sorted(top, key=lambda r: (covers.natural_key(os.path.basename(r["home"])), covers.natural_key(r["name"]))):
        walk(row, 0)
    return ordered


def common_home(db, media_ids=(), folder_keys=()) -> str:
    """The nearest real folder that holds every selected thing, if they all belong to one library folder
    ('' if they do not: such a selection cannot be put in a virtual folder). For a selected folder it is the
    folder's parent."""
    places = [os.path.dirname(_real(p)) for p in db.get_media_paths(media_ids).values()]
    places += [os.path.dirname(_real(covers.folder_key(k))) for k in folder_keys]
    if not places:
        return ""
    try:
        common = os.path.commonpath(places)
    except ValueError:
        return ""
    roots = [_real(covers.folder_key(f)) for f in db.get_all_folders()]
    return common if any(under(common, root) for root in roots) else ""
