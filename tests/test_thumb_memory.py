# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thumbnails asked for again: kept in memory, and a book's small cover is not made again on every request."""
import os

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from tetia import timing
from tetia.models import thumbModel
from tetia.models.thumbModel import ThumbnailProvider
from test_bookcovers import cbz, picture


def _ask(provider, path, hint=512):
    return provider.requestImage(str(path), QSize(), QSize(hint, hint))


def _counting(monkeypatch, provider):
    made = []
    real = provider._generate
    monkeypatch.setattr(provider, "_generate", lambda *a: (made.append(1), real(*a))[1])
    return made


def test_a_small_cover_is_made_once_then_kept(tmp_path, monkeypatch, qapp):
    book = cbz(tmp_path / "small.cbz", [("1.png", picture(120, 180, ink=0.4))])   # a page smaller than the tile
    provider = ThumbnailProvider()
    made = _counting(monkeypatch, provider)
    first = _ask(provider, book)
    assert first.height() == 180                                       # covers are never scaled up
    assert first.text("Thumb::Image::Height") == "180"                 # marked: as big as its page allows
    again = ThumbnailProvider()                                        # (a new provider: nothing in memory)
    monkeypatch.setattr(again, "_generate", lambda *a: (made.append(1), QImage())[1])
    assert _ask(again, book).height() == 180
    assert made == [1]                                                 # not made again from the archive


def test_a_thumbnail_asked_for_again_comes_from_memory(tmp_path, qapp):
    source = tmp_path / "pic.png"
    image = QImage(300, 200, QImage.Format_RGB32)
    image.fill(QColor("navy"))
    image.save(str(source))
    provider = ThumbnailProvider()
    reads = []
    real = provider._read_cached
    provider._read_cached = lambda *a: (reads.append(1), real(*a))[1]
    _ask(provider, source, 256)
    first = len(reads)
    assert _ask(provider, source, 256).width() == 256
    assert len(reads) == first                                         # no disk the second time
    os.utime(source, (1, 1))                                           # the file changed: read again
    _ask(provider, source, 256)
    assert len(reads) > first
    count = len(reads)
    thumbModel.forget_thumbnails(str(source))                          # a cover changed by hand: forgotten
    _ask(provider, source, 256)
    assert len(reads) > count


def test_memory_is_capped(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(thumbModel, "MEMORY_BUDGET", 300 * 300 * 4 * 2)
    provider = ThumbnailProvider()
    for i in range(5):
        source = tmp_path / f"{i}.png"
        image = QImage(300, 300, QImage.Format_RGB32)
        image.fill(QColor("olive"))
        image.save(str(source))
        _ask(provider, source, 256)
    assert len(provider._memory) <= 3 and provider._memory_bytes <= thumbModel.MEMORY_BUDGET + 256 * 256 * 4


def test_timing_says_numbers_and_labels_only(monkeypatch):
    monkeypatch.setattr(timing, "ENABLED", True)
    monkeypatch.setattr(timing, "_samples", {})
    timing.record("thumb image: pack", 12.5)
    timing.record("thumb image: pack", 7.5)
    with timing.timed("home: the pins"):
        pass
    text = timing.summary()
    assert "thumb image: pack" in text and "home: the pins" in text and "20" in text
    monkeypatch.setattr(timing, "ENABLED", False)
    assert timing.measured("x")(len) is len                            # off: functions are left as they are
