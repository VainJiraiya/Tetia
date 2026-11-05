# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest
from PySide6.QtCore import Qt

from tetia.models import covers, virtualfolders as vf
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel
from tetia.models.subfolderModel import SubfolderModel
from tetia.models.virtualFolderService import VirtualFolderService, split_tiles


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(b"x" * 10)
    return path


@pytest.fixture
def lib(tmp_path, qapp):
    """Anime/ a.jpg b.jpg  Art/ c.jpg d.jpg  Old/ e.jpg  Clip.mp4"""
    root = tmp_path / "Anime"
    for name in ("a.jpg", "b.jpg"):
        touch(str(root / name))
    touch(str(root / "Clip.mp4"))
    touch(str(root / "Art" / "c.jpg"))
    touch(str(root / "Art" / "d.jpg"))
    touch(str(root / "Old" / "e.jpg"))
    db = get_database()
    db.add_folder(covers.folder_uri(str(root)), "photos")
    media = MediaModel()
    media.load_from_qurl(str(root))
    ids = {}
    for sub in ("", "Art", "Old"):
        other = MediaModel()
        other.load_from_qurl(str(root / sub) if sub else str(root))
        for item in other._visible_items:
            ids[item["file_name"]] = item["media_id"]
    return {"root": str(root), "ids": ids, "db": db}


def names(model):
    return [model.data(model.index(r), SubfolderModel.Roles.NameRole) for r in range(model.rowCount())]


def file_names(model):
    return [i["file_name"] for i in model._visible_items]


def tiles(root):
    model = SubfolderModel()
    model.load(root)
    return model


def test_placed_files_leave_their_folder_and_appear_in_the_virtual_one(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    vf.place_media(db, one, [ids["a.jpg"], ids["c.jpg"]])        # c.jpg is from a real subfolder
    media = MediaModel()
    media.load_from_qurl(root)
    assert file_names(media) == ["b.jpg", "Clip.mp4"]            # a.jpg is gone from here
    media.load_virtual_folder(one)
    assert file_names(media) == ["a.jpg", "c.jpg"]
    assert media.virtualId == one and media.folderPath == ""
    media.load_from_qurl(str(os.path.join(root, "Art")))
    assert file_names(media) == ["d.jpg"] and media.virtualId == -1


def test_the_tab_filter_applies_inside_a_virtual_folder(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    vf.place_media(db, one, [ids["a.jpg"], ids["Clip.mp4"]])
    media = MediaModel()
    media.filterMode = MediaModel.FilterMode.ImagesOnly
    media.load_virtual_folder(one)
    assert file_names(media) == ["a.jpg"]
    media.filterMode = MediaModel.FilterMode.VideosOnly
    assert file_names(media) == ["Clip.mp4"]


def test_a_virtual_folder_can_be_sorted_like_a_folder(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    vf.place_media(db, one, [ids["a.jpg"], ids["b.jpg"], ids["c.jpg"]])
    media = MediaModel()
    media.load_virtual_folder(one)
    assert file_names(media) == ["a.jpg", "b.jpg", "c.jpg"]
    media.sortMode = MediaModel.SortMode.NameDescending
    assert file_names(media) == ["c.jpg", "b.jpg", "a.jpg"]


def test_virtual_folder_tiles_sit_among_the_subfolders(lib):
    db, root = lib["db"], lib["root"]
    vf.create(db, "Frieren", root)
    model = tiles(root)
    assert names(model) == ["Art", "Frieren", "Old"]                    # an empty one shows
    i = names(model).index("Frieren")
    assert model.data(model.index(i), SubfolderModel.Roles.IsVirtualRole) is True
    assert model.data(model.index(i), SubfolderModel.Roles.PathRole).startswith("virtual:")
    assert model.data(model.index(0), SubfolderModel.Roles.IsVirtualRole) is False


def test_a_virtual_tile_counts_and_pictures_what_is_in_it(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    vf.place_media(db, one, [ids["b.jpg"], ids["a.jpg"], ids["Clip.mp4"]])
    model = tiles(root)
    i = names(model).index("One")
    index = model.index(i)
    assert model.data(index, SubfolderModel.Roles.ItemCountRole) == 3
    assert model.data(index, SubfolderModel.Roles.HeroPathRole).endswith("a.jpg")
    model.filterMode = MediaModel.FilterMode.VideosOnly                  # the Videos tab counts videos only
    assert model.data(model.index(names(model).index("One")), SubfolderModel.Roles.ItemCountRole) == 1
    model.filterMode = MediaModel.FilterMode.MangaOnly                    # nothing for the Manga tab in it: no tile
    assert "One" not in names(model)


def test_an_emptied_subfolder_is_hidden_until_something_returns(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    vf.place_media(db, one, [ids["c.jpg"], ids["d.jpg"]])                # everything in Art
    assert names(tiles(root)) == ["Old", "One"]                          # Art is gone
    vf.unplace_media(db, [ids["c.jpg"]])
    assert names(tiles(root)) == ["Art", "Old", "One"]


def test_a_subfolder_with_a_virtual_folder_of_its_own_stays(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    vf.place_media(db, one, [ids["c.jpg"], ids["d.jpg"]])
    vf.create(db, "Inside Art", os.path.join(root, "Art"))
    assert "Art" in names(tiles(root))                                   # or the folder inside would be unreachable


def test_a_placed_subfolder_moves_to_the_virtual_folder(lib):
    db, root = lib["db"], lib["root"]
    one = vf.create(db, "One", root)
    vf.place_folders(db, one, [os.path.join(root, "Art")])
    assert names(tiles(root)) == ["Old", "One"]
    inside = SubfolderModel()
    inside.loadVirtual(one)
    assert names(inside) == ["Art"]
    assert inside.data(inside.index(0), SubfolderModel.Roles.PathRole).startswith("file:")   # still a real folder
    vf.unplace_folders(db, [os.path.join(root, "Art")])
    assert names(tiles(root)) == ["Art", "Old", "One"]


def test_tiles_of_a_virtual_folder_nested_inside_another(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    outer = vf.create(db, "Outer", root)
    inner = vf.create(db, "Inner", root, parent_id=outer)
    vf.place_media(db, inner, [ids["a.jpg"]])
    assert "Inner" not in names(tiles(root)) and "Outer" in names(tiles(root))
    model = SubfolderModel()
    model.loadVirtual(outer)
    assert names(model) == ["Inner"]
    assert model.data(model.index(0), SubfolderModel.Roles.ItemCountRole) == 1
    outer_count = names(tiles(root)).index("Outer")
    assert tiles(root).data(tiles(root).index(outer_count), SubfolderModel.Roles.ItemCountRole) == 1   # what is below counts


def test_a_files_count_on_a_folder_tile_leaves_with_the_file(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    model = tiles(root)
    art = names(model).index("Art")
    assert model.data(model.index(art), SubfolderModel.Roles.ItemCountRole) == 2
    vf.place_media(db, one, [ids["c.jpg"]])
    model = tiles(root)
    assert model.data(model.index(names(model).index("Art")), SubfolderModel.Roles.ItemCountRole) == 1


def test_a_picture_in_a_virtual_folder_can_be_its_cover(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    one = vf.create(db, "One", root)
    vf.place_media(db, one, [ids["a.jpg"], ids["b.jpg"]])
    media = MediaModel()
    media.load_virtual_folder(one)
    assert media.setFolderCover(ids["b.jpg"]) is True
    model = tiles(root)
    index = model.index(names(model).index("One"))
    assert model.data(index, SubfolderModel.Roles.HeroPathRole).endswith("b.jpg")
    assert model.data(index, SubfolderModel.Roles.HasCustomCoverRole) is True


# ---- the service ----------------------------------------------------------------------------------------------

def test_split_tiles():
    assert split_tiles(["virtual:3", "file:///x/Art", "virtual:oops", ""]) == (["/x/Art"], [3])


def test_the_service_moves_and_reports(lib):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    service = VirtualFolderService()
    options = service.options([ids["a.jpg"], ids["b.jpg"]], [])
    assert options["canCreate"] and options["targets"] == []
    made = service.placeInNew("Sorted", -1, options["home"], [ids["a.jpg"], ids["b.jpg"]], [])
    assert made["moved"] == 2 and made["skipped"] == 0
    assert [t["name"] for t in service.options([ids["c.jpg"]], [])["targets"]] == ["Sorted"]
    assert service.place(made["id"], [ids["c.jpg"]], [covers.folder_uri(os.path.join(root, "Old"))]) == {"moved": 2, "skipped": 0}
    assert service.info(made["id"])["crumbs"] == ["Sorted"]
    assert service.remove([ids["a.jpg"]], []) == 1
    assert "error" in service.create("sorted", root, -1)                  # the name is taken
    assert "error" in service.create("", root, -1)
    sub = service.create("Sub", "", made["id"])["id"]
    assert service.info(sub)["crumbs"] == ["Sorted", "Sub"] and service.info(sub)["parentId"] == made["id"]
    assert service.rename(sub, "Deeper") == {}
    service.deleteFolder(made["id"])
    assert service.info(made["id"]) == {}
    assert service.info(sub)["parentId"] == -1                            # the folder inside moved up
    media = MediaModel()
    media.load_from_qurl(root)
    assert "a.jpg" in file_names(media) and "b.jpg" in file_names(media)  # everything came back


def test_the_service_refuses_a_selection_from_two_library_folders(lib, tmp_path):
    db, root, ids = lib["db"], lib["root"], lib["ids"]
    other = tmp_path / "Other"
    touch(str(other / "z.jpg"))
    db.add_folder(covers.folder_uri(str(other)), "photos")
    m = MediaModel()
    m.load_from_qurl(str(other))
    z = m._visible_items[0]["media_id"]
    options = VirtualFolderService().options([ids["a.jpg"], z], [])
    assert options == {"home": "", "targets": [], "canCreate": False}


def test_the_service_signals_a_change(lib):
    service = VirtualFolderService()
    seen = []
    service.changed.connect(lambda: seen.append(1))
    service.create("X", lib["root"], -1)
    assert seen == [1]
