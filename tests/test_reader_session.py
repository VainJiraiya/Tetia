# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import zipfile

import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSize

from tetia.models import covers, reader, readerSession, series
from tetia.models.database import get_database
from tetia.models.readerSession import ReaderPageProvider, ReaderSession
from test_bookcovers import cbz, picture, png
from test_reader import comic_epub, gradient


def wait(session, timeout=15000):
    """Let the worker thread finish: spin the event loop until the session is no longer loading."""
    timer = QElapsedTimer()
    timer.start()
    while session.loading and timer.elapsed() < timeout:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents()
    assert not session.loading, "the book never finished opening"


def opened(path, qapp):
    session = ReaderSession()
    session.load(str(path))
    wait(session)
    return session


def in_library(path, kind="comic"):
    info = os.stat(path)
    db = get_database()
    media_id = db.upsert_media(str(path), os.path.basename(path), kind, info.st_size, int(info.st_mtime), "h" + os.path.basename(path))[0]
    db.conn.commit()
    return media_id


def ten_pages(tmp_path, name="book.cbz", **kwargs):
    return cbz(tmp_path / name, [(f"{i:02d}.png", picture(300, 450, color="#1e4fd0")) for i in range(10)])


# ---- opening --------------------------------------------------------------------------------

def test_a_book_opens_off_the_ui_thread_and_reports_its_pages(tmp_path, qapp):
    session = ReaderSession()
    path = ten_pages(tmp_path)
    session.load(path)
    assert session.loading and not session.ready                         # returns at once
    wait(session)
    assert session.ready and session.error == "" and session.pageCount == 10
    assert session.title == "book" and session.kind == "comic" and session.token
    assert session.pageSize(0) == [300, 450] and session.pageSize(99) == [0, 0]
    assert len(session.pieces) == 10 and session.pieces[3] == {"page": 3, "chunk": 0, "width": 300, "y0": 0, "y1": 450}
    assert session.firstPiece(4) == 4
    session.close()
    assert not session.ready and session.pageCount == 0


def test_a_file_address_works_as_well_as_a_path(tmp_path, qapp):
    path = ten_pages(tmp_path)
    assert opened(covers.folder_uri(path), qapp).pageCount == 10


def test_a_book_that_cannot_be_opened_says_why(tmp_path, qapp):
    bad = tmp_path / "bad.cbz"
    bad.write_bytes(b"not an archive")
    session = opened(bad, qapp)
    assert not session.ready and "not a comic archive" in session.error
    text = tmp_path / "x.mobi"
    text.write_bytes(b"x")
    assert "does not open" in opened(text, qapp).error


def test_loading_another_book_makes_the_first_one_stale(tmp_path, qapp):
    first = cbz(tmp_path / "a.cbz", [("1.png", picture(100, 150)), ("2.png", picture(100, 150))])
    second = ten_pages(tmp_path, "b.cbz")
    session = ReaderSession()
    session.load(first)
    session.load(second)                                                  # before the first finished
    wait(session)
    assert session.title == "b" and session.pageCount == 10


def test_closing_while_loading_does_not_leave_a_book_open(tmp_path, qapp):
    session = ReaderSession()
    session.load(ten_pages(tmp_path))
    session.close()
    timer = QElapsedTimer(); timer.start()
    while timer.elapsed() < 600:
        QCoreApplication.processEvents()
    assert not session.ready and session.token == ""


# ---- layout, direction, fit and what is remembered ----------------------------------------------------

def test_the_defaults_come_from_the_pages_and_comicinfo(tmp_path, qapp):
    plain = opened(ten_pages(tmp_path), qapp)
    assert (plain.layout, plain.direction, plain.fit) == ("paged", "ltr", "height")
    path = tmp_path / "manga.cbz"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("1.png", png(picture(300, 450)))
        z.writestr("ComicInfo.xml", "<ComicInfo><Manga>YesAndRightToLeft</Manga></ComicInfo>")
    assert opened(path, qapp).direction == "rtl"
    webtoon = cbz(tmp_path / "web.cbz", [(f"{i:02d}.png", gradient(718, 3059)) for i in range(4)])
    strip = opened(webtoon, qapp)
    assert (strip.layout, strip.fit) == ("strip", "width")
    assert len(strip.pieces) == 4 and all(p["chunk"] == 0 for p in strip.pieces)     # the 3059 px pieces stay whole


def test_an_unsegmented_tall_image_is_cut_into_chunks(tmp_path, qapp):
    path = cbz(tmp_path / "long.cbz", [("1.png", gradient(700, 9000)), ("2.png", gradient(700, 800))])
    session = opened(path, qapp)
    page0 = [p for p in session.pieces if p["page"] == 0]
    assert len(page0) == 3 and page0[0]["y0"] == 0 and page0[-1]["y1"] == 9000
    assert [p["page"] for p in session.pieces] == [0, 0, 0, 1]
    assert [c["chunk"] for c in session.chunksOf(0)] == [0, 1, 2] and len(session.chunksOf(1)) == 1


def test_choices_are_remembered_for_the_book_and_can_be_forgotten(tmp_path, qapp):
    path = ten_pages(tmp_path)
    in_library(path)
    first = opened(path, qapp)
    first.layout, first.direction, first.fit = "strip", "rtl", "width"
    first.layout = "sideways"                                             # not a layout: ignored
    assert (first.layout, first.direction, first.fit) == ("strip", "rtl", "width")
    first.close()
    again = opened(path, qapp)
    assert (again.layout, again.direction, again.fit) == ("strip", "rtl", "width")
    again.remember = False                                                # forget: the defaults come back next time
    again.close()
    assert opened(path, qapp).layout == "paged"
    third = opened(path, qapp)
    third.remember = False
    third.layout = "strip"                                                # not remembered while switched off
    third.close()
    assert opened(path, qapp).layout == "paged"


def test_a_series_shares_its_choices_between_chapters(tmp_path, qapp):
    folder = tmp_path / "Title"
    folder.mkdir()
    chapters = [cbz(folder / f"Vol.1 Ch.{i}.cbz", [("1.png", picture(100, 150)), ("2.png", picture(100, 150))]) for i in (1, 2)]
    for c in chapters:
        in_library(c)
    series.set_series(get_database(), str(folder), True)
    first = opened(chapters[0], qapp)
    first.direction = "rtl"
    first.close()
    assert opened(chapters[1], qapp).direction == "rtl"                     # another chapter, same series


# ---- progress and bookmarks ---------------------------------------------------------------------------------

def test_the_place_is_remembered_and_a_finished_book_starts_over(tmp_path, qapp):
    path = ten_pages(tmp_path)
    in_library(path)
    session = opened(path, qapp)
    assert (session.startPage, session.startOffset) == (0, 0.0)
    session.savePosition(6, 0.4, False)
    session.close()
    again = opened(path, qapp)
    assert again.startPage == 6 and abs(again.startOffset - 0.4) < 1e-9
    again.savePosition(99, 5.0, True)                                       # out-of-range values are clamped
    again.close()
    last = opened(path, qapp)
    assert (last.startPage, last.startOffset) == (0, 0.0)                   # a finished book starts over...
    assert get_database().get_progress(in_library(path))["finished"] is True    # ...and still counts as read
    last.savePosition(4, 0.0, False)                                        # reading it again does not unfinish it
    assert get_database().get_progress(in_library(path))["finished"] is True


def test_a_book_outside_the_library_still_opens_without_a_memory(tmp_path, qapp):
    path = ten_pages(tmp_path)                                              # never added to the library
    session = opened(path, qapp)
    session.savePosition(3, 0.2, False)
    session.toggleBookmark(2)                                               # silently nothing
    assert session.bookmarks == [] and session.ready
    session.close()
    assert opened(path, qapp).startPage == 0


def test_bookmarks_are_starred_and_unstarred_per_page(tmp_path, qapp):
    path = ten_pages(tmp_path)
    in_library(path)
    session = opened(path, qapp)
    changes = []
    session.bookmarksChanged.connect(lambda: changes.append(1))
    session.toggleBookmark(4)
    session.toggleBookmark(1)
    assert session.bookmarks == [1, 4] and session.isBookmarked(4) and not session.isBookmarked(2)
    session.toggleBookmark(4)
    assert session.bookmarks == [1] and len(changes) == 3
    session.toggleBookmark(50)                                              # no such page
    session.toggleBookmark(-1)
    assert session.bookmarks == [1]
    session.close()
    assert opened(path, qapp).bookmarks == [1]


# ---- series --------------------------------------------------------------------------------------------------

def test_a_chapter_knows_the_chapters_around_it_and_who_has_been_read(tmp_path, qapp):
    folder = tmp_path / "Title"
    folder.mkdir()
    chapters = [cbz(folder / f"Vol.1 Ch.{i}.cbz", [("1.png", picture(100, 150)), ("2.png", picture(100, 150))]) for i in (1, 2, 3, 10)]
    ids = [in_library(c) for c in chapters]
    db = get_database()
    series.set_series(db, str(folder), True)
    db.set_progress(ids[0], 1, 1.0, 2, True)                                # Ch.1 is read
    db.set_progress(ids[2], 1, 0.3, 2, False)                               # Ch.3 was started
    session = opened(chapters[1], qapp)                                     # open Ch.2
    assert os.path.basename(session.previousPath) == "Vol.1 Ch.1.cbz" and session.nextName == "Vol.1 Ch.3"
    states = {c["name"]: c["state"] for c in session.chapters}
    assert states == {"Vol.1 Ch.1": "read", "Vol.1 Ch.2": "current", "Vol.1 Ch.3": "reading", "Vol.1 Ch.10": "unread"}
    assert [c["name"] for c in session.chapters][-1] == "Vol.1 Ch.10"      # chapter order, not alphabetical
    assert db.get_collection_meta(str(folder))["last_read"] == chapters[1]   # the series tile resumes here
    session.savePosition(1, 1.0, True)                                      # reaching the end marks it read
    assert {c["name"]: c["state"] for c in session.chapters}["Vol.1 Ch.2"] == "read"
    assert opened(chapters[3], qapp).nextPath == ""                         # nothing after the last chapter
    assert opened(chapters[0], qapp).previousPath == ""


def test_resume_skips_chapters_that_are_finished(tmp_path, qapp):
    folder = tmp_path / "Title"
    folder.mkdir()
    chapters = [cbz(folder / f"Vol.1 Ch.{i}.cbz", [("1.png", picture(100, 150)), ("2.png", picture(100, 150))]) for i in (1, 2, 3)]
    ids = [in_library(c) for c in chapters]
    db = get_database()
    series.set_series(db, str(folder), True)
    db.set_collection_last_read(str(folder), chapters[0])
    assert series.skip_finished(db, str(folder), chapters[0]) == chapters[0]           # nothing read: stay
    db.set_progress(ids[0], 1, 1.0, 2, True)
    assert series.skip_finished(db, str(folder), chapters[0]) == chapters[1]           # Ch.1 is done: on to Ch.2
    db.set_progress(ids[1], 0, 0.5, 2, False)                                          # Ch.2 is half read: stop there
    assert series.skip_finished(db, str(folder), chapters[0]) == chapters[1]
    db.set_progress(ids[1], 1, 1.0, 2, True)
    db.set_progress(ids[2], 1, 1.0, 2, True)
    assert series.skip_finished(db, str(folder), chapters[0]) == chapters[2]           # all read: the last stays put
    assert series.open_series(db, str(folder), "resume").endswith("Ch.3.cbz")
    assert series.open_series(db, str(folder), "first").endswith("Ch.1.cbz")           # asking for a chapter is not skipped


def test_a_book_can_be_opened_on_its_last_page(tmp_path, qapp):
    path = ten_pages(tmp_path)
    session = ReaderSession()
    session.loadFrom(str(path), True)
    wait(session)
    assert (session.startPage, session.startOffset) == (9, 1.0)
    session.close()
    assert opened(path, qapp).startPage == 0                                           # a plain load is unaffected


def test_can_read_sends_text_epubs_to_the_system_app(tmp_path, qapp):
    session = ReaderSession()
    assert session.canRead(str(ten_pages(tmp_path)))
    assert not session.canRead(str(tmp_path / "movie.mkv"))
    comic = comic_epub(tmp_path, [("a.xhtml", "1.png"), ("b.xhtml", "2.png"), ("c.xhtml", "3.png")])
    assert session.canRead(str(comic))
    novel = tmp_path / "novel.epub"
    novel.write_bytes(b"not a zip")
    assert not session.canRead(str(novel))                                  # unreadable: the system app can try


def test_a_plain_book_has_no_chapters(tmp_path, qapp):
    session = opened(ten_pages(tmp_path), qapp)
    assert session.chapters == [] and session.nextPath == "" and session.previousPath == ""


# ---- EPUB and PDF ---------------------------------------------------------------------------------------------

def test_an_image_epub_opens_and_a_text_epub_says_so(tmp_path, qapp):
    good = comic_epub(tmp_path, [("a.xhtml", "1.png"), ("b.xhtml", "2.png"), ("c.xhtml", "3.png")])
    session = opened(good, qapp)
    assert session.ready and session.kind == "epub" and session.pageCount == 3
    junk = tmp_path / "bad.epub"
    junk.write_bytes(b"not a zip")
    assert "could not be read" in opened(junk, qapp).error


# ---- the provider -----------------------------------------------------------------------------------------------

def test_the_provider_draws_pages_and_chunks_by_token(tmp_path, qapp):
    path = cbz(tmp_path / "long.cbz", [("1.png", picture(400, 600)), ("2.png", gradient(700, 9000))])
    session = opened(path, qapp)
    provider = ReaderPageProvider()
    size = QSize()
    # a width is asked for with sourceSize (Qt's last argument) and rounded up to a step (600 here); never enlarged
    page = provider.requestImage(f"{session.token}/0/0", size, QSize(200, 0))
    assert (page.width(), page.height()) == (400, 600) and size.width() == 400      # the 400 px source, as it is
    chunks = [provider.requestImage(f"{session.token}/1/{k}", QSize(), QSize(350, 0)) for k in range(3)]
    assert all(c.width() == 600 for c in chunks)                                    # 350 asked: the 600 step
    assert abs(sum(c.height() for c in chunks) - round(9000 * 600 / 700)) <= 3
    unbounded = provider.requestImage(f"{session.token}/0/0", QSize(), QSize())
    assert unbounded.width() == 400                                         # no width asked: not enlarged
    for bad in (f"{session.token}/9/0", f"{session.token}/0/5", "nope/0/0", f"{session.token}/x/0", f"{session.token}/0", ""):
        assert provider.requestImage(bad, QSize(), QSize(100, 0)).isNull(), bad
    token = session.token
    session.close()
    assert provider.requestImage(f"{token}/0/0", QSize(), QSize(100, 0)).isNull()    # closed: nothing is served


def test_a_pdf_opens_and_is_served_at_the_width_asked(tmp_path, qapp):
    from PySide6.QtGui import QColor, QPageSize, QPainter, QPdfWriter
    path = tmp_path / "p.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    painter.fillRect(500, 500, 3000, 3000, QColor("blue"))
    writer.newPage()
    painter.fillRect(500, 500, 2000, 2000, QColor("red"))
    painter.end()
    session = opened(path, qapp)
    assert session.ready and session.kind == "pdf" and session.pageCount == 2
    page = ReaderPageProvider().requestImage(f"{session.token}/1/0", QSize(), QSize(300, 0))
    assert page.width() == 600 and 845 <= page.height() <= 852                      # 300 asked: the 600 step, A4 shaped
