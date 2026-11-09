# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""A private profile keeps its thumbnails in one file (a vault on a hard drive reads one file far faster than
thousands); General keeps the shared freedesktop folders."""
import hashlib
import sqlite3

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from tetia.models import profiles, thumbModel, thumbPack
from tetia.models.thumbModel import ThumbnailProvider


@pytest.fixture
def private(qapp):
    profile, _ = profiles.create("Hidden")
    profiles.activate(profile["id"])
    try:
        yield profile
    finally:
        thumbPack._close_current()
        profiles.activate(None)


def _picture(path, edge=64):
    image = QImage(edge, edge, QImage.Format_RGB32)
    image.fill(QColor("orange"))
    image.save(str(path))
    return path


def _md5(path):
    return hashlib.md5(thumbModel._local_path_to_thumb_uri(str(path)).encode()).hexdigest()


def _request(provider, path, hint=128):
    return provider.requestImage(str(path), QSize(), QSize(hint, hint))


def test_the_pack_keeps_forgets_and_lets_go(tmp_path):
    pack = thumbPack.ThumbPack(tmp_path / "thumbnails.db")
    assert pack.put("abc", "normal", b"one") and pack.put("abc", "large", b"two")
    assert pack.put("abc", "normal", b"three")                       # made again: replaced
    assert pack.get("abc") == {"normal": b"three", "large": b"two"} and pack.get("nothing") == {}
    page = sqlite3.connect(str(tmp_path / "thumbnails.db")).execute("PRAGMA page_size").fetchone()[0]
    assert page == thumbPack.PAGE_SIZE
    pack.forget("abc")
    assert pack.get("abc") == {}
    pack.close()
    assert pack.get("abc") == {} and not pack.put("abc", "normal", b"x")   # closed: nothing is opened again


def test_a_private_profile_keeps_its_thumbnails_in_the_pack(tmp_path, private):
    source = _picture(tmp_path / "pic.png")
    provider = ThumbnailProvider()
    assert not _request(provider, source).isNull()
    pack = thumbPack.pack()
    assert pack.path == profiles.profile_dir() / "thumbnails.db"
    stored = pack.get(_md5(source))
    assert list(stored) == ["normal"]
    assert QImage.fromData(stored["normal"], "PNG").text("Thumb::MTime")           # tagged like the spec's files
    assert not any(profiles.thumbnail_base().rglob("*.png"))                         # no loose files
    again = ThumbnailProvider()
    assert _request(again, source).width() == 128                                    # read back from the pack


def test_an_older_tetias_thumbnail_files_move_into_the_pack(tmp_path, private):
    source = _picture(tmp_path / "pic.png")
    folder = profiles.thumbnail_base() / "large"
    folder.mkdir(parents=True)
    old = QImage(256, 256, QImage.Format_RGB32)
    old.fill(QColor("white"))
    old.save(str(folder / (_md5(source) + ".png")))
    provider = ThumbnailProvider()
    image = _request(provider, source, 256)
    assert image.width() == 256 and image.pixelColor(10, 10) == QColor("white")      # the old one, not made again
    assert "large" in thumbPack.pack().get(_md5(source))
    assert not (folder / (_md5(source) + ".png")).exists()                         # moved, not copied


def test_a_changed_cover_is_forgotten_in_the_pack(tmp_path, private):
    source = _picture(tmp_path / "pic.png")
    _request(ThumbnailProvider(), source)
    thumbModel.forget_thumbnails(str(source))
    assert thumbPack.pack().get(_md5(source)) == {}


def test_general_keeps_the_shared_folders(tmp_path, qapp):
    profiles.activate(None)
    source = _picture(tmp_path / "pic.png")
    provider = ThumbnailProvider()
    assert thumbPack.pack() is None
    _request(provider, source)
    assert (provider.thumbnails_base / "normal" / (_md5(source) + ".png")).exists()
    assert not (profiles.profile_dir() / "thumbnails.db").exists()
