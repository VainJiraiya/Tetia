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
                                           "is_series": False, "last_read": None, "rating": None, "description": None}


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


# ---- a folder holding one file shows as that file --------------------------------------------------------

MANGA = {".cbz", ".pdf"}


def test_single_file_rule(tmp_path):
    folder = tmp_path / "Title"
    _touch(folder, "vol1.cbz")
    assert series.single_file(str(folder), MANGA) == str(folder / "vol1.cbz")
    _touch(folder, "notes.txt", "cover.jpg", ".hidden.cbz", "subs.srt")        # not counted
    assert series.single_file(str(folder), MANGA) == str(folder / "vol1.cbz")
    _touch(folder, "vol2.cbz")                                                   # a second one
    assert series.single_file(str(folder), MANGA) == ""
    (folder / "vol2.cbz").unlink()
    (folder / "extras").mkdir()                                                  # any subfolder
    assert series.single_file(str(folder), MANGA) == ""
    assert series.single_file(str(tmp_path / "empty"), MANGA) == ""
    assert series.single_file(str(tmp_path / "missing"), MANGA) == ""


def test_the_collections_grid_flattens_one_file_folders(tmp_path, qapp):
    root = tmp_path
    _touch(root / "One", "only.cbz", "readme.txt")
    _touch(root / "Two", "a.cbz", "b.cbz")
    model = _folder_model("manga", root / "One", root / "Two")
    rows = {os.path.basename(model.getFolderPath(i).rstrip("/")): i for i in range(model.rowCount())}
    assert model.data(model.index(rows["One"]), model.Roles.SingleFileRole) == str(root / "One" / "only.cbz")
    assert model.data(model.index(rows["Two"]), model.Roles.SingleFileRole) == ""
    uri = model.openSingleFile(covers.folder_uri(str(root / "One")))
    assert uri.endswith("/One/only.cbz") and uri.startswith("file://")
    assert model.openSingleFile(covers.folder_uri(str(root / "Two"))) == ""


def test_one_file_folders_follow_the_tab_and_exclude_photos(tmp_path, qapp):
    pic = tmp_path / "Pic"
    _touch(pic, "photo.png")
    photos = _folder_model("photos", pic)
    assert photos.data(photos.index(0), photos.Roles.SingleFileRole) == ""        # photos are not flattened
    clip = tmp_path / "Clip"
    _touch(clip, "movie.mkv")
    videos = _folder_model("videos", clip)
    assert videos.data(videos.index(0), videos.Roles.SingleFileRole) == str(clip / "movie.mkv")
    book = tmp_path / "Book"
    _touch(book, "novel.epub")
    books = _folder_model("books", book)
    assert books.data(books.index(0), books.Roles.SingleFileRole) == str(book / "novel.epub")
    # a video folder filed under Manga has nothing the Manga tab lists
    wrong = _folder_model("manga", clip)
    assert wrong.data(wrong.index(0), wrong.Roles.SingleFileRole) == ""


def test_a_series_is_not_also_flattened_and_a_new_file_unflattens(tmp_path, qapp):
    folder = tmp_path / "Title"
    _touch(folder, "ch1.cbz")
    model = _folder_model("manga", folder)
    assert model.data(model.index(0), model.Roles.SingleFileRole) != ""
    series.set_series(get_database(), str(folder), True)
    assert model.data(model.index(0), model.Roles.SingleFileRole) == ""           # the series path handles it
    series.set_series(get_database(), str(folder), False)
    _touch(folder, "ch2.cbz")
    assert model.data(model.index(0), model.Roles.SingleFileRole) == ""           # now an ordinary folder


def test_the_subfolder_grid_flattens_too(tmp_path, qapp):
    from tetia.models.mediaModel import MediaModel
    from tetia.models.subfolderModel import SubfolderModel
    parent = tmp_path / "Parent"
    _touch(parent / "Solo", "only.cbz")
    _touch(parent / "Pair", "a.cbz", "b.cbz")
    model = SubfolderModel()
    model.filterMode = int(MediaModel.FilterMode.MangaOnly)
    model.load(str(parent))
    by_name = {model.data(model.index(i), model.Roles.NameRole): i for i in range(model.rowCount())}
    assert model.data(model.index(by_name["Solo"]), model.Roles.SingleFileRole) == str(parent / "Solo" / "only.cbz")
    assert model.data(model.index(by_name["Pair"]), model.Roles.SingleFileRole) == ""
    assert model.openSingleFile(covers.folder_uri(str(parent / "Solo"))).endswith("/Solo/only.cbz")
    model.filterMode = int(MediaModel.FilterMode.ImagesOnly)                       # photos: never
    assert model.openSingleFile(covers.folder_uri(str(parent / "Solo"))) == ""


# ---- the Favorites tab: one click for a series or a one-file folder -----------------------------------------

def _favorites_collections(tmp_path, *folders):
    from tetia.models.favoritesModel import FavoritesModel
    db = get_database()
    db.add_folder(covers.folder_uri(str(tmp_path)), "manga")        # the library root holding them
    for folder in folders:
        db.set_collection_favorite(covers.folder_key(str(folder)), True)
    model = FavoritesModel()
    tiles = [t for row in model.layoutRows(8) if row["type"] == "tiles" and row["kind"] == "collection"
             for t in row["items"]]
    return model, {t["fileName"]: t for t in tiles}


def test_a_favorited_one_file_folder_opens_its_file_in_one_click(tmp_path, qapp):
    _touch(tmp_path / "Solo", "only.cbz", "readme.txt")
    _touch(tmp_path / "Pair", "a.cbz", "b.cbz")
    _touch(tmp_path / "Clip", "movie.mkv")
    _touch(tmp_path / "Photo", "pic.png")
    model, tiles = _favorites_collections(tmp_path, tmp_path / "Solo", tmp_path / "Pair",
                                          tmp_path / "Clip", tmp_path / "Photo")
    assert model.openCollection(tiles["Solo"]["folderUri"]).endswith("/Solo/only.cbz")
    assert model.openCollection(tiles["Clip"]["folderUri"]).endswith("/Clip/movie.mkv")
    assert model.openCollection(tiles["Pair"]["folderUri"]) == ""             # a real folder: browse it
    assert model.openCollection(tiles["Photo"]["folderUri"]) == ""            # photos open in the viewer
    assert tiles["Solo"]["opensFile"] and tiles["Clip"]["opensFile"]
    assert not tiles["Pair"]["opensFile"] and not tiles["Photo"]["opensFile"]


def test_a_favorited_series_opens_the_chapter_to_resume(tmp_path, qapp):
    _touch(tmp_path / "Dragon", "Vol.1 Ch.1.cbz", "Vol.1 Ch.2.cbz", "Vol.1 Ch.3.cbz")
    series.set_series(get_database(), str(tmp_path / "Dragon"), True)
    model, tiles = _favorites_collections(tmp_path, tmp_path / "Dragon")
    assert tiles["Dragon"]["opensFile"]
    assert model.openCollection(tiles["Dragon"]["folderUri"]).endswith("Ch.1.cbz")       # nothing read yet
    series.open_series(get_database(), str(tmp_path / "Dragon"), "next")                   # chapter 2 was opened
    assert model.openCollection(tiles["Dragon"]["folderUri"]).endswith("Ch.2.cbz")        # resumes there


def test_a_series_without_chapters_falls_back_to_the_folder(tmp_path, qapp):
    (tmp_path / "Empty").mkdir()
    series.set_series(get_database(), str(tmp_path / "Empty"), True)
    model, tiles = _favorites_collections(tmp_path, tmp_path / "Empty")
    assert model.openCollection(tiles["Empty"]["folderUri"]) == "" and not tiles["Empty"]["opensFile"]


def test_a_folder_of_videos_lists_its_episodes_in_order(tmp_path):
    for name in ("Show S01E10.mkv", "Show S01E02.mkv", "Show S01E01.mkv", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert [os.path.basename(p) for p in series.chapters(str(tmp_path))] == [
        "Show S01E01.mkv", "Show S01E02.mkv", "Show S01E10.mkv"]


def test_episode_names_are_read_in_every_common_style():
    from tetia.models import episodes as ep
    assert ep.parse_episode("Show S01E02 - Guts.mkv") == (1, 2)
    assert ep.parse_episode("show.s1e5.720p.mkv") == (1, 5)
    assert ep.parse_episode("Show Season 2 Episode 10.mp4") == (2, 10)
    assert ep.parse_episode("Show 1x07.avi") == (1, 7)
    assert ep.parse_episode("Show - Ep 12 [1080p].mkv") == (None, 12)
    assert ep.parse_episode("Dragon Ball 001 - Secret.mkv") == (None, 1)
    assert ep.parse_episode("[Group] Naruto - 045 [1080p][ABCD1234].mkv") == (None, 45)
    assert ep.parse_episode("Movie (2012) 1080p x264.mkv") == (None, None)
    assert ep.parse_season_folder("Season 1") == 1 and ep.parse_season_folder("S03") == 3
    assert ep.parse_season_folder("Specials") == 0 and ep.parse_season_folder("Extras") == 0
    assert ep.parse_season_folder("Dragon") is None
    assert ep.episode_title("Show S01E02 - Guts.mkv", 2, "Show") == "Guts"
    assert ep.episode_title("Show 1x07.avi", 7, "Show") == "Episode 7"


def test_a_show_with_season_folders_lists_seasons_in_order(tmp_path):
    from tetia.models import episodes as ep
    for folder, names in (("Season 10", ["Show S10E01.mkv"]), ("Season 2", ["Show S02E02.mkv", "Show S02E01.mkv"]),
                          ("Season 1", ["Show S01E01.mkv"]), ("Specials", ["Making of.mkv"])):
        (tmp_path / folder).mkdir()
        for n in names:
            (tmp_path / folder / n).write_bytes(b"x")
    groups = ep.seasons(str(tmp_path))
    assert [g["name"] for g in groups] == ["Specials", "Season 1", "Season 2", "Season 10"]
    assert [e["number"] for e in groups[2]["episodes"]] == [1, 2]
    assert [os.path.basename(p) for p in ep.episode_paths(str(tmp_path))][1:4] == [
        "Show S01E01.mkv", "Show S02E01.mkv", "Show S02E02.mkv"]
    assert len(series.chapters(str(tmp_path))) == 5                # the series tile counts every episode


def test_one_folder_of_hundreds_of_episodes_goes_by_number(tmp_path):
    from tetia.models import episodes as ep
    for n in (100, 2, 10, 1, 99):
        (tmp_path / ("Dragon Ball %03d.mkv" % n)).write_bytes(b"x")
    (group,) = ep.seasons(str(tmp_path))
    assert [e["number"] for e in group["episodes"]] == [1, 2, 10, 99, 100] and group["name"] == "Episodes"


def test_loose_episodes_are_grouped_by_their_season(tmp_path):
    from tetia.models import episodes as ep
    for n in ("Show S02E01.mkv", "Show S01E02.mkv", "Show S01E01.mkv"):
        (tmp_path / n).write_bytes(b"x")
    groups = ep.seasons(str(tmp_path))
    assert [(g["name"], len(g["episodes"])) for g in groups] == [("Season 1", 2), ("Season 2", 1)]


def test_a_series_of_videos_is_a_show_and_one_of_chapters_is_not(tmp_path):
    show, manga = tmp_path / "Show", tmp_path / "Manga"
    (show / "Season 1").mkdir(parents=True)
    manga.mkdir()
    (show / "Season 1" / "Show S01E01.mkv").write_bytes(b"x")
    (manga / "Vol.1 Ch.1.cbz").write_bytes(b"x")
    assert series.is_show(str(show)) is True
    assert series.is_show(str(manga)) is False
    assert series.is_show(str(tmp_path / "nothing")) is False


def test_titles_lose_the_release_junk_and_the_show_name():
    from tetia.models import episodes as ep
    name = "Rick.and.Morty.S03E01.The.Rickshank.Rickdemption.1080p.Amazon.WEB-DL.x264-Rapta.mkv"
    show = ep.show_name("Rick and Morty - Season 3 (2017) [1080p]")
    assert show == "Rick and Morty"
    assert ep.episode_title(name, 1, show) == "The Rickshank Rickdemption"
    assert ep.show_name("The Walking Dead") == "The Walking Dead"
    assert ep.show_name("Show.Name.S02.1080p") == "Show Name"
    # a real title with a dash in it is left alone, and so is a name that does not look like a release
    assert ep.episode_title("Show S01E04 - Spider-Man.mkv", 4, "Show") == "Spider-Man"
    assert ep.episode_title("Show S01E04 - Amazon Women.mkv", 4, "Show") == "Amazon Women"
