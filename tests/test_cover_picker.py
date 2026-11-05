# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import zipfile

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from tetia.models import bookcovers, bookpages, covers, thumbModel
from tetia.models.coverPicker import CoverPicker
from tetia.models.database import get_database
from tetia.models.thumbModel import ThumbnailProvider
from test_bookcovers import BLUE, cbz, epub, middle, picture


def media_id(path, kind="comic"):
    info = os.stat(path)
    db = get_database()
    media = db.upsert_media(str(path), os.path.basename(path), kind, info.st_size,
                            int(info.st_mtime), "h" + os.path.basename(path))[0]
    db.conn.commit()            # a scan commits its whole transaction; a helper must too
    return media


def five_pages(tmp_path, name="book.cbz"):
    """Pages: blue, red, green, black block, white - so every pick can be told apart."""
    return cbz(tmp_path / name, [
        ("p1.png", picture(300, 450, ink=0.4)),
        ("p2.png", picture(300, 450, ink=0.4, color="#cc0000")),
        ("p3.png", picture(300, 450, ink=0.4, color="#00aa00")),
        ("p4.png", picture(300, 450, ink=0.4, color="black")),
        ("p5.png", picture(300, 450, ink=0)),
    ])


# ---- listing and reading pages ----------------------------------------------------------

def test_cbz_pages_are_listed_in_natural_order_without_junk(tmp_path):
    path = cbz(tmp_path / "x.cbz", [("page10.png", picture(50, 80)), ("page2.png", picture(50, 80)),
                                    ("__MACOSX/page1.png", picture(50, 80)), ("notes.txt", picture(50, 80))])
    refs, message = bookpages.list_pages(path)
    assert refs == ["page2.png", "page10.png"] and message == ""


def test_the_page_list_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(bookpages, "PAGE_LIMIT", 3)
    path = cbz(tmp_path / "many.cbz", [(f"{i:02d}.png", picture(20, 30)) for i in range(10)])
    assert len(bookpages.list_pages(path)[0]) == 3


def test_pages_of_other_formats_and_bad_files(tmp_path):
    for name, content in (("a.cbz", b"junk"), ("b.cbr", b"Rar!"), ("c.cb7", b"7z"), ("d.mobi", b"x")):
        (tmp_path / name).write_bytes(content)
        refs, message = bookpages.list_pages(str(tmp_path / name))
        assert refs == [] and message
    empty = tmp_path / "empty.cbz"
    zipfile.ZipFile(empty, "w").close()
    assert bookpages.list_pages(str(empty)) == ([], "There are no pictures in this archive.")
    assert "works for" in bookpages.list_pages(str(tmp_path / "b.cbr"))[1]


def test_epub_pages_start_with_the_cover(tmp_path):
    images = {"images/a.png": picture(100, 150, color="red"), "images/front.png": picture(100, 150)}
    path = epub(tmp_path / "b.epub", [("a", "images/a.png", ""), ("c", "images/front.png", 'properties="cover-image"')],
                images=images)
    refs, _ = bookpages.list_pages(path)
    assert refs[0].endswith("front.png") and len(refs) == 2


def test_pdf_pages_are_numbered(tmp_path):
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
    path = tmp_path / "p.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    for i in range(3):
        painter.fillRect(500, 500, 3000 + i * 1000, 3000, QColor("blue"))
        if i < 2:
            writer.newPage()
    painter.end()
    refs, _ = bookpages.list_pages(str(path))
    assert refs == ["0", "1", "2"]
    page = bookpages.read_page(str(path), "1", 200)
    assert max(page.width(), page.height()) == 200


def test_read_page_respects_the_size_and_survives_damage(tmp_path):
    path = five_pages(tmp_path)
    page = bookpages.read_page(path, "p2.png", 100)
    assert max(page.width(), page.height()) == 100 and middle(page)[0] > 150
    assert bookpages.read_page(path, "nope.png", 100).isNull()
    assert bookpages.read_page(str(tmp_path / "gone.cbz"), "p1.png", 100).isNull()


def test_the_image_provider_serves_pages_by_token(tmp_path, qapp):
    path = five_pages(tmp_path)
    refs, _ = bookpages.list_pages(path)
    token = bookpages.register(path, refs)
    provider = bookpages.BookPageProvider()
    size = QSize()
    image = provider.requestImage(f"{token}/2", QSize(), size)
    assert middle(image)[1] > 120 and size.width() == image.width()          # page 3 is green
    assert provider.requestImage(f"{token}/99", QSize(), QSize()).isNull()
    assert provider.requestImage("unknown/0", QSize(), QSize()).isNull()
    bookpages.unregister(token)
    assert provider.requestImage(f"{token}/0", QSize(), QSize()).isNull()


# ---- choosing a cover ---------------------------------------------------------------------------------

def test_choosing_a_page_sets_the_cover_and_survives_a_cleared_cache(tmp_path, qapp):
    path = five_pages(tmp_path)
    mid = media_id(path)
    provider = ThumbnailProvider()
    thumb = lambda: provider.requestImage(str(path), QSize(), QSize())
    assert middle(thumb()) == BLUE                                         # automatic: the first good page
    assert any((provider.thumbnails_base / t).exists() for t in ("normal", "large", "x-large"))

    picker = CoverPicker()
    changed = []
    picker.coverChanged.connect(changed.append)
    assert picker.open(mid) and picker.count == 5 and picker.title == "book.cbz" and not picker.custom
    assert picker.choose(2)                                                # the green page
    assert changed == [str(path)] and picker.custom
    stored = get_database().get_book_cover(str(path))
    assert stored and os.path.isfile(stored) and covers._in_covers_dir(stored)
    assert max(QImage(stored).width(), QImage(stored).height()) <= bookpages.CHOSEN_EDGE
    assert middle(thumb())[1] > 120                                        # green, not the old blue
    # a cache cleaner wipes the thumbnails: the choice is still there
    for tier in ("normal", "large", "x-large"):
        d = provider.thumbnails_base / tier
        for f in (d.glob("*.png") if d.exists() else []):
            f.unlink()
    assert middle(thumb())[1] > 120


def test_choosing_again_replaces_the_picture_and_deletes_the_old_one(tmp_path, qapp):
    path = five_pages(tmp_path)
    picker = CoverPicker()
    picker.open(media_id(path))
    picker.choose(1)
    first = get_database().get_book_cover(str(path))
    picker.choose(0)
    second = get_database().get_book_cover(str(path))
    assert second != first and not os.path.exists(first) and os.path.exists(second)


def test_going_back_to_the_automatic_cover(tmp_path, qapp):
    path = five_pages(tmp_path)
    provider = ThumbnailProvider()
    picker = CoverPicker()
    picker.open(media_id(path))
    picker.choose(2)
    picked = get_database().get_book_cover(str(path))
    changed = []
    picker.coverChanged.connect(changed.append)
    assert picker.useAutomatic()
    assert get_database().get_book_cover(str(path)) is None and not os.path.exists(picked) and not picker.custom
    assert changed == [str(path)]
    assert middle(provider.requestImage(str(path), QSize(), QSize())) == BLUE


def test_a_picked_page_survives_the_archive_being_changed_or_missing_image(tmp_path, qapp):
    path = five_pages(tmp_path)
    picker = CoverPicker()
    picker.open(media_id(path))
    picker.choose(1)
    picked = get_database().get_book_cover(str(path))
    os.remove(picked)                                                # the stored picture was deleted behind our back
    assert bookcovers.chosen_cover(str(path)) == ""
    assert middle(bookcovers.make_cover(str(path), 128)) == BLUE     # falls back to the automatic cover


def test_open_and_choose_fail_cleanly(tmp_path, qapp):
    picker = CoverPicker()
    assert not picker.open(99999)                                    # no such file in the library
    assert not picker.choose(0) and not picker.useAutomatic()
    rar = tmp_path / "old.cbr"
    rar.write_bytes(b"Rar!")
    assert picker.open(media_id(rar)) and picker.count == 0 and "works for" in picker.message
    assert not picker.choose(0)
    path = five_pages(tmp_path)
    picker.open(media_id(path))
    assert not picker.choose(7) and not picker.choose(-1)
    picker.close()
    assert picker.count == 0 and picker.token == ""


def test_a_refresh_marker_on_the_id_is_ignored_by_the_thumbnail_provider(tmp_path, qapp):
    path = five_pages(tmp_path)
    provider = ThumbnailProvider()
    plain = provider.requestImage(str(path), QSize(), QSize())
    marked = provider.requestImage(str(path) + "?v=3", QSize(), QSize())
    assert not marked.isNull() and middle(marked) == middle(plain) == BLUE


def test_a_file_can_be_opened_by_path_or_uri(tmp_path, qapp):
    path = five_pages(tmp_path)                                       # never added to the library
    picker = CoverPicker()
    assert picker.open(media_id(path)) is True
    assert picker.openPath(path) and picker.count == 5 and picker.title == "book.cbz"
    assert picker.openPath(covers.folder_uri(path)) and picker.count == 5     # a file:// URI too
    assert picker.choose(1)
    assert picker.custom and get_database().get_book_cover(path)
    assert not picker.openPath(str(tmp_path / "missing.cbz")) and picker.count == 0
