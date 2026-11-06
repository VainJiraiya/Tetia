# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest

from tetia.models import covers
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel
from tetia.models.searchModel import SearchModel
from tetia.models.tagModel import TagModel


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(b"x" * 9)
    return path


@pytest.fixture
def page(tmp_path, qapp):
    """Five pictures in Anime/, tagged: mira on 3, frieren on 2, kantoku on 1, and one tag per category."""
    root = tmp_path / "Anime"
    for name in ("a", "b", "c", "d", "e"):
        touch(str(root / f"{name}.png"))
    db = get_database()
    db.add_folder(covers.folder_uri(str(root)), "photos")
    media = MediaModel()
    media.load_from_qurl(str(root))
    ids = {i["file_name"]: i["media_id"] for i in media._visible_items}
    tags = TagModel()
    for name in ("a.png", "b.png", "c.png"):
        tags.addTag(ids[name], "mira", "character")
    for name in ("a.png", "d.png"):
        tags.addTag(ids[name], "frieren", "series")
    tags.addTag(ids["a.png"], "kantoku", "creator")                 # only one item: left out
    for name in ("b.png", "c.png", "e.png"):
        tags.addTag(ids[name], "sunny", "genre")
    return {"media": media, "tags": tags, "ids": ids, "root": str(root)}


def test_the_tags_of_a_page_with_counts_in_category_order(page):
    groups = page["tags"].browse(page["media"].visibleIds(), [])
    assert [(g["category"], [(t["name"], t["count"]) for t in g["tags"]]) for g in groups] == [
        ("series", [("frieren", 2)]), ("character", [("mira", 3)]), ("genre", [("sunny", 3)])]


def test_a_tag_on_one_item_is_left_out_and_so_is_an_empty_category(page):
    names = [t["name"] for g in page["tags"].browse(page["media"].visibleIds(), []) for t in g["tags"]]
    assert "kantoku" not in names
    assert "creator" not in [g["category"] for g in page["tags"].browse(page["media"].visibleIds(), [])]


def test_only_the_items_of_the_page_count(page):
    ids = page["ids"]
    groups = page["tags"].browse([ids["a.png"], ids["d.png"]], [])             # a page of two items
    assert [(g["category"], [t["name"] for t in g["tags"]]) for g in groups] == [("series", ["frieren"])]
    assert page["tags"].browse([], []) == []


def test_most_used_first_then_by_name(page):
    tags, ids = page["tags"], page["ids"]
    for name in ("a.png", "b.png"):
        tags.addTag(ids[name], "zelda", "character")                      # 2 items, after mira (3)
    for name in ("a.png", "b.png"):
        tags.addTag(ids[name], "ayla", "character")                       # 2 items, before zelda
    groups = tags.browse(page["media"].visibleIds(), [])
    character = next(g for g in groups if g["category"] == "character")
    assert [(t["name"], t["count"]) for t in character["tags"]] == [("mira", 3), ("ayla", 2), ("zelda", 2)]


def test_many_items_do_not_hit_the_variable_limit(page):
    db = get_database()
    counts = db.get_tag_counts(list(page["ids"].values()) * 400)           # 2000 ids: several chunks
    assert {c["name"] for c in counts} >= {"mira", "frieren"}


def test_the_library_folder_that_holds_a_path(page, tmp_path):
    search = SearchModel()
    assert search.rootOf(os.path.join(page["root"], "Deep", "er")) == os.path.realpath(page["root"])
    assert search.rootOf(str(tmp_path / "elsewhere")) == ""
    outer = tmp_path / "Anime"
    get_database().add_folder(covers.folder_uri(str(outer / "Deep")), "photos")      # a nested library folder
    assert search.rootOf(str(outer / "Deep" / "x")) == os.path.realpath(outer)       # the outermost wins


# ---- a removed misspelling does not stay behind ---------------------------------------------------------------

def test_a_tag_removed_from_its_last_item_is_gone(page):
    tags, ids, db = page["tags"], page["ids"], get_database()
    tags.addTag(ids["e.png"], "mira_typo", "character")
    typo = db.get_tag_id("mira_typo")
    assert [s["name"] for s in tags.suggest("mira_t")] == ["mira_typo"]
    tags.removeTag(ids["e.png"], typo)
    assert db.get_tag_id("mira_typo") is None                          # the tag itself went
    assert tags.suggest("mira_t") == []                                 # and is not suggested


def test_a_tag_still_used_by_another_item_stays(page):
    tags, ids, db = page["tags"], page["ids"], get_database()
    mira = db.get_tag_id("mira")
    tags.removeTag(ids["a.png"], mira)                                 # b and c still have it
    assert db.get_tag_id("mira") == mira
    tags.removeTagsFromMedia([ids["b.png"], ids["c.png"]], mira)       # the last two
    assert db.get_tag_id("mira") is None


def test_a_tag_that_is_an_alias_target_or_implied_is_kept(page):
    tags, ids, db = page["tags"], page["ids"], get_database()
    tags.addTag(ids["e.png"], "feline", "genre")
    tags.addTag(ids["e.png"], "cat", "genre")
    feline, cat = db.get_tag_id("feline"), db.get_tag_id("cat")
    db.conn.execute("INSERT INTO tag_alias (alias, tag_id) VALUES ('kitty', ?)", (cat,))
    db.conn.execute("INSERT INTO tag_implication (antecedent_id, consequent_id) VALUES (?, ?)", (cat, feline))
    db.conn.commit()
    tags.removeTag(ids["e.png"], feline)
    tags.removeTag(ids["e.png"], cat)
    assert db.get_tag_id("feline") == feline and db.get_tag_id("cat") == cat      # set up on purpose: kept


def test_leftovers_from_before_are_not_suggested(page):
    db = get_database()
    db.conn.execute("INSERT INTO tag (name, category_id) VALUES ('old_typo', 3)")      # an orphan already in the database
    db.conn.commit()
    assert page["tags"].suggest("old_t") == []
    assert [s["name"] for s in page["tags"].suggest("mir")] == ["mira"]


# ---- the whole tab, and the viewer's tag signal ---------------------------------------------------------------

def test_searching_a_whole_tab_takes_every_folder_added_to_it(page, tmp_path):
    other = tmp_path / "Elsewhere"
    touch(str(other / "z.png"))
    db = get_database()
    db.add_folder(covers.folder_uri(str(other)), "photos")
    db.add_folder(covers.folder_uri(str(tmp_path / "Videos")), "videos")
    touch(str(tmp_path / "Videos" / "v.mp4"))
    media = MediaModel()
    media.load_from_qurl(str(other))
    z = media._visible_items[0]["media_id"]
    page["tags"].addTag(z, "mira", "character")
    search = SearchModel()
    in_folder = search.search("character:mira", page["root"])
    in_tab = search.searchInTab("character:mira", "photos")
    assert len(in_folder) == 3 and z not in in_folder
    assert len(in_tab) == 4 and z in in_tab                               # both library folders of the Photos tab
    assert search.searchInTab("character:mira", "videos") == []           # another tab's folders are not searched
    assert search.searchInTab("character:mira", "manga") == []            # a tab with no folder


def test_the_tag_model_says_when_tags_change(page):
    seen = []
    page["tags"].tagsChanged.connect(lambda: seen.append(1))
    ids = page["ids"]
    page["tags"].addTag(ids["e.png"], "solo", "genre")
    page["tags"].addTagsToMedia([ids["d.png"], ids["e.png"]], "pair", "genre")
    tag = get_database().get_tag_id("solo")
    page["tags"].removeTag(ids["e.png"], tag)
    page["tags"].removeTagsFromMedia([ids["d.png"]], get_database().get_tag_id("pair"))
    assert len(seen) == 4


@pytest.fixture
def manga(tmp_path, qapp):
    """A Manga library folder: Berserk/ (three chapters, a series) and Loose/ (two files, not a series)."""
    root = tmp_path / "Manga"
    for folder, names in (("Berserk", ("ch1", "ch2", "ch3")), ("Loose", ("x", "y"))):
        for name in names:
            touch(str(root / folder / f"{name}.cbz"))
    db = get_database()
    db.add_folder(covers.folder_uri(str(root)), "manga")
    media = MediaModel()
    media.load_from_qurl(str(root / "Berserk"))
    media.load_from_qurl(str(root / "Loose"))
    series = str(root / "Berserk")
    db.set_collection_series(covers.folder_key(series), True)
    return {"root": str(root), "series": series, "loose": str(root / "Loose"), "tags": TagModel()}


def test_only_a_series_folder_takes_tags(manga):
    tags = manga["tags"]
    assert tags.addTagToFolders([manga["loose"]], "dark", "genre") is True      # accepted, but nothing is stored
    assert tags.tagsForFolder(manga["loose"]) == []
    assert tags.addTagToFolders([manga["series"]], "dark", "genre") is True
    assert [t["name"] for t in tags.tagsForFolder(manga["series"])] == ["dark"]


def test_a_search_finds_a_series_once_not_its_chapters(manga):
    manga["tags"].addTagToFolders([manga["series"]], "dark", "genre")
    hits = SearchModel().searchHits("genre:dark", "", "manga")
    assert hits["ids"] == [] and hits["series"] == [os.path.realpath(manga["series"])]
    assert SearchModel().searchHits("genre:dark", manga["root"], "")["series"] == hits["series"]    # by folder too


def test_files_outside_a_series_are_still_listed_one_by_one(manga):
    db = get_database()
    rows = db.conn.execute("SELECT id FROM media WHERE path LIKE ?", (manga["loose"] + "/%",)).fetchall()
    for (media_id,) in rows:
        manga["tags"].addTag(media_id, "dark", "genre")
    hits = SearchModel().searchHits("genre:dark", "", "manga")
    assert len(hits["ids"]) == 2 and hits["series"] == []


def test_taking_the_series_away_forgets_its_tags(manga):
    from tetia.models import series
    manga["tags"].addTagToFolders([manga["series"]], "dark", "genre")
    series.set_series(get_database(), manga["series"], False)
    assert manga["tags"].tagsForFolder(manga["series"]) == []
    assert get_database().get_tag_id("dark") is None                  # nothing uses it any more


def test_a_search_page_can_show_series_as_tiles(manga, qapp):
    from tetia.models.subfolderModel import SubfolderModel
    model = SubfolderModel()
    model.loadSeries([manga["series"]])
    assert model.rowCount() == 1 and model.data(model.index(0, 0), model.Roles.IsSeriesRole) is True
    assert model.folderKeys() == [covers.folder_uri(manga["series"])]


def test_a_one_file_folder_gives_the_media_id_of_its_file(manga, qapp):
    from tetia.models.subfolderModel import SubfolderModel
    from tetia.models.mediaModel import MediaModel as M
    one = os.path.join(manga["root"], "Solo")
    touch(os.path.join(one, "only.cbz"))
    media = M()
    media.load_from_qurl(one)
    model = SubfolderModel()
    model.filterMode = M.FilterMode.MangaOnly
    model.load(manga["root"])
    names = [model.data(model.index(r, 0), model.Roles.NameRole) for r in range(model.rowCount())]
    row = names.index("Solo")
    expected = get_database().get_media_by_path(os.path.realpath(os.path.join(one, "only.cbz")))[0]
    assert model.data(model.index(row, 0), model.Roles.SingleFileIdRole) == expected
    assert model.data(model.index(names.index("Berserk"), 0), model.Roles.SingleFileIdRole) == -1


def test_a_tag_on_a_single_series_is_listed(manga):
    manga["tags"].addTagToFolders([manga["series"]], "dark", "genre")
    groups = manga["tags"].browse([], [covers.folder_uri(manga["series"])])
    assert [(g["category"], [(t["name"], t["count"]) for t in g["tags"]]) for g in groups] == [("genre", [("dark", 1)])]


def test_a_series_takes_a_rating_and_a_favorite(manga, qapp):
    from tetia.models.subfolderModel import SubfolderModel
    model = SubfolderModel()
    assert model.folderRating(manga["series"]) == -1 and model.folderFavorite(manga["series"]) is False
    model.setRating(manga["series"], 2)
    model.setFavorite(manga["series"], True)
    assert model.folderRating(manga["series"]) == 2 and model.folderFavorite(manga["series"]) is True
    assert get_database().get_favorite_collections()[0]["path"] == covers.folder_key(manga["series"])
    model.setRating(manga["series"], -1)
    assert model.folderRating(manga["series"]) == -1


def test_hidden_files_are_not_media(tmp_path, qapp):
    folder = tmp_path / "Videos"
    touch(str(folder / "Show 01.mp4"))
    touch(str(folder / "._Show 01.mp4"))                 # a macOS resource-fork stub
    media = MediaModel()
    media.load_from_qurl(str(folder))
    assert [i["file_name"] for i in media._visible_items] == ["Show 01.mp4"]
