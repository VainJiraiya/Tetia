# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import zipfile

import pytest
from PySide6.QtGui import QColor, QImage, QPainter

from tetia.models import reader
from tetia.models.database import get_database
from tetia.models.reader import ReaderError
from test_bookcovers import cbz, epub, picture, png

# ---- helpers ---------------------------------------------------------------------------


def gradient(width, height):
    """A tall picture whose colour changes smoothly down its length, so any gap or overlap shows."""
    image = QImage(width, height, QImage.Format_RGB32)
    painter = QPainter(image)
    for y in range(height):
        painter.fillRect(0, y, width, 1, QColor(int(255 * y / height), int(255 - 255 * y / height), 128))
    painter.end()
    return image


def rows(image):
    return [image.pixelColor(image.width() // 2, y).rgb() for y in range(image.height())]


def book(tmp_path, pages, name="b.cbz", extra=()):
    return reader.open_book(cbz(tmp_path / name, list(pages) + list(extra)))


# ---- pure helpers -------------------------------------------------------------------------

def test_chunk_boundaries_split_evenly_and_cover_the_page():
    assert reader.chunk_boundaries(3059) == [0, 3059]                      # a Mihon piece stays whole
    assert reader.chunk_boundaries(4096) == [0, 4096]
    bounds = reader.chunk_boundaries(12000)
    assert bounds == [0, 4000, 8000, 12000]
    for height in (4097, 8193, 30001, 99999):
        bounds = reader.chunk_boundaries(height)
        sizes = [b - a for a, b in zip(bounds, bounds[1:])]
        assert bounds[0] == 0 and bounds[-1] == height and max(sizes) <= reader.MAX_CHUNK and min(sizes) > 0
        assert max(sizes) - min(sizes) <= 1                                   # equal, not a tiny last piece
    assert reader.chunk_boundaries(1) == [0, 1]


def test_pieces_are_contiguous_and_know_their_page():
    pieces = reader.pieces_for([(700, 900), (700, 9000), (500, 100)])
    assert [(p["page"], p["chunk"]) for p in pieces] == [(0, 0), (1, 0), (1, 1), (1, 2), (2, 0)]
    page1 = [p for p in pieces if p["page"] == 1]
    assert page1[0]["y0"] == 0 and page1[-1]["y1"] == 9000
    assert all(a["y1"] == b["y0"] for a, b in zip(page1, page1[1:]))        # a shared edge: no gap
    assert all(p["width"] > 0 and p["y1"] > p["y0"] for p in pieces)


def test_a_book_of_tall_pages_is_a_strip_and_ordinary_pages_are_not():
    assert reader.suggest_layout([(718, 3059)] * 12) == "strip"             # the Mihon webtoon pieces
    assert reader.suggest_layout([(800, 1200)] * 12) == "paged"
    assert reader.suggest_layout([(800, 1200)] * 3 + [(700, 5000)] * 2) == "paged"   # one odd page does not decide
    assert reader.suggest_layout([]) == "paged"
    assert reader.suggest_layout([(0, 0)]) == "paged"


def test_comicinfo_decides_the_direction():
    assert reader.suggest_direction("YesAndRightToLeft") == "rtl"
    assert reader.suggest_direction(" yesandrighttoleft ") == "rtl"
    for value in ("Yes", "No", "", None, "Unknown"):
        assert reader.suggest_direction(value) == "ltr"


# ---- a comic ------------------------------------------------------------------------------------

def test_a_comic_lists_its_pages_in_natural_order_with_their_sizes(tmp_path):
    comic = book(tmp_path, [("page10.png", picture(300, 450)), ("page2.png", picture(200, 300)),
                            ("page1.png", picture(100, 150))])
    assert comic.refs == ["page1.png", "page2.png", "page10.png"]
    assert comic.scan_sizes() == [(100, 150), (200, 300), (300, 450)]
    assert comic.kind == "comic"
    comic.close()


def test_pages_are_drawn_at_the_width_asked_and_never_enlarged(tmp_path):
    comic = book(tmp_path, [("1.png", picture(400, 600))])
    comic.scan_sizes()
    page = comic.render(0, 200)
    assert (page.width(), page.height()) == (200, 300)
    page = comic.render(0, 4000)
    assert (page.width(), page.height()) == (400, 600)                      # a bigger request does not enlarge it
    assert comic.render(5, 200).isNull() and comic.render(-1, 200).isNull()


def test_a_tall_page_is_cut_into_chunks_of_the_right_width_and_total_height(tmp_path):
    comic = book(tmp_path, [("1.png", gradient(700, 12000))])
    comic.scan_sizes()
    for width, total in ((700, 12000), (350, 6000)):
        chunks = [comic.render(0, width, k) for k in range(3)]
        assert all(not c.isNull() and c.width() == width for c in chunks)
        assert sum(c.height() for c in chunks) == total                    # no row lost or repeated
        assert max(c.height() for c in chunks) <= reader.MAX_CHUNK


def test_chunks_meet_exactly_with_no_seam(tmp_path):
    """Draw the page once as a whole (cuts disabled) and once cut: the rows are identical."""
    tall = gradient(700, 9000)
    path = cbz(tmp_path / "t.cbz", [("1.png", tall)])
    cut = reader.open_book(path)
    cut.scan_sizes()
    cut_rows = [r for k in range(3) for r in rows(cut.render(0, 700, k))]
    cut.close()
    original = reader.MAX_CHUNK
    reader.MAX_CHUNK = 10 ** 9
    try:
        whole = reader.open_book(path)
        whole.scan_sizes()
        whole_rows = rows(whole.render(0, 700, 0))
        whole.close()
    finally:
        reader.MAX_CHUNK = original
    assert cut_rows == whole_rows
    # and neighbouring rows across the two cut lines change smoothly (no jump from a missing or repeated row)
    for boundary in (3000, 6000):
        a, b = QColor(cut_rows[boundary - 1]), QColor(cut_rows[boundary])
        assert abs(a.red() - b.red()) <= 2 and abs(a.green() - b.green()) <= 2


def test_a_scaled_tall_page_still_stacks_exactly(tmp_path):
    tall = gradient(800, 10000)
    path = cbz(tmp_path / "t.cbz", [("1.png", tall)])
    cut = reader.open_book(path)
    cut.scan_sizes()
    chunks = [cut.render(0, 400, k) for k in range(len(reader.chunk_boundaries(10000)) - 1)]
    assert sum(c.height() for c in chunks) == 5000                          # 10000 rows at half width
    assert all(c.width() == 400 for c in chunks)
    cut.close()


def test_a_chunk_that_does_not_exist_is_null(tmp_path):
    comic = book(tmp_path, [("1.png", gradient(500, 9000))])
    comic.scan_sizes()
    assert comic.render(0, 500, 3).isNull() and comic.render(0, 500, -1).isNull()
    assert not comic.render(0, 500, 2).isNull()


def test_a_broken_page_gets_a_placeholder_shape_and_a_null_render(tmp_path):
    path = tmp_path / "b.cbz"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("1.png", png(picture(200, 300)))
        z.writestr("2.png", b"not a picture")
    comic = reader.open_book(str(path))
    assert comic.scan_sizes() == [(200, 300), (1000, 1500)]
    assert not comic.render(0, 100).isNull() and comic.render(1, 100).isNull()


def test_comicinfo_manga_flag_is_read(tmp_path):
    info = '<ComicInfo><Title>x</Title><Manga>YesAndRightToLeft</Manga></ComicInfo>'
    path = tmp_path / "m.cbz"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("1.png", png(picture(100, 150)))
        z.writestr("ComicInfo.xml", info)
    assert reader.open_book(str(path)).manga == "YesAndRightToLeft"
    assert book(tmp_path, [("1.png", picture(50, 80))], name="plain.cbz").manga == ""


def test_what_cannot_be_read_raises_a_readable_error(tmp_path):
    (tmp_path / "junk.cbz").write_bytes(b"not an archive")
    with pytest.raises(ReaderError, match="not a comic archive"):
        reader.open_book(str(tmp_path / "junk.cbz"))
    empty = tmp_path / "empty.cbz"
    zipfile.ZipFile(empty, "w").close()
    with pytest.raises(ReaderError, match="no pictures"):
        reader.open_book(str(empty))
    (tmp_path / "x.mobi").write_bytes(b"x")
    with pytest.raises(ReaderError, match="does not open"):
        reader.open_book(str(tmp_path / "x.mobi"))
    assert reader.is_readable("a.CBZ") and reader.is_readable("b.pdf") and reader.is_readable("c.epub")
    assert not reader.is_readable("d.mobi") and not reader.is_readable("e.png")


# ---- EPUB and PDF ------------------------------------------------------------------------------------

def comic_epub(tmp_path, pages, name="c.epub"):
    """An EPUB whose pages are single pictures, in the given spine order."""
    items, spine, files = [], [], {}
    for i, (doc, image) in enumerate(pages):
        items.append(f'<item id="d{i}" href="{doc}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="d{i}"/>')
        files["OEBPS/" + doc] = f'<html><body><div><img src="images/{image}"/></div></body></html>'
    opf = ('<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata/>'
           f'<manifest>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>')
    with zipfile.ZipFile(tmp_path / name, "w") as z:
        z.writestr("META-INF/container.xml",
                   '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        for name_, html in files.items():
            z.writestr(name_, html)
        for _doc, image in pages:
            z.writestr("OEBPS/images/" + image, png(picture(200, 300, color="#1e4fd0")))
    return str(tmp_path / name)


def test_an_image_epub_is_read_in_spine_order(tmp_path):
    path = comic_epub(tmp_path, [("p3.xhtml", "c.png"), ("p1.xhtml", "a.png"), ("p2.xhtml", "b.png")])
    book_ = reader.open_book(path)
    assert [os.path.basename(r) for r in book_.refs] == ["c.png", "a.png", "b.png"]     # the spine, not the file names
    assert book_.kind == "epub" and book_.scan_sizes() == [(200, 300)] * 3
    assert not book_.render(0, 100).isNull()
    book_.close()


def test_a_text_epub_is_refused_with_a_hint(tmp_path):
    text = "word " * 400
    items = "".join(f'<item id="d{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(5))
    spine = "".join(f'<itemref idref="d{i}"/>' for i in range(5))
    path = tmp_path / "novel.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml",
                   '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", f'<package xmlns="http://www.idpf.org/2007/opf"><manifest>{items}</manifest><spine>{spine}</spine></package>')
        for i in range(5):
            z.writestr(f"OEBPS/c{i}.xhtml", f"<html><body><p>{text}</p><img src='x.png'/></body></html>")
    with pytest.raises(ReaderError, match="system app"):
        reader.open_book(str(path))
    broken = tmp_path / "broken.epub"
    broken.write_bytes(b"not a zip")
    with pytest.raises(ReaderError, match="could not be read"):
        reader.open_book(str(broken))
    # the app decides before opening: text and broken files go to the system app without a question
    assert reader.is_image_epub(str(path)) is False and reader.is_image_epub(str(broken)) is False
    assert reader.is_image_epub(str(tmp_path / "missing.epub")) is False


def test_the_comic_epub_test():
    assert reader.is_comic_epub([("a", 10), ("b", 0), ("c", 40), ("d", 5)])
    assert not reader.is_comic_epub([("a", 10), ("b", 0)])                    # too few pages
    assert not reader.is_comic_epub([(None, 900), (None, 900), ("x", 5), (None, 700)])
    assert not reader.is_comic_epub([("a", 900), ("b", 800), ("c", 700), ("d", 600)])   # pictures, but mostly text


def test_a_pdf_is_read_page_by_page(tmp_path):
    from PySide6.QtGui import QPageSize, QPdfWriter
    path = tmp_path / "p.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    for i in range(3):
        painter.fillRect(500, 500, 3000 + i * 500, 3000, QColor("blue"))
        if i < 2:
            writer.newPage()
    painter.end()
    pdf = reader.open_book(str(path))
    assert pdf.kind == "pdf" and pdf.refs == ["0", "1", "2"]
    width, height = pdf.sizes[0]
    assert 0.7 < width / height < 0.72                                      # A4 portrait
    page = pdf.render(1, 300)
    assert page.width() == 300 and 420 <= page.height() <= 430
    assert pdf.render(7, 300).isNull() and pdf.render(0, 300, 1).isNull()
    pdf.close()
    (tmp_path / "junk.pdf").write_bytes(b"%PDF-1.4 nothing")
    with pytest.raises(ReaderError):
        reader.open_book(str(tmp_path / "junk.pdf"))


# ---- series and remembered settings -------------------------------------------------------------------

def test_a_chapter_of_a_series_knows_its_neighbours(tmp_path, qapp):
    from tetia.models import series
    folder = tmp_path / "Title"
    folder.mkdir()
    paths = []
    for name in ("Vol.1 Ch.2.cbz", "Vol.1 Ch.10.cbz", "Vol.1 Ch.1.cbz"):
        paths.append(cbz(folder / name, [("1.png", picture(50, 80))]))
    db = get_database()
    assert reader.series_context(db, paths[0]) is None                       # not a series yet
    series.set_series(db, str(folder), True)
    context = reader.series_context(db, paths[0])
    assert [os.path.basename(c) for c in context["chapters"]] == ["Vol.1 Ch.1.cbz", "Vol.1 Ch.2.cbz", "Vol.1 Ch.10.cbz"]
    assert reader.series_context(db, str(folder / "other.cbz")) is None      # not one of its chapters


def test_settings_are_remembered_per_series_or_per_book(tmp_path):
    assert reader.settings_scope({"folder": "/a/Title", "chapters": []}, 5, "/a/Title/x.cbz") == "series:/a/Title"
    assert reader.settings_scope(None, 5, "/a/x.cbz") == "media:5"
    assert reader.settings_scope(None, None, "/a/x.cbz") == "path:/a/x.cbz"
    db = get_database()
    assert reader.load_settings(db, "series:/a") == {}
    reader.save_settings(db, "series:/a", {"layout": "strip", "direction": "ltr", "fit": "width", "junk": 1})
    assert reader.load_settings(db, "series:/a") == {"layout": "strip", "direction": "ltr", "fit": "width"}
    reader.save_settings(db, "series:/a", {"layout": "paged"})
    assert reader.load_settings(db, "series:/a") == {"layout": "paged"}
    db.set_setting("reader:series:/b", '{"layout": "sideways", "fit": "height"}')      # a hand-edited bad value is ignored
    assert reader.load_settings(db, "series:/b") == {"fit": "height"}
    db.set_setting("reader:series:/c", "not json")
    assert reader.load_settings(db, "series:/c") == {}
    reader.forget_settings(db, "series:/a")
    assert reader.load_settings(db, "series:/a") == {}


# ---- progress and bookmarks in the database ---------------------------------------------------------------

def media(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"x")
    db = get_database()
    media_id = db.upsert_media(str(path), name, "comic", 1, 1, "h" + name)[0]
    db.conn.commit()
    return media_id


def test_progress_is_stored_and_finished_sticks(tmp_path):
    db, mid = get_database(), media(tmp_path, "a.cbz")
    assert db.get_progress(mid) is None
    db.set_progress(mid, 5, 0.25, 30, False)
    assert db.get_progress(mid) == {"page": 5, "offset": 0.25, "total": 30, "finished": False}
    db.set_progress(mid, 29, 0.9, 30, True)
    db.set_progress(mid, 2, 0.0, 30, False)                                  # read again from the start
    assert db.get_progress(mid) == {"page": 2, "offset": 0.0, "total": 30, "finished": True}
    other = media(tmp_path, "b.cbz")
    db.set_progress(other, 1, 0, 10, False)
    many = db.get_progress_many([mid, other, 9999])
    assert set(many) == {mid, other} and many[other]["page"] == 1
    db.clear_progress(mid)
    assert db.get_progress(mid) is None


def test_bookmarks_are_per_book_sorted_and_unique(tmp_path):
    db = get_database()
    a, b = media(tmp_path, "a.cbz"), media(tmp_path, "b.cbz")
    for page in (9, 3, 3, 14):
        db.add_bookmark(a, page)
    db.add_bookmark(b, 1)
    assert db.get_bookmarks(a) == [3, 9, 14] and db.get_bookmarks(b) == [1]
    db.remove_bookmark(a, 9)
    db.remove_bookmark(a, 77)
    assert db.get_bookmarks(a) == [3, 14]


def test_progress_and_bookmarks_go_with_a_trashed_file(tmp_path):
    db, mid = get_database(), media(tmp_path, "gone.cbz")
    db.set_progress(mid, 4, 0, 20, False)
    db.add_bookmark(mid, 4)
    db.delete_media([mid])
    db.conn.commit()
    assert db.get_progress(mid) is None and db.get_bookmarks(mid) == []
