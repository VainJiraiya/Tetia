# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tags from a comic's ComicInfo.xml: read when a comic is new or changed, and what every chapter says goes on
the series."""
import os
import zipfile

from PySide6.QtGui import QImage

from tetia.models import comicinfo, series
from tetia.models.database import get_database
from tetia.models.scanner import fingerprint, scan_folder
from test_bookcovers import png


def _info(**fields):
    body = "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())
    return f'<?xml version="1.0"?><ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{body}</ComicInfo>'


def _comic(path, info=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("001.png", png(QImage(20, 30, QImage.Format_RGB32)))
        if info is not None:
            z.writestr("ComicInfo.xml", info)
    return path


def _file_tags(db, path):
    media_id = db.get_media_by_path(os.path.realpath(str(path)))[0]
    return {(r[0], r[1]) for r in db.conn.execute(
        "SELECT c.name, t.name FROM media_tag mt JOIN tag t ON t.id = mt.tag_id JOIN tag_category c "
        "ON c.id = t.category_id WHERE mt.media_id = ? AND mt.source = 'import'", (media_id,))}


def _series_tags(db, folder):
    return {r[0] for r in db.conn.execute(
        "SELECT t.name FROM folder_tag ft JOIN tag t ON t.id = ft.tag_id WHERE ft.folder = ?",
        (os.path.realpath(str(folder)),))}


def test_what_a_comicinfo_says():
    found = comicinfo.parse(_info(Series="Sousou no Frieren", Writer="Kanehito Yamada", Penciller="Tsukasa Abe",
                                  Characters="Frieren, Fern", Genre="Fantasy, Adventure", Tags="elf",
                                  AgeRating="Teen", Summary="After the hero's party...", Manga="YesAndRightToLeft").encode())
    assert ("creator", "Kanehito Yamada") in found.tags and ("creator", "Tsukasa Abe") in found.tags
    assert ("series", "Sousou no Frieren") in found.tags
    assert ("character", "Fern") in found.tags and ("genre", "Adventure") in found.tags and ("content", "elf") in found.tags
    assert found.rating == 0 and found.format == "manga" and found.description.startswith("After")
    assert comicinfo.parse(_info(AgeRating="Adults Only 18+").encode()).rating == 3
    assert comicinfo.parse(_info(AgeRating="Rating Pending").encode()).rating is None
    assert comicinfo.parse(_info(Manga="Yes").encode()).format == ""                 # manga, but not right to left
    assert not comicinfo.parse(b"<NotComicInfo/>") and not comicinfo.parse(b"not xml")


def test_a_new_comic_gets_its_tags_and_a_comic_without_one_nothing(tmp_path, qapp):
    db = get_database()
    _comic(tmp_path / "Lib" / "one.cbz", _info(Writer="A Writer", Genre="Drama", AgeRating="Mature 17+"))
    _comic(tmp_path / "Lib" / "two.cbz")
    scan_folder(db, tmp_path / "Lib", fingerprint)
    assert _file_tags(db, tmp_path / "Lib" / "one.cbz") == {("creator", "a_writer"), ("genre", "drama")}
    assert _file_tags(db, tmp_path / "Lib" / "two.cbz") == set()
    rating = db.conn.execute("SELECT rating FROM media WHERE name = 'one.cbz'").fetchone()[0]
    assert rating == 2


def test_a_series_takes_what_all_its_chapters_say(tmp_path, qapp):
    db = get_database()
    folder = tmp_path / "Frieren"
    _comic(folder / "Ch.1.cbz", _info(Series="Frieren", Writer="Yamada", Characters="Frieren, Himmel"))
    _comic(folder / "Ch.2.cbz", _info(Series="Frieren", Writer="Yamada", Characters="Frieren, Fern"))
    scan_folder(db, folder, fingerprint)
    series.set_series(db, str(folder), True)
    assert _series_tags(db, folder) == {"frieren", "yamada"}                         # Himmel and Fern stay on chapters
    _comic(folder / "Ch.3.cbz", _info(Series="Frieren", Writer="Someone Else"))       # one new chapter alone
    scan_folder(db, folder, fingerprint)
    assert _series_tags(db, folder) == {"frieren"}                                     # all three agree on this only


def test_importing_can_be_turned_off(tmp_path, qapp):
    db = get_database()
    db.set_setting("import.tags", "off")
    _comic(tmp_path / "Lib" / "one.cbz", _info(Genre="Drama"))
    scan_folder(db, tmp_path / "Lib", fingerprint)
    assert _file_tags(db, tmp_path / "Lib" / "one.cbz") == set()
