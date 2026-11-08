# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""A series' format (manga, webtoon...) decides how the reader opens it and filters the shelf; Continue reading
lists what is partway in the Manga and EBooks tabs."""
import os

from tetia.models import covers, reader
from tetia.models.database import get_database
from tetia.models.folderModel import FolderModel
from tetia.models.gridModel import GridModel
from tetia.models.mediaModel import MediaModel
from tetia.models.subfolderModel import SubfolderModel


def _touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


def test_a_format_says_how_a_series_opens():
    assert reader.format_defaults("webtoon") == {"layout": "strip", "direction": "ltr"}
    assert reader.format_defaults("manga") == {"direction": "rtl"}
    assert reader.format_defaults("doujin")["direction"] == "rtl"
    assert reader.format_defaults("manhwa") == {"direction": "ltr"}
    assert reader.format_defaults("") == {}


def test_the_format_is_kept_with_the_folder_and_forgotten_cleanly(tmp_path):
    db = get_database()
    key = str(tmp_path / "Tower")
    db.set_collection_format(key, "webtoon")
    assert db.get_collection_meta(key)["format"] == "webtoon"
    db.set_collection_format(key, None)
    assert db.get_collection_meta(key)["format"] is None
    assert db.conn.execute("SELECT COUNT(*) FROM collection WHERE path = ?", (key,)).fetchone()[0] == 0  # tidied away


def test_the_shelf_filters_series_by_format_and_hides_loose_files(tmp_path, qapp):
    _touch(tmp_path / "Lib" / "Tower", "Ep.1.cbz", "Ep.2.cbz")
    _touch(tmp_path / "Lib" / "Frieren", "Ch.1.cbz", "Ch.2.cbz")
    _touch(tmp_path / "Lib", "Loose.cbz")
    media = MediaModel()
    media.filterMode = MediaModel.FilterMode.MangaOnly
    media.load_from_qurl(str(tmp_path / "Lib"))
    subs = SubfolderModel()
    subs.filterMode = int(MediaModel.FilterMode.MangaOnly)
    subs.load(str(tmp_path / "Lib"))
    for name in ("Tower", "Frieren"):
        subs.setSeries(covers.folder_uri(str(tmp_path / "Lib" / name)), True)
    subs.setFormat(covers.folder_uri(str(tmp_path / "Lib" / "Tower")), "webtoon")
    grid = GridModel()
    grid.subfolders = subs
    grid.media = media
    assert grid.rowCount() == 3                                     # two series and the loose book
    names = lambda: [subs.data(subs.index(r), subs.Roles.NameRole) for r in range(subs.rowCount())]
    tower = names().index("Tower")
    assert subs.data(subs.index(tower), subs.Roles.FormatRole) == "webtoon"
    subs.formatFilter = "webtoon"
    assert names() == ["Tower"] and grid.rowCount() == 1           # only webtoons, no loose files
    subs.formatFilter = ""
    assert grid.rowCount() == 3


def test_continue_reading_lists_what_is_partway_newest_first(tmp_path, qapp):
    _touch(tmp_path / "Manga" / "Frieren", "Ch.1.cbz", "Ch.2.cbz", "Ch.3.cbz")
    _touch(tmp_path / "Manga", "Oneshot.cbz", "Done.cbz")
    _touch(tmp_path / "Elsewhere", "Other.cbz")
    MediaModel().load_from_qurl(str(tmp_path / "Manga" / "Frieren"))
    MediaModel().load_from_qurl(str(tmp_path / "Manga"))
    MediaModel().load_from_qurl(str(tmp_path / "Elsewhere"))
    folders = FolderModel()
    folders.addFolder(covers.folder_uri(str(tmp_path / "Manga")), "manga")
    folders.currentCategory = "manga"
    folders.setSeries(covers.folder_uri(str(tmp_path / "Manga" / "Frieren")), True)
    db = get_database()
    media_id = lambda *parts: db.get_media_by_path(os.path.realpath(str(tmp_path.joinpath(*parts))))[0]

    db.set_progress(media_id("Manga", "Frieren", "Ch.1.cbz"), 19, 0, 20, True)
    db.conn.execute("UPDATE reading_progress SET updated = '2026-01-01 10:00:00'")
    db.set_progress(media_id("Manga", "Oneshot.cbz"), 4, 0, 10, False)
    db.set_progress(media_id("Manga", "Done.cbz"), 9, 0, 10, True)          # read: not listed
    db.set_progress(media_id("Elsewhere", "Other.cbz"), 2, 0, 10, False)    # not in this tab's library
    db.conn.execute("UPDATE reading_progress SET updated = '2026-01-02 10:00:00' WHERE updated > '2026-01-01 10:00:00'")
    db.conn.commit()

    found = folders.continueReading(8)
    assert [(f["kind"], f["name"]) for f in found] == [("book", "Oneshot"), ("series", "Frieren")]
    assert found[0]["where"] == "Page 5 of 10"
    assert found[1]["where"] == "Chapter 2 of 3" and 0 < found[1]["fraction"] < 1
    folders.currentCategory = "photos"
    assert folders.continueReading(8) == []


def test_a_format_chip_finds_its_series_at_any_depth_and_counts_them(tmp_path, qapp):
    lib = tmp_path / "Manga"
    _touch(lib / "Frieren", "Ch.1.cbz")
    _touch(lib / "Doujins" / "Summer", "Summer.cbz", "Summer 2.cbz")
    _touch(lib / "Doujins" / "Circle" / "Winter", "Winter.cbz", "Winter 2.cbz")
    _touch(tmp_path / "Elsewhere" / "Other", "Other.cbz")
    subs = SubfolderModel()
    subs.filterMode = int(MediaModel.FilterMode.MangaOnly)
    for path, fmt in ((lib / "Frieren", "manga"), (lib / "Doujins" / "Summer", "doujin"),
                      (lib / "Doujins" / "Circle" / "Winter", "doujin"), (tmp_path / "Elsewhere" / "Other", "doujin")):
        subs.setSeries(covers.folder_uri(str(path)), True)
        subs.setFormat(covers.folder_uri(str(path)), fmt)
    counts = subs.formatCounts([str(lib)], [])
    assert [(c["key"], c["name"], c["count"]) for c in counts] == [("manga", "Manga", 1), ("doujin", "Doujin", 2)]
    subs.formatFilter = "doujin"
    subs.loadSources([str(lib)], [])
    names = [subs.data(subs.index(r), subs.Roles.NameRole) for r in range(subs.rowCount())]
    assert names == ["Summer", "Winter"]                 # deep in Doujins, and nothing from outside the library folder
    subs.formatFilter = ""
    assert subs.formatCounts([str(tmp_path / "Nothing")], []) == []


def test_the_selection_gets_one_format_but_only_its_series_take_it(tmp_path, qapp):
    _touch(tmp_path / "A", "1.cbz")
    _touch(tmp_path / "B", "1.cbz")
    _touch(tmp_path / "Plain", "1.cbz")
    subs = SubfolderModel()
    for name in ("A", "B"):
        subs.setSeries(covers.folder_uri(str(tmp_path / name)), True)
    told = []
    subs.formatsSet.connect(lambda: told.append(1))
    picked = [covers.folder_uri(str(tmp_path / n)) for n in ("A", "B", "Plain")] + ["virtual:3"]
    assert subs.seriesCount(picked) == 2
    subs.setFormats(picked, "webtoon")
    db = get_database()
    assert [db.get_collection_meta(str(tmp_path / n))["format"] for n in ("A", "B", "Plain")] == ["webtoon", "webtoon", None]
    assert told == [1]
    subs.setFormats(picked, "")
    assert db.get_collection_meta(str(tmp_path / "A"))["format"] is None
