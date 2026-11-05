# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os

from tetia.models import covers, series
from tetia.models.database import Database, get_database


def _touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


def test_chapters_in_natural_order_and_only_chapter_files(tmp_path):
    _touch(tmp_path, "ch 10.cbz", "ch 2.cbz", "ch 1.cbz", "notes.txt", "cover.png", ".hidden.cbz")
    names = [os.path.basename(p) for p in series.chapters(str(tmp_path))]
    assert names == ["ch 1.cbz", "ch 2.cbz", "ch 10.cbz"]
    assert series.chapters(str(tmp_path / "missing")) == []


def test_loose_cover_names_and_priority(tmp_path):
    assert series.loose_cover(str(tmp_path)) == ""
    _touch(tmp_path, "A1.JPG", "page.png")
    assert os.path.basename(series.loose_cover(str(tmp_path))) == "A1.JPG"
    _touch(tmp_path, "Cover.webp")                       # cover beats a1
    assert os.path.basename(series.loose_cover(str(tmp_path))) == "Cover.webp"
    _touch(tmp_path, "cover.cbz")                        # not an image: ignored
    assert os.path.basename(series.loose_cover(str(tmp_path))) == "Cover.webp"


def test_chapter_to_open(tmp_path):
    _touch(tmp_path, "c1.cbz", "c2.cbz", "c3.cbz")
    folder = str(tmp_path)
    c = lambda n: os.path.join(folder, f"c{n}.cbz")
    assert series.chapter_to_open(folder, "", "resume") == c(1)          # nothing read yet
    assert series.chapter_to_open(folder, c(2), "resume") == c(2)
    assert series.chapter_to_open(folder, c(2), "next") == c(3)
    assert series.chapter_to_open(folder, c(3), "next") == c(3)          # last one stays
    assert series.chapter_to_open(folder, c(2), "first") == c(1)
    assert series.chapter_to_open(folder, "/gone.cbz", "resume") == c(1)  # deleted since
    assert series.chapter_to_open(str(tmp_path / "none"), "", "resume") == ""


def test_hero_prefers_cover_then_loose_picture_then_first_chapter(tmp_path):
    _touch(tmp_path, "c2.cbz", "c1.cbz")
    key = str(tmp_path)
    assert covers.hero_path(key, None, True) == os.path.join(key, "c1.cbz")
    _touch(tmp_path, "poster.png")
    assert covers.hero_path(key, None, True) == os.path.join(key, "poster.png")
    chosen = tmp_path / "mine.png"
    chosen.write_bytes(b"x")
    assert covers.hero_path(key, str(chosen), True) == str(chosen)


def test_series_flag_and_last_read_are_stored(tmp_path):
    db = get_database()
    key = str(tmp_path)
    assert db.get_collection_meta(key)["is_series"] is False
    db.set_collection_series(key, True)
    db.set_collection_last_read(key, "/x/c2.cbz")
    meta = db.get_collection_meta(key)
    assert meta["is_series"] is True and meta["last_read"] == "/x/c2.cbz"
    assert db.get_collections_meta([key])[key]["is_series"] is True
    db.set_collection_series(key, False)                  # forgets the chapter, drops the row
    assert db.get_collection_meta(key) == {"cover_path": None, "favorite": False,
                                           "is_series": False, "last_read": None}


def test_series_survives_a_favorite_toggle(tmp_path):
    db = get_database()
    key = str(tmp_path)
    db.set_collection_series(key, True)
    db.set_collection_favorite(key, True)
    db.set_collection_favorite(key, False)
    assert db.get_collection_meta(key)["is_series"] is True


def test_folder_model_roles_and_open_series(tmp_path, qapp):
    from tetia.models.folderModel import FolderModel
    _touch(tmp_path / "Dragon", "ch 2.cbz", "ch 1.cbz", "cover.png")
    model = FolderModel()
    model.currentCategory = "manga"
    folder = covers.folder_uri(str(tmp_path / "Dragon"))
    model.addFolder(folder, "manga")
    model.setSeries(folder, True)
    index = model.index(0)
    assert model.data(index, model.Roles.IsSeriesRole) is True
    assert model.data(index, model.Roles.ItemCountRole) == 2             # chapters, not pictures
    assert model.data(index, model.Roles.HeroPathRole).endswith("cover.png")
    assert model.openSeries(folder, "resume").endswith("ch%201.cbz")
    assert model.openSeries(folder, "next").endswith("ch%202.cbz")
    assert model.openSeries(folder, "resume").endswith("ch%202.cbz")      # remembered


# A real messy download: several groups, volumes out of file-name order, decimal extras
MESSY = """7 bottles of vodka_Vol.1 Ch.9_e73ba2.cbz
7 bottles of vodka_Vol.2 Ch.21.1_83f1c9.cbz
7 bottles of vodka_Vol.2 Ch.21.2_05ecfd.cbz
7 bottles of vodka_Vol.2 Ch.21_be8c53.cbz
7 bottles of vodka_Vol.2 Ch.22.1_c64593.cbz
7 bottles of vodka_Vol.2 Ch.22_3269b0.cbz
_a_nonymous_Vol.2 Ch.17_0e44f5.cbz
_a_nonymous_Vol.2 Ch.20_2270c6.cbz
Copium Scans_Vol.3 Ch.27.5 - Twitter Extra_db4165.cbz
Melonpan Translation_Vol.1 Ch.5_cf4034.cbz
Melonpan Translation_Vol.1 Ch.8_78fd07.cbz
Skythewood_Vol.1 Ch.10_7e9ecf.cbz
Skythewood_Vol.1 Ch.16.5 - Vol.1 Extras_fa82e9.cbz
Skythewood_Vol.1 Ch.16.6 - Vol.1 Extras 2_ad42fc.cbz
Skythewood_Vol.1 Ch.16_99c996.cbz
Skythewood_Vol.2 Ch.23_07a0dd.cbz
Skythewood_Vol.2 Ch.23.1 - Twitter Extra_9bd96f.cbz
Skythewood_Vol.2 Ch.24.5 - New Year Extra_e36908.cbz
Skythewood_Vol.2 Ch.24_c76a4a.cbz
Skythewood_Vol.3 Ch.25.5 - Twitter Extra_115f67.cbz
Skythewood_Vol.3 Ch.25_6956eb.cbz
Skythewood_Vol.3 Ch.26.7 - April Fools' Special_9e4bd8.cbz
Skythewood_Vol.3 Ch.26_b2adb8.cbz
Skythewood_Vol.4 Ch.31.5 - Twitter Extra_c0e16d.cbz
Skythewood_Vol.4 Ch.31_a62c41.cbz
Translational Trainwreck & Melonpan Translation_Vol.1 Ch.1_0e1747.cbz
Translational Trainwreck & Melonpan Translation_Vol.1 Ch.4_842f73.cbz""".splitlines()


def test_messy_downloads_come_out_in_reading_order():
    import random
    shuffled = MESSY[:]
    random.Random(1).shuffle(shuffled)
    ordered = series.sort_chapter_names(shuffled)
    chapter = lambda n: series._number(series._CHAPTER, n)
    volume = lambda n: series._number(series._VOLUME, n)
    assert [chapter(n) for n in ordered] == sorted(chapter(n) for n in MESSY)
    assert [volume(n) for n in ordered] == sorted(volume(n) for n in MESSY)   # volumes never go backwards
    assert ordered[0].endswith("Ch.1_0e1747.cbz") and ordered[-1].endswith("Ch.31.5 - Twitter Extra_c0e16d.cbz")
    # 16 < 16.5 < 16.6 < 17, 21 < 21.1 < 21.2
    pos = {n: i for i, n in enumerate(ordered)}
    key = lambda text: next(n for n in ordered if text in n)
    assert pos[key("Ch.16_")] < pos[key("Ch.16.5")] < pos[key("Ch.16.6")] < pos[key("Ch.17_")]
    assert pos[key("Ch.21_")] < pos[key("Ch.21.1_")] < pos[key("Ch.21.2")]


def test_sort_falls_back_sensibly():
    # clean names: same as a natural sort
    assert series.sort_chapter_names(["ch 10.cbz", "ch 2.cbz", "ch 1.cbz"]) == ["ch 1.cbz", "ch 2.cbz", "ch 10.cbz"]
    # no keywords at all: natural sort
    assert series.sort_chapter_names(["b 10.cbz", "b 9.cbz", "a.cbz"]) == ["a.cbz", "b 9.cbz", "b 10.cbz"]
    # volume-only files
    assert series.sort_chapter_names(["X Vol.10.cbz", "X Vol.2.cbz"]) == ["X Vol.2.cbz", "X Vol.10.cbz"]
    # "Epoch 5" is not a chapter
    assert series._number(series._CHAPTER, "Epoch 5") == ()
    assert series.sort_chapter_names([]) == []


def test_previous_chapter(tmp_path):
    _touch(tmp_path, "c1.cbz", "c2.cbz", "c3.cbz")
    folder = str(tmp_path)
    c = lambda n: os.path.join(folder, f"c{n}.cbz")
    assert series.chapter_to_open(folder, c(3), "previous") == c(2)
    assert series.chapter_to_open(folder, c(1), "previous") == c(1)      # first stays put
    assert series.chapter_to_open(folder, "", "previous") == c(1)


def test_subfolder_model_can_make_a_series(tmp_path, qapp):
    from tetia.models.mediaModel import MediaModel
    from tetia.models.subfolderModel import SubfolderModel
    _touch(tmp_path / "Parent" / "Dragon", "Vol.1 Ch.2.cbz", "Vol.1 Ch.1.cbz")
    model = SubfolderModel()
    model.filterMode = int(MediaModel.FilterMode.MangaOnly)
    model.load(str(tmp_path / "Parent"))
    child = covers.folder_uri(str(tmp_path / "Parent" / "Dragon"))
    assert model.data(model.index(0), model.Roles.IsSeriesRole) is False
    model.setSeries(child, True)
    index = model.index(0)
    assert model.data(index, model.Roles.IsSeriesRole) is True
    assert model.data(index, model.Roles.HeroPathRole).endswith("Ch.1.cbz")
    assert model.openSeries(child, "resume").endswith("Ch.1.cbz")
    assert model.openSeries(child, "next").endswith("Ch.2.cbz")
    assert model.openSeries(child, "previous").endswith("Ch.1.cbz")


def test_browse_chapters_uses_reading_order_only_for_a_series(tmp_path, qapp):
    from tetia.models.mediaModel import MediaModel
    folder = tmp_path / "Title"
    _touch(folder, "Zed_Vol.1 Ch.2_a.cbz", "Amy_Vol.1 Ch.3_b.cbz", "Zed_Vol.1 Ch.1_c.cbz")
    uri = covers.folder_uri(str(folder))

    def shown():
        model = MediaModel()
        model.filterMode = MediaModel.FilterMode.MangaOnly
        model.load_from_qurl(uri)
        return [model.data(model.index(i), MediaModel.Roles.FileNameRole) for i in range(model.rowCount())]

    assert shown()[0].startswith("Amy")                      # a plain folder: alphabetical
    series.set_series(get_database(), str(folder), True)
    assert [n.split("_")[1] for n in shown()] == ["Vol.1 Ch.1", "Vol.1 Ch.2", "Vol.1 Ch.3"]


def test_sort_modes_reorder_the_files_of_a_folder(tmp_path, qapp):
    from tetia.models.mediaModel import MediaModel
    folder = tmp_path / "Mixed"
    folder.mkdir()
    # name, size in bytes, age (older = larger number)
    for name, size, age in (("a.png", 30, 300), ("b.png", 10, 100), ("c.png", 20, 200)):
        path = folder / name
        path.write_bytes(b"x" * size)
        os.utime(path, (1_700_000_000 - age, 1_700_000_000 - age))
    model = MediaModel()
    model.filterMode = MediaModel.FilterMode.ImagesOnly
    model.load_from_qurl(covers.folder_uri(str(folder)))

    def shown():
        return [model.data(model.index(i), MediaModel.Roles.FileNameRole) for i in range(model.rowCount())]

    assert shown() == ["a.png", "b.png", "c.png"]                       # default
    for mode, expected in (
        (MediaModel.SortMode.NameDescending, ["c.png", "b.png", "a.png"]),
        (MediaModel.SortMode.NewestFirst, ["b.png", "c.png", "a.png"]),
        (MediaModel.SortMode.OldestFirst, ["a.png", "c.png", "b.png"]),
        (MediaModel.SortMode.LargestFirst, ["a.png", "c.png", "b.png"]),
        (MediaModel.SortMode.SmallestFirst, ["b.png", "c.png", "a.png"]),
    ):
        model.sortMode = mode
        assert shown() == expected, mode
    model.sortMode = MediaModel.SortMode.Default
    assert shown() == ["a.png", "b.png", "c.png"]


def test_sort_mode_does_not_reorder_search_results(tmp_path, qapp):
    from tetia.models.mediaModel import MediaModel
    folder = tmp_path / "Mixed"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        (folder / name).write_bytes(b"x")
    model = MediaModel()
    model.load_from_qurl(covers.folder_uri(str(folder)))
    ids = [model.data(model.index(i), MediaModel.Roles.MediaIdRole) for i in range(model.rowCount())]
    model.sortMode = MediaModel.SortMode.NameDescending
    model.load_media_ids(list(reversed(ids)))                           # ranked order from a search
    assert [model.data(model.index(i), MediaModel.Roles.MediaIdRole) for i in range(model.rowCount())] == list(reversed(ids))


# ---- the picture on a folder tile --------------------------------------------------------------------

def _folder_model(category, *folders):
    from tetia.models.folderModel import FolderModel
    model = FolderModel()
    model.currentCategory = category
    for folder in folders:
        model.addFolder(covers.folder_uri(str(folder)), category)
    return model


def _hero(model, row=0):
    return model.data(model.index(row), model.Roles.HeroPathRole)


def test_a_top_level_folder_shows_its_first_loose_cbz(tmp_path, qapp):
    manga = tmp_path / "Manga"
    _touch(manga, "ch 10.cbz", "ch 2.cbz", "notes.txt")
    model = _folder_model("manga", manga)
    assert _hero(model) == str(manga / "ch 2.cbz")                       # natural order, the file itself


def test_a_top_level_folder_borrows_the_picture_of_a_series_inside_it(tmp_path, qapp):
    library = tmp_path / "Library"
    _touch(library / "Dragon", "Vol.1 Ch.2.cbz", "Vol.1 Ch.1.cbz")
    _touch(library / "Other", "x.cbz")
    model = _folder_model("manga", library)
    assert _hero(model) == str(library / "Dragon" / "Vol.1 Ch.1.cbz")    # first folder, first chapter
    series.set_series(get_database(), str(library / "Dragon"), True)
    assert _hero(model) == str(library / "Dragon" / "Vol.1 Ch.1.cbz")    # same, now as a series
    _touch(library / "Dragon", "cover.png")                              # a loose cover on the series
    assert _hero(model) == str(library / "Dragon" / "cover.png")


def test_the_picture_of_a_folder_inside_counts_whatever_it_is(tmp_path, qapp):
    library = tmp_path / "Library"
    _touch(library / "A", "a2.cbz", "a1.cbz")
    _touch(library / "B", "b1.cbz")
    chosen = tmp_path / "mine.png"
    chosen.write_bytes(b"x")
    covers.set_cover_from_file(str(library / "A"), str(chosen))          # the user chose A's cover
    model = _folder_model("manga", library)
    assert os.path.basename(_hero(model)).endswith(".png") and "covers" in _hero(model)


def test_the_tile_updates_when_a_folder_inside_it_becomes_a_series(tmp_path, qapp):
    library = tmp_path / "Library"
    _touch(library / "Dragon", "c1.cbz")
    model = _folder_model("manga", library)
    changed = []
    model.dataChanged.connect(lambda top, bottom, roles: changed.append(list(roles)))
    series.set_series(get_database(), str(library / "Dragon"), True)     # a folder inside, not the tile itself
    assert any(model.Roles.HeroPathRole in roles for roles in changed)


def test_each_tab_only_shows_its_own_kind_of_file(tmp_path, qapp):
    mixed = tmp_path / "Mixed"
    _touch(mixed, "a_clip.mp4", "b_pic.png", "c_book.epub", "d_scan.pdf", "e_comic.cbz")
    assert _hero(_folder_model("photos", mixed)) == str(mixed / "b_pic.png")      # not the earlier video
    assert _hero(_folder_model("videos", mixed)) == str(mixed / "a_clip.mp4")
    assert _hero(_folder_model("manga", mixed)) in (str(mixed / "d_scan.pdf"), str(mixed / "e_comic.cbz"))
    assert _hero(_folder_model("books", mixed)) == str(mixed / "c_book.epub")


def test_the_subfolder_grid_uses_the_same_rule(tmp_path, qapp):
    from tetia.models.mediaModel import MediaModel
    from tetia.models.subfolderModel import SubfolderModel
    parent = tmp_path / "Parent"
    _touch(parent / "Group" / "Title", "Vol.1 Ch.2.cbz", "Vol.1 Ch.1.cbz")     # a series, one level further down
    series.set_series(get_database(), str(parent / "Group" / "Title"), True)
    model = SubfolderModel()
    model.filterMode = int(MediaModel.FilterMode.MangaOnly)
    model.load(str(parent))
    assert model.data(model.index(0), model.Roles.HeroPathRole) == str(parent / "Group" / "Title" / "Vol.1 Ch.1.cbz")


def test_a_loose_pdf_and_epub_give_a_tile_picture(tmp_path, qapp):
    books = tmp_path / "Books"
    _touch(books, "novel.epub")
    assert _hero(_folder_model("books", books)) == str(books / "novel.epub")
    docs = tmp_path / "Docs"
    _touch(docs, "paper.pdf")
    assert _hero(_folder_model("manga", docs)) == str(docs / "paper.pdf")      # PDFs show in the Manga tab too


def test_symlink_loops_do_not_hang_the_picture_lookup(tmp_path, qapp):
    loop = tmp_path / "Loop"
    (loop / "inner").mkdir(parents=True)
    os.symlink(str(loop), str(loop / "inner" / "back"))
    assert covers.hero_path(str(loop), extensions={".cbz"}) == ""
