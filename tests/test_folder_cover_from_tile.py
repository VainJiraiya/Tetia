# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import subprocess

import pytest

from tetia.models import covers, series
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel
from tetia.models.subfolderModel import SubfolderModel
from test_bookcovers import cbz, picture


def _open(parent):
    model = MediaModel()
    model.load_from_qurl(covers.folder_uri(str(parent)))
    return model


def _cover_of(folder):
    return get_database().get_collection_meta(covers.folder_key(str(folder)))["cover_path"]


def test_a_one_file_folder_can_lend_its_file_as_the_folder_cover(tmp_path, qapp):
    parent = tmp_path / "Library"
    (parent / "Solo").mkdir(parents=True)
    book = cbz(parent / "Solo" / "only.cbz", [("1.png", picture(100, 150))])
    model = _open(parent)
    assert model.setFolderCoverFromPath(book)
    assert _cover_of(parent) == book                       # a comic is used as the file itself (its first page)


def test_an_image_is_copied_into_the_covers_folder(tmp_path, qapp):
    parent = tmp_path / "Library"
    (parent / "Series").mkdir(parents=True)
    pic = parent / "Series" / "cover.png"
    picture(200, 300).save(str(pic))
    assert _open(parent).setFolderCoverFromPath(str(pic))
    stored = _cover_of(parent)
    assert stored != str(pic) and covers._in_covers_dir(stored) and os.path.isfile(stored)


def test_a_series_tile_can_lend_its_first_chapter(tmp_path, qapp):
    parent = tmp_path / "Library"
    (parent / "Dragon").mkdir(parents=True)
    first = cbz(parent / "Dragon" / "Vol.1 Ch.1.cbz", [("1.png", picture(100, 150))])
    cbz(parent / "Dragon" / "Vol.1 Ch.2.cbz", [("1.png", picture(100, 150, color="red"))])
    series.set_series(get_database(), str(parent / "Dragon"), True)
    sub = SubfolderModel()
    sub.filterMode = int(MediaModel.FilterMode.MangaOnly)
    sub.load(str(parent))
    hero = sub.data(sub.index(0), sub.Roles.HeroPathRole)       # what the tile shows
    assert hero == first
    assert _open(parent).setFolderCoverFromPath(hero)
    assert _cover_of(parent) == first


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_video_gives_a_frame(tmp_path, qapp):
    parent = tmp_path / "Library"
    (parent / "Clip").mkdir(parents=True)
    video = parent / "Clip" / "movie.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=64x48:rate=10",
                    "-c:v", "mpeg4", str(video)], check=True)
    assert _open(parent).setFolderCoverFromPath(str(video))
    stored = _cover_of(parent)
    assert stored.endswith(".jpg") and covers._in_covers_dir(stored)


def test_it_refuses_what_cannot_be_a_cover(tmp_path, qapp):
    parent = tmp_path / "Library"
    (parent / "Sub").mkdir(parents=True)
    notes = parent / "Sub" / "notes.txt"
    notes.write_text("x")
    model = _open(parent)
    assert not model.setFolderCoverFromPath(str(notes))                      # not a picture, comic, book or video
    assert not model.setFolderCoverFromPath("")
    assert not model.setFolderCoverFromPath(str(parent / "Sub" / "gone.cbz"))   # no such file
    assert _cover_of(parent) is None
    nothing_open = MediaModel()                                              # no folder shown (search results)
    book = cbz(parent / "Sub" / "b.cbz", [("1.png", picture(100, 150))])
    assert not nothing_open.setFolderCoverFromPath(book)


def test_a_cover_set_this_way_replaces_the_previous_one(tmp_path, qapp):
    parent = tmp_path / "Library"
    (parent / "A").mkdir(parents=True)
    (parent / "B").mkdir(parents=True)
    one = parent / "A" / "one.png"
    two = parent / "B" / "two.png"
    picture(100, 100).save(str(one))
    picture(100, 100, color="red").save(str(two))
    model = _open(parent)
    assert model.setFolderCoverFromPath(str(one))
    first = _cover_of(parent)
    assert model.setFolderCoverFromPath(str(two))
    assert _cover_of(parent) != first and not os.path.exists(first)        # the old copy is cleaned up
