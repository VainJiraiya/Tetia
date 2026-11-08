# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Home: Continue (books and long videos partway), Pinned, Favorites and Recently added."""
import os

from PySide6.QtGui import QColor, QImage

from tetia.models import boards, covers, home
from tetia.models.database import get_database
from tetia.models.homeModel import HomeModel
from tetia.models.mediaModel import MediaModel
from tetia.models.searchModel import _Resolver


def _touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


def _id(db, path):
    return db.get_media_by_path(os.path.realpath(str(path)))[0]


def test_continue_mixes_books_and_long_videos_newest_first_and_skips_clips(tmp_path):
    _touch(tmp_path / "Manga" / "Frieren", "Ch.1.cbz", "Ch.2.cbz")
    _touch(tmp_path / "Videos", "Movie.mkv", "Clip.mp4")
    _touch(tmp_path / "Videos" / "Starfall", "S01E01.mkv", "S01E02.mkv")
    for folder in ("Manga/Frieren", "Videos", "Videos/Starfall"):
        MediaModel().load_from_qurl(str(tmp_path / folder))
    db = get_database()
    db.add_folder(covers.folder_uri(str(tmp_path / "Manga")), "manga")
    db.add_folder(covers.folder_uri(str(tmp_path / "Videos")), "videos")
    db.set_collection_series(str(tmp_path / "Manga" / "Frieren"), True)
    db.set_collection_series(str(tmp_path / "Videos" / "Starfall"), True)
    db.set_progress(_id(db, tmp_path / "Manga" / "Frieren" / "Ch.1.cbz"), 9, 0, 10, True)
    db.set_playback(_id(db, tmp_path / "Videos" / "Movie.mkv"), 1200, 6000, False)
    db.set_playback(_id(db, tmp_path / "Videos" / "Clip.mp4"), 30, 120, False)          # a clip: never resumed
    db.set_playback(_id(db, tmp_path / "Videos" / "Starfall" / "S01E02.mkv"), 600, 2700, False)
    db.conn.execute("UPDATE reading_progress SET updated = '2026-01-01 00:00:03'")
    db.conn.execute("UPDATE playback SET updated = '2026-01-01 00:00:0' || media_id % 3")
    db.conn.commit()
    items = home.continue_items(db)
    kinds = {i["name"]: i["kind"] for i in items}
    assert kinds == {"Frieren": "series", "Movie": "video", "Starfall": "show"}
    assert items[0]["name"] == "Frieren"                                      # the most recent
    movie = next(i for i in items if i["name"] == "Movie")
    assert movie["where"] == "1 h 20 min left" and 0 < movie["fraction"] < 1


def test_pinned_is_for_boards(tmp_path, qapp):
    folder = tmp_path / "Art"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        image = QImage(4, 4, QImage.Format_RGB32)
        image.fill(QColor("blue"))
        image.save(str(folder / name))
    _touch(tmp_path / "Frieren", "Ch.1.cbz")
    db = get_database()
    db.add_folder(covers.folder_uri(str(folder)), "photos")
    MediaModel().load_from_qurl(str(folder))
    db.insert_media_tags([_id(db, folder / "a.png")], db.get_or_create_tag("frieren", "character"))
    db.set_collection_series(str(tmp_path / "Frieren"), True)
    board = boards.create(db, "Frieren art", "character:frieren", "photos")

    model = HomeModel()
    changed = []
    model.pinsChanged.connect(lambda: changed.append(1))
    model.setPinned("board", str(board), True)
    model.setPinned("folder", covers.folder_uri(str(tmp_path / "Frieren")), True)
    model.setPinned("tag", "frieren", True)
    model.setPinned("board", str(board), True)                                  # twice: still one pin
    pinned = model.pinned()
    # folders, series and tags reach Home through the favorites, not the pins (an old pin of one is not shown)
    assert [(p["kind"], p["name"]) for p in pinned] == [("board", "Frieren art")]
    assert pinned[0]["sub"] == "Board · 1" and len(changed) == 4
    boards.delete(db, board)                                                    # a pin of a deleted board goes
    assert model.pinned() == []


def test_favorites_and_recently_added_are_pictures_in_their_shape(tmp_path):
    folder = tmp_path / "Pics"
    folder.mkdir()
    for name, (w, h) in (("wide.png", (80, 40)), ("tall.png", (30, 60))):
        image = QImage(w, h, QImage.Format_RGB32)
        image.fill(QColor("green"))
        image.save(str(folder / name))
    MediaModel().load_from_qurl(str(folder))
    db = get_database()
    db.add_folder(covers.folder_uri(str(folder)), "photos")
    db.conn.execute("UPDATE media SET added_at = 100 WHERE name = 'wide.png'")
    db.conn.execute("UPDATE media SET added_at = 200, favorite = 1 WHERE name = 'tall.png'")
    db.conn.commit()
    assert [(f["name"], f["aspect"]) for f in home.recent_files(db)] == [("tall.png", 0.5), ("wide.png", 2.0)]
    assert [f["name"] for f in home.favorite_files(db)] == ["tall.png"]
    assert [f["favorite"] for f in home.recent_files(db)] == [True, False]      # the tile's star shows it


def test_the_star_on_a_home_picture_favorites_it(tmp_path, qapp):
    folder = tmp_path / "Pics"
    folder.mkdir()
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor("green"))
    image.save(str(folder / "a.png"))
    db = get_database()
    db.add_folder(covers.folder_uri(str(folder)), "photos")
    MediaModel().load_from_qurl(str(folder))
    a = _id(db, folder / "a.png")
    model = HomeModel()
    changed = []
    model.pinsChanged.connect(lambda: changed.append(1))
    model.setFileFavorite(a, True)
    assert [f["id"] for f in model.favorites()] == [a] and model.recent()[0]["favorite"] and changed
    model.setFileFavorite(a, False)
    assert model.favorites() == [] and not model.recent()[0]["favorite"]


def test_an_episode_in_a_season_folder_continues_its_series(tmp_path):
    _touch(tmp_path / "Starfall" / "Season 1", "S01E01.mkv", "S01E02.mkv")
    MediaModel().load_from_qurl(str(tmp_path / "Starfall" / "Season 1"))
    db = get_database()
    db.add_folder(covers.folder_uri(str(tmp_path / "Starfall")), "videos")
    db.set_collection_series(str(tmp_path / "Starfall"), True)
    db.set_playback(_id(db, tmp_path / "Starfall" / "Season 1" / "S01E02.mkv"), 600, 2700, False)
    items = home.continue_items(db)
    assert [(i["kind"], i["name"]) for i in items] == [("show", "Starfall")]
    assert items[0]["where"].startswith("S01E02 · ")


def test_the_library_cards_count_each_tab(tmp_path):
    folder = tmp_path / "Art"
    folder.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        image = QImage(4, 4, QImage.Format_RGB32)
        image.fill(QColor("red"))
        image.save(str(folder / name))
    db = get_database()
    db.add_folder(covers.folder_uri(str(folder)), "photos")
    MediaModel().load_from_qurl(str(folder))
    db.set_media_rating(_id(db, folder / "a.png"), 3)
    cards = home.library_summary(db)
    assert [(c["tab"], c["sub"]) for c in cards] == [("photos", "3 images")]
    assert len(cards[0]["collage"]) == 3 and not cards[0]["collage"][0].endswith("a.png")   # the explicit one last


def test_a_removed_library_folder_leaves_boards_and_home(tmp_path):
    folder = tmp_path / "Art"
    folder.mkdir()
    image = QImage(4, 4, QImage.Format_RGB32)
    image.fill(QColor("red"))
    image.save(str(folder / "a.png"))
    db = get_database()
    db.add_folder(covers.folder_uri(str(folder)), "photos")
    MediaModel().load_from_qurl(str(folder))
    a = _id(db, folder / "a.png")
    board = boards.create(db, "Picked", "", "photos")
    boards.pin(db, board, [a])                                   # put on the board by hand
    db.conn.execute("UPDATE media SET favorite = 1")
    db.conn.commit()
    assert boards.members(db, _Resolver(db), board) == [a] and home.recent_files(db) and home.favorite_files(db)
    db.remove_folder(covers.folder_uri(str(folder)))
    assert boards.members(db, _Resolver(db), board) == []        # its files left the board; the board stays
    assert boards.get(db, board) is not None
    assert home.recent_files(db) == [] and home.favorite_files(db) == []
    db.add_folder(covers.folder_uri(str(folder)), "photos")      # added again: they come back
    assert boards.members(db, _Resolver(db), board) == [a]
