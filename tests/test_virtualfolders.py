# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest

from tetia.models import covers, virtualfolders as vf
from tetia.models.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "gallery.db")
    yield database
    database.close()


def media(db, path, kind="image"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    real = os.path.realpath(path)
    row = db.upsert_media(real, os.path.basename(real), kind, 1, 1, "h" + real)
    db.conn.commit()
    return row[0]


@pytest.fixture
def library(tmp_path, db):
    """Anime/ (a.jpg, b.jpg), Anime/Art/ (c.jpg), Anime/Art/Old/ (d.jpg), Other/ (z.jpg)."""
    root = tmp_path / "Anime"
    other = tmp_path / "Other"
    ids = {
        "a": media(db, str(root / "a.jpg")), "b": media(db, str(root / "b.jpg")),
        "c": media(db, str(root / "Art" / "c.jpg")), "d": media(db, str(root / "Art" / "Old" / "d.jpg")),
        "z": media(db, str(other / "z.jpg")),
    }
    db.add_folder(covers.folder_uri(str(root)), "photos")
    db.add_folder(covers.folder_uri(str(other)), "photos")
    return {"root": str(root), "other": str(other), "ids": ids}


# ---- the folders ------------------------------------------------------------------------------------------

def test_create_rename_and_names(db, library):
    root = library["root"]
    a = vf.create(db, "  Frieren  ", root)
    assert vf.get(db, a)["name"] == "Frieren"
    assert [r["name"] for r in vf.roots_at(db, root)] == ["Frieren"]
    with pytest.raises(vf.VirtualFolderError, match="already a virtual folder"):
        vf.create(db, "frieren", root)                                       # not even in another case
    vf.create(db, "Frieren", library["other"])                                # another folder: no clash
    with pytest.raises(vf.VirtualFolderError, match="name"):
        vf.create(db, "   ", root)
    with pytest.raises(vf.VirtualFolderError, match="at most"):
        vf.create(db, "x" * 101, root)
    b = vf.create(db, "Marin", root)
    with pytest.raises(vf.VirtualFolderError):
        vf.rename(db, b, "FRIEREN")
    vf.rename(db, b, "Marin K")
    assert vf.get(db, b)["name"] == "Marin K"


def test_nesting_shares_the_home_and_names_are_per_level(db, library):
    outer = vf.create(db, "Characters", library["root"])
    inner = vf.create(db, "Frieren", library["root"], parent_id=outer)
    assert vf.get(db, inner)["home"] == vf.get(db, outer)["home"]
    assert [r["name"] for r in vf.children_of(db, outer)] == ["Frieren"]
    assert vf.roots_at(db, library["root"])[0]["id"] == outer                # the inner one is not at the top
    vf.create(db, "Frieren", library["root"])                                # same name, another level: fine
    with pytest.raises(vf.VirtualFolderError):
        vf.create(db, "Frieren", "", parent_id=outer)
    assert vf.crumbs(db, inner) == [(outer, "Characters"), (inner, "Frieren")]
    assert vf.descendants(db, outer) == [inner]


# ---- placing and taking out -----------------------------------------------------------------------------------

def test_placing_a_file_takes_it_out_of_its_folder_and_is_exclusive(db, library):
    ids, root = library["ids"], library["root"]
    one = vf.create(db, "One", root)
    two = vf.create(db, "Two", root)
    assert vf.place_media(db, one, [ids["a"], ids["b"]]) == (2, 0)
    assert vf.placed_media_ids(db, ids.values()) == {ids["a"], ids["b"]}
    assert [m["name"] for m in vf.member_rows(db, one)] == ["a.jpg", "b.jpg"]
    assert vf.place_media(db, two, [ids["a"]]) == (1, 0)                     # moving again: it only lives in one place
    assert [m["name"] for m in vf.member_rows(db, one)] == ["b.jpg"]
    assert vf.placement_of_media(db, ids["a"]) == two


def test_items_come_from_anywhere_below_the_home_and_nowhere_else(db, library):
    ids = library["ids"]
    top = vf.create(db, "Everything", library["root"])
    assert vf.place_media(db, top, [ids["c"], ids["d"], ids["a"]]) == (3, 0)  # a subfolder's files and deeper ones
    assert vf.place_media(db, top, [ids["z"]]) == (0, 1)                     # a different library folder is refused
    sub = vf.create(db, "Art stuff", os.path.join(library["root"], "Art"))
    assert vf.place_media(db, sub, [ids["a"]]) == (0, 1)                     # above the home is refused too
    assert vf.place_media(db, sub, [ids["c"]]) == (1, 0)


def test_missing_files_are_not_shown(db, library):
    ids = library["ids"]
    top = vf.create(db, "T", library["root"])
    vf.place_media(db, top, [ids["a"], ids["b"]])
    db.conn.execute("UPDATE media SET missing = 1 WHERE id = ?", (ids["a"],))
    assert [m["name"] for m in vf.member_rows(db, top)] == ["b.jpg"]


def test_a_removed_file_leaves_the_virtual_folder(db, library):
    ids = library["ids"]
    top = vf.create(db, "T", library["root"])
    vf.place_media(db, top, [ids["a"]])
    db.delete_media([ids["a"]])                                              # trashed
    assert vf.member_rows(db, top) == []
    assert vf.placed_media_ids(db, [ids["a"]]) == set()


def test_removing_goes_up_one_level_and_then_home(db, library):
    ids, root = library["ids"], library["root"]
    outer = vf.create(db, "Outer", root)
    inner = vf.create(db, "Inner", root, parent_id=outer)
    vf.place_media(db, inner, [ids["a"]])
    assert vf.unplace_media(db, [ids["a"]]) == 1
    assert vf.placement_of_media(db, ids["a"]) == outer                      # up into the folder it was in
    assert vf.unplace_media(db, [ids["a"]]) == 1
    assert vf.placement_of_media(db, ids["a"]) is None                       # and then back to its real folder
    assert vf.unplace_media(db, [ids["a"]]) == 0                             # nothing left to remove


def test_whole_folders_can_be_placed_and_taken_out(db, library):
    root = library["root"]
    art = os.path.join(root, "Art")
    top = vf.create(db, "Sorted", root)
    assert vf.place_folders(db, top, [art]) == (1, 0)
    assert vf.folder_placement(db, covers.folder_key(art)) == top
    assert vf.placed_folder_keys(db) == {covers.folder_key(art)}
    assert vf.member_folders(db, top) == [covers.folder_key(art)]
    assert vf.place_folders(db, top, [root]) == (0, 1)                       # a folder cannot go inside itself
    assert vf.place_folders(db, top, [library["other"]]) == (0, 1)
    assert vf.unplace_folders(db, [art]) == 1
    assert vf.placed_folder_keys(db) == set()


def test_virtual_folders_can_be_nested_but_not_into_themselves(db, library):
    root = library["root"]
    a = vf.create(db, "A", root)
    b = vf.create(db, "B", root)
    c = vf.create(db, "C", root, parent_id=b)
    assert vf.place_vfolders(db, a, [b]) == (1, 0)
    assert vf.get(db, b)["parent_id"] == a
    assert vf.place_vfolders(db, c, [a]) == (0, 1)                           # A holds B holds C: cannot go into C
    assert vf.place_vfolders(db, a, [a]) == (0, 1)
    assert vf.unplace_vfolders(db, [b]) == 1
    assert vf.get(db, b)["parent_id"] is None
    assert vf.unplace_vfolders(db, [b]) == 0                                  # already at the top
    d = vf.create(db, "D", root)
    vf.create(db, "C", root, parent_id=d)                                     # D already holds a C
    assert vf.place_vfolders(db, d, [c]) == (1, 0) and vf.get(db, c)["name"] == "C (2)"   # a clash gets a number


def test_a_virtual_folder_cannot_leave_its_homes_reach(db, library):
    deep = vf.create(db, "Deep", os.path.join(library["root"], "Art"))
    top = vf.create(db, "Top", library["root"])
    assert vf.place_vfolders(db, top, [deep]) == (1, 0)                       # a deeper home fits in a higher one
    other = vf.create(db, "Other", library["other"])
    assert vf.place_vfolders(db, top, [other]) == (0, 1)                      # another library folder does not


def test_deleting_gives_everything_back(db, library):
    ids, root = library["ids"], library["root"]
    art = os.path.join(root, "Art")
    outer = vf.create(db, "Outer", root)
    inner = vf.create(db, "Inner", root, parent_id=outer)
    vf.place_media(db, inner, [ids["a"]])
    vf.place_folders(db, inner, [art])
    vf.delete(db, inner)
    assert vf.get(db, inner) is None
    assert vf.placement_of_media(db, ids["a"]) == outer                      # back in the folder that held Inner
    assert vf.folder_placement(db, covers.folder_key(art)) == outer
    kid = vf.create(db, "Kid", root, parent_id=outer)
    vf.delete(db, outer)
    assert vf.placement_of_media(db, ids["a"]) is None                       # a top-level one: back to the real folder
    assert vf.folder_placement(db, covers.folder_key(art)) is None
    assert vf.get(db, kid)["parent_id"] is None                              # the folder inside moved up
    assert [r["name"] for r in vf.roots_at(db, root)] == ["Kid"]


def test_deleting_a_folder_renames_a_clashing_child(db, library):
    root = library["root"]
    outer = vf.create(db, "Outer", root)
    vf.create(db, "Same", root)
    inner = vf.create(db, "Same", root, parent_id=outer)
    vf.delete(db, outer)
    assert vf.get(db, inner)["name"] == "Same (2)"


# ---- what the grids need ------------------------------------------------------------------------------------

def test_a_folder_with_a_virtual_folder_in_it_stays_visible(db, library):
    root = library["root"]
    art = os.path.join(root, "Art")
    old = os.path.join(art, "Old")
    assert not vf.has_roots_under(db, art)
    vf.create(db, "Inside Old", old)
    assert vf.has_roots_under(db, art) and vf.has_roots_under(db, old) and vf.has_roots_under(db, root)
    assert not vf.has_roots_under(db, library["other"])
    assert not vf.has_roots_under(db, str(art) + "x")                         # a folder with a similar name


def test_placed_paths_under(db, library):
    ids, root = library["ids"], library["root"]
    top = vf.create(db, "T", root)
    vf.place_media(db, top, [ids["c"], ids["a"]])
    art = os.path.join(root, "Art")
    assert {os.path.basename(p) for p in vf.placed_paths_under(db, art)} == {"c.jpg"}
    assert {os.path.basename(p) for p in vf.placed_paths_under(db, root)} == {"a.jpg", "c.jpg"}


def test_targets_list_the_folders_that_can_take_a_selection(db, library):
    ids, root = library["ids"], library["root"]
    art = os.path.join(root, "Art")
    chars = vf.create(db, "Characters", root)
    frieren = vf.create(db, "Frieren", root, parent_id=chars)
    sketches = vf.create(db, "Sketches", art)
    vf.create(db, "Elsewhere", library["other"])
    spare = vf.create(db, "Spare", root)
    names = lambda items: [(t["name"], t["depth"]) for t in items]
    assert names(vf.targets(db, [ids["c"]])) == [("Characters", 0), ("Frieren", 1), ("Spare", 0), ("Sketches", 0)]   # by home folder, then name
    assert names(vf.targets(db, [ids["a"]])) == [("Characters", 0), ("Frieren", 1), ("Spare", 0)]   # a is above Sketches' home
    assert names(vf.targets(db, [ids["a"], ids["z"]])) == []                            # two library folders: nowhere
    assert names(vf.targets(db, [], [art])) == [("Characters", 0), ("Frieren", 1), ("Spare", 0)]    # a folder tile goes below the home
    assert names(vf.targets(db, [], [root])) == []
    assert names(vf.targets(db, [], [], exclude_vfolders=[chars])) == [("Spare", 0)]  # not into itself or what it holds; Sketches' home is too deep


def test_common_home(db, library):
    ids, root = library["ids"], library["root"]
    assert vf.common_home(db, [ids["a"], ids["b"]]) == os.path.realpath(root)
    assert vf.common_home(db, [ids["a"], ids["c"]]) == os.path.realpath(root)
    assert vf.common_home(db, [ids["c"], ids["d"]]) == os.path.realpath(os.path.join(root, "Art"))
    assert vf.common_home(db, [ids["a"], ids["z"]]) == ""                               # two library folders
    assert vf.common_home(db, [], [os.path.join(root, "Art")]) == os.path.realpath(root)
    assert vf.common_home(db, []) == ""
