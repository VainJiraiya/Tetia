# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest

from tetia.models import covers
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel
from tetia.models.purgeSession import PurgeSession


def add(tmp_path, name, kind="image", favorite=False):
    path = tmp_path / name
    path.write_bytes(b"x")
    db = get_database()
    info = os.stat(path)
    media_id = db.upsert_media(str(path), name, kind, info.st_size, int(info.st_mtime), "h" + name)[0]
    if favorite:
        db.set_media_favorite(media_id, True)
    db.conn.commit()
    return media_id


@pytest.fixture
def deck(tmp_path, qapp):
    """A session on four pictures: a, b, c, d."""
    ids = [add(tmp_path, f"{n}.png") for n in "abcd"]
    session = PurgeSession()
    assert session.start(ids)
    return session, ids


def names(session):
    return [session._items[i]["name"] for i in session._waiting()]


# ---- starting ---------------------------------------------------------------------------

def test_start_keeps_the_order_and_ignores_what_is_unusable(tmp_path, qapp):
    ids = [add(tmp_path, "one.png"), add(tmp_path, "two.png")]
    session = PurgeSession()
    assert session.start([ids[1], 99999, "junk", ids[0], ids[1], None])
    assert names(session) == ["two.png", "one.png"]                    # given order, no duplicates
    assert session.total == 2 and session.pending == 2
    assert not session.start([])
    assert not session.start([99999])
    assert session.currentId == -1 and session.currentUri == ""


def test_the_first_image_is_on_top_and_nothing_is_decided(deck):
    session, ids = deck
    assert session.currentId == ids[0] and session.currentName == "a.png"
    assert session.total == 4 and session.pending == 4
    assert session.trashCount == session.keepCount == 0
    assert not session.canUndo and not session.canGoBack and session.canGoForward and not session.hasProgress


def test_the_address_is_fully_encoded_and_favorites_are_flagged(tmp_path, qapp):
    odd = add(tmp_path, "a #1 {x} 50%.png", favorite=True)
    plain = add(tmp_path, "plain.png")
    session = PurgeSession()
    session.start([odd, plain])
    assert session.currentFavorite is True
    assert session.currentUri == covers.folder_uri(str(tmp_path / "a #1 {x} 50%.png")) or "%23" in session.currentUri
    assert "#" not in session.currentUri and "{" not in session.currentUri and session.currentUri.startswith("file://")
    session.decide("keep")
    assert session.currentFavorite is False


# ---- deciding -------------------------------------------------------------------------------

def test_deciding_sends_the_image_off_and_brings_up_the_next(deck):
    session, ids = deck
    session.decide("trash")
    assert session.currentId == ids[1] and session.pending == 3 and session.trashCount == 1
    session.decide("keep")
    assert session.currentId == ids[2] and session.keepCount == 1 and session.hasProgress
    assert session.nextUri.endswith("d.png")
    session.decide("trash")
    session.decide("keep")
    assert session.pending == 0 and session.currentId == -1 and session.nextUri == ""
    assert session.trashCount == 2 and session.keepCount == 2
    session.decide("trash")                                           # nothing left: no effect
    assert session.trashCount == 2


def test_an_unknown_decision_is_ignored(deck):
    session, ids = deck
    session.decide("delete")
    session.decide("")
    assert session.pending == 4 and session.currentId == ids[0]


def test_browsing_moves_among_the_waiting_images_without_deciding(deck):
    session, ids = deck
    session.goForward()
    session.goForward()
    assert session.currentId == ids[2] and session.pending == 4 and session.canGoBack
    session.goForward()
    session.goForward()                                               # stops at the last
    assert session.currentId == ids[3] and not session.canGoForward
    session.goBack()
    assert session.currentId == ids[2]
    for _ in range(5):
        session.goBack()
    assert session.currentId == ids[0] and not session.canGoBack


def test_deciding_after_browsing_continues_from_that_place(deck):
    session, ids = deck
    session.goForward()                                               # b is on top
    session.decide("trash")                                           # b goes; c comes up (a still waits behind)
    assert session.currentId == ids[2] and names(session) == ["a.png", "c.png", "d.png"]
    session.goForward()                                               # d, the last one
    session.decide("keep")
    assert session.currentId == ids[2]                                # nothing after d: back to c
    session.goBack()
    assert session.currentId == ids[0]                                # and a still waits at the front


# ---- undo ------------------------------------------------------------------------------------------

def test_undo_brings_back_the_last_image_decided(deck):
    session, ids = deck
    session.decide("trash")
    session.decide("keep")
    session.undo()
    assert session.currentId == ids[1] and session.keepCount == 0 and session.trashCount == 1
    session.undo()
    assert session.currentId == ids[0] and session.trashCount == 0 and not session.canUndo and not session.hasProgress
    session.undo()                                                    # nothing to undo
    assert session.currentId == ids[0]


def test_undo_after_browsing_returns_to_the_image_itself(deck):
    session, ids = deck
    session.goForward()
    session.goForward()                                               # c on top
    session.decide("trash")                                           # c goes, d is on top
    session.goBack()                                                  # b on top
    session.undo()
    assert session.currentId == ids[2]                                # c is back on top, not b


def test_undo_works_after_the_last_image_is_decided(deck):
    session, ids = deck
    for _ in range(4):
        session.decide("keep")
    assert session.currentId == -1
    session.undo()
    assert session.currentId == ids[3] and session.pending == 1


# ---- the review --------------------------------------------------------------------------------------

def test_the_review_lists_the_trash_in_shown_order_and_keepinstead_removes_one(deck):
    session, ids = deck
    session.decide("trash")
    session.decide("keep")
    session.decide("trash")
    session.decide("trash")
    assert [i["name"] for i in session.trashItems()] == ["a.png", "c.png", "d.png"]
    assert set(session.trashItems()[0]) == {"id", "uri", "name", "favorite"}
    session.keepInstead(ids[2])
    assert [i["name"] for i in session.trashItems()] == ["a.png", "d.png"]
    assert session.trashCount == 2 and session.keepCount == 2
    session.keepInstead(ids[1])                                       # already kept: no change
    session.keepInstead(99999)
    assert session.keepCount == 2


def test_review_now_works_with_images_still_waiting(deck):
    session, ids = deck
    session.decide("trash")
    assert session.pending == 3 and [i["name"] for i in session.trashItems()] == ["a.png"]


def test_forget_drops_images_that_were_trashed(deck):
    session, ids = deck
    session.decide("trash")
    session.decide("trash")
    session.decide("keep")
    session.forget([ids[0], ids[1], "junk"])
    assert session.trashCount == 0 and session.total == 2 and session.keepCount == 1
    assert session.currentId == ids[3]
    session.undo()                                                    # the history of the forgotten ones is gone
    assert session.currentId == ids[2] and session.keepCount == 0
    session.undo()
    assert session.currentId == ids[2]
    session.forget([ids[2], ids[3]])
    assert session.total == 0 and session.currentId == -1


def test_the_changed_signal_fires_for_every_change(deck):
    session, ids = deck
    seen = []
    session.changed.connect(lambda: seen.append(1))
    session.decide("keep"); session.goForward(); session.goBack(); session.undo(); session.keepInstead(ids[0]); session.forget([])
    assert len(seen) == 5                                             # keepInstead of a kept/waiting image changes nothing


# ---- the folder's pictures ---------------------------------------------------------------------------

def test_image_ids_are_the_pictures_shown_in_the_current_order(tmp_path, qapp):
    folder = tmp_path / "Mixed"
    folder.mkdir()
    for name in ("b.png", "a.png", "c.png"):
        (folder / name).write_bytes(b"x" * (3 if name == "c.png" else 1))
    (folder / "clip.mp4").write_bytes(b"v")
    (folder / "book.cbz").write_bytes(b"c")
    model = MediaModel()
    model.load_from_qurl(covers.folder_uri(str(folder)))
    ids = model.imageIds()
    assert len(ids) == 3 and all(isinstance(i, int) for i in ids)
    rows = get_database().get_media_rows(ids)
    assert [rows[i]["name"] for i in ids] == ["a.png", "b.png", "c.png"]       # no video, no comic; natural order
    model.sortMode = MediaModel.SortMode.LargestFirst
    assert [get_database().get_media_rows(model.imageIds())[i]["name"] for i in model.imageIds()][0] == "c.png"
