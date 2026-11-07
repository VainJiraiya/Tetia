# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Boards: a saved search plus what was put on or taken off by hand; nothing moves."""
import os

from PySide6.QtGui import QColor, QImage

from tetia.models import boards, covers
from tetia.models.boardService import BoardService
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel
from tetia.models.searchModel import _Resolver


def _library(tmp_path):
    folder = tmp_path / "Art"
    folder.mkdir()
    for name in ("a.png", "b.png", "c.png", "d.png"):
        image = QImage(4, 4, QImage.Format_RGB32)
        image.fill(QColor("red"))
        image.save(str(folder / name))
    db = get_database()
    db.add_folder(covers.folder_uri(str(folder)), "photos")
    MediaModel().load_from_qurl(str(folder))
    ids = {name: db.get_media_by_path(os.path.realpath(str(folder / name)))[0] for name in ("a.png", "b.png", "c.png", "d.png")}
    tag = db.get_or_create_tag("raphtalia", "character")
    db.insert_media_tags([ids["a.png"], ids["c.png"]], tag)
    return db, ids


def test_a_board_holds_what_its_search_finds_and_follows_new_tags(tmp_path):
    db, ids = _library(tmp_path)
    board = boards.create(db, "Raphtalia", "character:raphtalia", "photos")
    assert boards.members(db, _Resolver(db), board) == [ids["a.png"], ids["c.png"]]
    db.insert_media_tags([ids["d.png"]], db.get_or_create_tag("raphtalia", "character"))    # tagged later
    assert ids["d.png"] in boards.members(db, _Resolver(db), board)


def test_files_put_on_or_taken_off_by_hand(tmp_path):
    db, ids = _library(tmp_path)
    board = boards.create(db, "Best", "character:raphtalia", "photos")
    boards.pin(db, board, [ids["b.png"]], added=True)
    boards.pin(db, board, [ids["a.png"]], added=False)
    assert boards.members(db, _Resolver(db), board) == [ids["b.png"], ids["c.png"]]
    boards.unpin(db, board, [ids["a.png"]])                               # the search decides again
    assert ids["a.png"] in boards.members(db, _Resolver(db), board)
    empty = boards.create(db, "Hand picked", "", "photos")                # no search: only what was put on it
    boards.pin(db, empty, [ids["d.png"]])
    assert boards.members(db, _Resolver(db), empty) == [ids["d.png"]]


def test_a_board_only_looks_in_its_tab(tmp_path):
    db, ids = _library(tmp_path)
    elsewhere = boards.create(db, "Videos board", "character:raphtalia", "videos")
    assert boards.members(db, _Resolver(db), elsewhere) == []
    everywhere = boards.create(db, "Everything", "character:raphtalia", "")
    assert len(boards.members(db, _Resolver(db), everywhere)) == 2


def test_the_cover_prefers_the_chosen_picture_then_the_mildest(tmp_path):
    db, ids = _library(tmp_path)
    board = boards.create(db, "All", "", "photos")
    boards.pin(db, board, list(ids.values()))
    db.set_media_rating(ids["a.png"], 3)       # explicit
    db.set_media_rating(ids["b.png"], 0)       # general
    db.set_media_rating(ids["c.png"], 1)       # suggestive; d stays unrated
    members = boards.members(db, _Resolver(db), board)
    names = lambda paths: [os.path.basename(p) for p in paths]
    assert names(boards.collage(db, board, members)) == ["b.png", "d.png", "c.png"]
    boards.update(db, board, cover_media_id=ids["a.png"])                 # chosen by hand: it comes first
    assert names(boards.collage(db, board, members))[0] == "a.png"


def test_deleting_a_board_touches_no_file(tmp_path):
    db, ids = _library(tmp_path)
    board = boards.create(db, "Gone soon", "character:raphtalia", "photos")
    boards.pin(db, board, [ids["b.png"]])
    boards.delete(db, board)
    assert boards.get(db, board) is None
    assert db.conn.execute("SELECT COUNT(*) FROM board_pin").fetchone()[0] == 0
    assert all(os.path.exists(tmp_path / "Art" / n) for n in ids)


def test_the_service_lists_boards_and_says_when_one_changed(tmp_path, qapp):
    db, ids = _library(tmp_path)
    service = BoardService()
    changed = []
    service.changed.connect(changed.append)
    board = service.create("Raphtalia", "character:raphtalia", "photos")
    listed = service.boards("photos")
    assert [(b["name"], b["count"]) for b in listed] == [("Raphtalia", 2)] and len(listed[0]["collage"]) == 2
    service.rename(board, "Raph")
    service.addMedia(board, [ids["b.png"]])
    assert service.info(board)["name"] == "Raph" and service.info(board)["count"] == 3
    service.remove(board)
    assert service.boards("photos") == [] and changed == [board] * 4
