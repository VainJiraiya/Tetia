# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import os
import zipfile

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QColor, QImage, QPainter

from tetia.models import bookcovers, thumbModel
from tetia.models.thumbModel import ThumbnailProvider


def picture(width, height, ink=0.3, color="#1e4fd0", background="white"):
    """A page: `background` with a block of `color` covering about `ink` of it."""
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(background))
    if ink > 0:
        block_h = min(height, int(height * ink / 0.8))
        painter = QPainter(image)
        painter.fillRect(int(width * 0.1), (height - block_h) // 2, int(width * 0.8), block_h, QColor(color))
        painter.end()
    return image


def png(image):
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def cbz(path, pages):
    """pages: [(member name, QImage)]."""
    with zipfile.ZipFile(path, "w") as archive:
        for name, image in pages:
            archive.writestr(name, png(image))
    return str(path)


def middle(image):
    c = image.pixelColor(image.width() // 2, image.height() // 2)
    return c.red(), c.green(), c.blue()


BLUE = (0x1e, 0x4f, 0xd0)


# ---- scoring -----------------------------------------------------------------------

def test_blank_pages_score_zero_and_content_scores_high():
    assert bookcovers.content(picture(200, 300, ink=0)) < 0.001                                  # white
    assert bookcovers.content(picture(200, 300, ink=0, background="black")) < 0.001              # black
    assert bookcovers.content(picture(200, 300, ink=0, background="#336699")) < 0.001            # one colour
    assert bookcovers.content(picture(200, 300, ink=0.4)) > 0.3


def test_the_cover_skips_blank_black_and_nearly_empty_pages(tmp_path):
    path = cbz(tmp_path / "ch1.cbz", [
        ("01.png", picture(200, 300, ink=0)),                      # white
        ("02.png", picture(200, 300, ink=0, background="black")),  # black
        ("03.png", picture(200, 300, ink=0.02)),                   # a line of text
        ("04.png", picture(200, 300, ink=0.4)),                    # the real cover
        ("05.png", picture(200, 300, ink=0.5, color="red")),
    ])
    assert middle(bookcovers.make_cover(path, 128)) == BLUE


def test_a_black_and_white_manga_cover_is_not_skipped(tmp_path):
    path = cbz(tmp_path / "bw.cbz", [
        ("01.png", picture(200, 300, ink=0.25, color="black")),
        ("02.png", picture(200, 300, ink=0.5, color="red")),
    ])
    assert middle(bookcovers.make_cover(path, 128)) == (0, 0, 0)      # page one, as it is


def test_a_sparse_title_page_is_used_when_nothing_better_exists(tmp_path):
    path = cbz(tmp_path / "t.cbz", [
        ("01.png", picture(200, 300, ink=0)),
        ("02.png", picture(200, 300, ink=0.03, color="green")),     # low content, but the best
        ("03.png", picture(200, 300, ink=0)),
    ])
    cover = bookcovers.make_cover(path, 128)
    assert cover.pixelColor(cover.width() // 2, cover.height() // 2).green() > 100


def test_all_blank_gives_the_first_page(tmp_path):
    path = cbz(tmp_path / "blank.cbz", [("01.png", picture(100, 150, ink=0, background="#fefefe")),
                                        ("02.png", picture(100, 150, ink=0, background="black"))])
    assert middle(bookcovers.make_cover(path, 128)) == (0xfe, 0xfe, 0xfe)


def test_a_double_page_spread_is_not_chosen_over_a_portrait_page(tmp_path):
    path = cbz(tmp_path / "spread.cbz", [
        ("01.png", picture(1000, 500, ink=0.5, color="red")),      # wide
        ("02.png", picture(200, 300, ink=0.4)),
    ])
    assert middle(bookcovers.make_cover(path, 128)) == BLUE


def test_pages_are_taken_in_natural_order(tmp_path):
    path = cbz(tmp_path / "order.cbz", [
        ("page10.png", picture(200, 300, ink=0.4, color="red")),
        ("page2.png", picture(200, 300, ink=0.4)),                  # this one is the second page
        ("page1.png", picture(200, 300, ink=0.4, color="#00aa00")),
    ])
    assert middle(bookcovers.make_cover(path, 128))[1] > 150         # page1 (green) first, not page10


def test_a_tall_strip_is_cut_to_a_portrait_piece_from_its_top(tmp_path):
    strip = QImage(300, 3000, QImage.Format_RGB32)
    strip.fill(QColor("white"))
    painter = QPainter(strip)
    painter.fillRect(0, 0, 300, 600, QColor(BLUE[0], BLUE[1], BLUE[2]))       # the top is blue
    painter.fillRect(0, 600, 300, 2400, QColor("black"))
    painter.end()
    cover = bookcovers.make_cover(cbz(tmp_path / "strip.cbz", [("01.png", strip)]), 256)
    assert cover.height() == 256 and cover.width() == round(256 / bookcovers.PORTRAIT)
    assert cover.pixelColor(cover.width() // 2, 10).blue() > 150                # taken from the top


def test_a_cover_is_never_bigger_than_the_tier(tmp_path):
    cover = bookcovers.make_cover(cbz(tmp_path / "big.cbz", [("1.png", picture(2400, 3400, ink=0.4))]), 256)
    assert max(cover.width(), cover.height()) == 256
    small = bookcovers.make_cover(cbz(tmp_path / "tiny.cbz", [("1.png", picture(60, 90, ink=0.4))]), 256)
    assert (small.width(), small.height()) == (60, 90)                          # not scaled up


def test_unreadable_archives_give_a_null_cover(tmp_path):
    junk = tmp_path / "junk.cbz"
    junk.write_bytes(b"not a zip at all")
    rar = tmp_path / "old.cbz"
    rar.write_bytes(b"Rar!\x1a\x07\x00 something")
    empty = tmp_path / "empty.cbz"
    zipfile.ZipFile(empty, "w").close()
    nothing = cbz(tmp_path / "text.cbz", [])
    for path in (junk, rar, empty, nothing, tmp_path / "missing.cbz"):
        assert bookcovers.make_cover(str(path), 128).isNull()
    assert bookcovers.make_cover(str(tmp_path / "x.mobi"), 128).isNull()


def test_a_huge_page_is_skipped(tmp_path, monkeypatch):
    path = cbz(tmp_path / "big.cbz", [("1.png", picture(400, 600, ink=0.4, color="red")),
                                      ("2.png", picture(100, 150, ink=0.4))])
    monkeypatch.setattr(bookcovers, "MAX_PAGE_BYTES", 2000)         # page 1 is now "too big"
    assert middle(bookcovers.make_cover(path, 128)) == BLUE


# ---- EPUB ------------------------------------------------------------------------------

CONTAINER = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>' \
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'


def epub(path, manifest, extra_meta="", images=None):
    items = "".join(f'<item id="{i}" href="{h}" media-type="image/png" {p}/>' for i, h, p in manifest)
    opf = f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">' \
          f'<dc:title>T</dc:title>{extra_meta}</metadata><manifest>{items}</manifest></package>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", opf)
        for name, image in (images or {}).items():
            archive.writestr("OEBPS/" + name, png(image))
    return str(path)


def test_epub_uses_the_declared_cover(tmp_path):
    images = {"images/a_first.png": picture(200, 300, ink=0.4, color="red"),
              "images/front.png": picture(200, 300, ink=0.4)}
    path = epub(tmp_path / "b.epub", [("a", "images/a_first.png", ""), ("c", "images/front.png", 'properties="cover-image"')],
                images=images)
    assert middle(bookcovers.make_cover(path, 128)) == BLUE
    # EPUB 2 style: <meta name="cover" content="id">
    path2 = epub(tmp_path / "b2.epub", [("a", "images/a_first.png", ""), ("c", "images/front%20.png", "")],
                 extra_meta='<meta name="cover" content="c"/>',
                 images={"images/a_first.png": images["images/a_first.png"], "images/front .png": images["images/front.png"]})
    assert middle(bookcovers.make_cover(path2, 128)) == BLUE


def test_epub_without_a_declared_cover_uses_one_named_cover_or_the_first_image(tmp_path):
    images = {"images/p1.png": picture(200, 300, ink=0.4, color="red"), "images/cover.png": picture(200, 300, ink=0.4)}
    named = epub(tmp_path / "n.epub", [("i1", "images/p1.png", ""), ("i2", "images/cover.png", "")], images=images)
    assert middle(bookcovers.make_cover(named, 128)) == BLUE
    first = epub(tmp_path / "f.epub", [("i1", "images/p1.png", "")], images={"images/p1.png": images["images/p1.png"]})
    assert middle(bookcovers.make_cover(first, 128))[0] > 200


def test_a_broken_epub_gives_a_null_cover(tmp_path):
    broken = tmp_path / "x.epub"
    broken.write_bytes(b"not a zip")
    assert bookcovers.make_cover(str(broken), 128).isNull()


# ---- PDF ---------------------------------------------------------------------------------

def test_pdf_skips_a_blank_first_page(tmp_path):
    from PySide6.QtGui import QPageSize, QPdfWriter
    path = tmp_path / "paper.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    painter.drawRect(0, 0, 1, 1)                      # page one: effectively empty
    writer.newPage()
    painter.fillRect(500, 500, 6000, 7000, QColor(BLUE[0], BLUE[1], BLUE[2]))
    painter.end()
    cover = bookcovers.make_cover(str(path), 200)
    assert max(cover.width(), cover.height()) == 200
    assert cover.pixelColor(cover.width() // 2, cover.height() // 2).blue() > 150      # page two
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"%PDF-1.4 nothing")
    assert bookcovers.make_cover(str(junk), 200).isNull()


# ---- the provider ----------------------------------------------------------------------------

def _cache_name(path):
    return hashlib.md5(thumbModel._local_path_to_thumb_uri(str(path)).encode()).hexdigest() + ".png"


def _request(provider, path, hint=0):
    size = QSize()
    return provider.requestImage(str(path), QSize(hint, hint) if hint else QSize(), size)


def test_a_comic_without_a_cached_cover_gets_one_made_and_saved(tmp_path):
    path = cbz(tmp_path / "deep.cbz", [("1.png", picture(200, 300, ink=0.4))])
    provider = ThumbnailProvider()
    image = _request(provider, path)
    assert middle(image) == BLUE
    saved = provider.thumbnails_base / "large" / _cache_name(path)             # 256 px is the "large" tier
    assert saved.exists()
    stored = QImage(str(saved))
    assert stored.text("Thumb::URI") == thumbModel._local_path_to_thumb_uri(str(path))
    assert stored.text("Thumb::MTime") == str(int(os.stat(path).st_mtime))
    assert stored.text("Thumb::Size") == str(os.stat(path).st_size)
    # a second request is a hit: nothing is regenerated
    saved.write_bytes(saved.read_bytes())
    mtime = saved.stat().st_mtime_ns
    assert middle(_request(provider, path)) == BLUE
    assert saved.stat().st_mtime_ns == mtime


def test_a_changed_file_gets_a_new_cover(tmp_path):
    path = tmp_path / "vol.cbz"
    cbz(path, [("1.png", picture(200, 300, ink=0.4))])
    provider = ThumbnailProvider()
    assert middle(_request(provider, path)) == BLUE
    cbz(path, [("1.png", picture(200, 300, ink=0.4, color="#00aa00"))])         # replaced
    os.utime(path, (os.stat(path).st_atime, os.stat(path).st_mtime + 100))
    assert middle(_request(provider, path))[1] > 150                           # green now, not the cached blue


def test_images_are_remade_when_the_cached_one_is_stale(tmp_path):
    path = tmp_path / "pic.png"
    picture(300, 300, ink=0.4).save(str(path))
    provider = ThumbnailProvider()
    assert middle(_request(provider, path)) == BLUE
    picture(300, 300, ink=0.4, color="#aa0000").save(str(path))
    os.utime(path, (os.stat(path).st_atime, os.stat(path).st_mtime + 100))
    assert middle(_request(provider, path))[0] > 120


def test_an_unreadable_comic_is_not_retried_while_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "bad.cbz"
    path.write_bytes(b"junk")
    provider = ThumbnailProvider()
    calls = []
    real = bookcovers.make_cover
    monkeypatch.setattr(bookcovers, "make_cover", lambda p, e: (calls.append(p), real(p, e))[1])
    assert _request(provider, path).isNull()
    assert _request(provider, path).isNull()
    assert len(calls) == 1
