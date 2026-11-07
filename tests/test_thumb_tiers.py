# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from tetia.models import thumbModel
from tetia.models.thumbModel import ThumbnailProvider


def _cache(base, tier, edge, source):
    """Put a thumbnail of `edge` pixels for `source` in the cache's `tier` folder."""
    uri = thumbModel._local_path_to_thumb_uri(str(source))
    folder = base / tier
    folder.mkdir(parents=True, exist_ok=True)
    image = QImage(edge, edge, QImage.Format_RGB32)
    image.fill(QColor("white"))
    image.save(str(folder / f"{hashlib.md5(uri.encode()).hexdigest()}.png"))


def _edge(provider, source, hint):
    size = QSize()
    image = provider.requestImage(str(source), size, QSize(hint, hint) if hint else QSize())
    return image.width()


def test_the_tile_asks_for_the_tier_it_needs(tmp_path):
    source = tmp_path / "pic.png"
    QImage(64, 64, QImage.Format_RGB32).save(str(source))
    provider = ThumbnailProvider()
    base = provider.thumbnails_base
    for tier, edge in (("normal", 128), ("large", 256), ("x-large", 512)):
        _cache(base, tier, edge, source)

    assert _edge(provider, source, 0) == 512        # no hint: biggest, as it always was
    assert _edge(provider, source, 128) == 128      # small tiles: the normal thumbnail
    assert _edge(provider, source, 256) == 256
    assert _edge(provider, source, 512) == 512
    assert _edge(provider, source, 320) == 512      # the folder grid's usual hint


def test_a_missing_small_tier_uses_a_larger_one(tmp_path):
    source = tmp_path / "pic.png"
    QImage(64, 64, QImage.Format_RGB32).save(str(source))
    provider = ThumbnailProvider()
    _cache(provider.thumbnails_base, "large", 256, source)
    assert _edge(provider, source, 128) == 256      # no normal one: a bigger one will do


def test_a_too_small_thumbnail_in_a_big_tier_is_made_again(tmp_path):
    source = tmp_path / "photo.png"
    big = QImage(900, 900, QImage.Format_RGB32)
    big.fill(QColor("red"))
    big.save(str(source))
    provider = ThumbnailProvider()
    _cache(provider.thumbnails_base, "x-large", 320, source)       # what older versions left behind
    assert _edge(provider, source, 512) == 512                     # made again at the real size
    assert _edge(provider, source, 512) == 512                     # and kept: the second time it is a hit
    stored = QImage(str(provider.thumbnails_base / "x-large"
                        / (hashlib.md5(thumbModel._local_path_to_thumb_uri(str(source)).encode()).hexdigest() + ".png")))
    assert max(stored.width(), stored.height()) == 512


def test_a_missing_big_tier_is_generated_not_stretched_from_a_small_one(tmp_path):
    source = tmp_path / "photo.png"
    big = QImage(900, 900, QImage.Format_RGB32)
    big.fill(QColor("blue"))
    big.save(str(source))
    provider = ThumbnailProvider()
    _cache(provider.thumbnails_base, "normal", 128, source)
    assert _edge(provider, source, 256) == 256                     # not the 128 one blown up


def test_files_tetia_cannot_draw_use_whatever_the_cache_has(tmp_path):
    source = tmp_path / "book.cbz"
    source.write_bytes(b"not an image")
    provider = ThumbnailProvider()
    _cache(provider.thumbnails_base, "large", 256, source)         # made by Dolphin
    assert _edge(provider, source, 512) == 256


def test_a_big_tile_gets_the_1024_tier_and_a_small_one_does_not(tmp_path):
    source = tmp_path / "cover.png"
    big = QImage(2000, 2000, QImage.Format_RGB32)
    big.fill(QColor("white"))
    big.save(str(source))
    provider = ThumbnailProvider()
    assert _edge(provider, source, 1024) == 1024                    # a tile drawn bigger than 512 real pixels
    assert (provider.thumbnails_base / "xx-large").exists()         # and kept where the freedesktop spec puts it
    assert len(list((provider.thumbnails_base / "xx-large").glob("*.png"))) == 1
    assert _edge(provider, source, 600) == 1024                     # anything between 512 and 1024 rounds up
    small = tmp_path / "other.png"                                  # a file that has no thumbnail yet
    QImage(2000, 2000, QImage.Format_RGB32).save(str(small))
    assert _edge(provider, small, 256) == 256                       # a small tile does not make the big one
    assert not any((provider.thumbnails_base / "xx-large").glob("*other*"))
