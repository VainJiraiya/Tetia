# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tags from the metadata gallery-dl writes beside a download, in the shapes its sites give."""
import json
import os

from PySide6.QtGui import QColor, QImage

from tetia.models import gallerydl
from tetia.models.database import get_database
from tetia.models.scanner import fingerprint, scan_folder


def test_danbooru():
    found = gallerydl.parse({"category": "danbooru", "tag_string_artist": "some_artist",
                             "tag_string_character": "frieren fern", "tag_string_copyright": "sousou_no_frieren",
                             "tag_string_general": "1girl elf", "tag_string_meta": "highres", "rating": "s"})
    assert ("creator", "some_artist") in found.tags and ("character", "fern") in found.tags
    assert ("series", "sousou_no_frieren") in found.tags and ("content", "elf") in found.tags
    assert all(name != "highres" for _, name in found.tags)               # meta tags say nothing of the picture
    assert found.rating == 1                                                # Danbooru's s: sensitive


def test_e621_and_other_boorus():
    found = gallerydl.parse({"category": "e621", "rating": "s",
                             "tags": {"artist": ["an_artist"], "character": ["a_character"], "general": ["solo"],
                                      "species": ["fox"], "meta": ["hi_res"]}})
    assert set(found.tags) == {("creator", "an_artist"), ("character", "a_character"), ("content", "solo"),
                               ("content", "fox")}
    assert found.rating == 0                                                # e621's s: safe
    gelbooru = gallerydl.parse({"category": "gelbooru", "tags": "a b c", "tags_artist": "x", "tags_general": "a b c",
                                "rating": "explicit"})
    assert ("creator", "x") in gelbooru.tags and gelbooru.rating == 3
    assert len([t for t in gelbooru.tags if t[1] == "a"]) == 1


def test_ehentai_pixiv_twitter_and_a_plain_list():
    eh = gallerydl.parse({"category": "exhentai", "tags": ["artist:someone", "parody:a_show", "character:hero",
                                                           "female:glasses", "language:english", "other:full color"]})
    assert set(eh.tags) == {("creator", "someone"), ("series", "a_show"), ("character", "hero"),
                            ("content", "glasses"), ("content", "full color")}
    pixiv = gallerydl.parse({"category": "pixiv", "user": {"name": "Painter", "account": "p1"}, "tags": ["landscape"],
                             "x_restrict": 1})
    assert ("creator", "Painter") in pixiv.tags and ("content", "landscape") in pixiv.tags and pixiv.rating == 3
    tweet = gallerydl.parse({"category": "twitter", "author": {"name": "someuser", "nick": "Some User"},
                             "hashtags": ["art", "fanart"]})
    assert set(tweet.tags) == {("creator", "someuser"), ("content", "art"), ("content", "fanart")}
    assert not gallerydl.parse({"category": "x"}) and not gallerydl.parse([1, 2])


def test_a_scan_reads_the_sidecars_of_new_files(tmp_path, qapp):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for name in ("one.png", "two.png", "three.png"):
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor("red"))
        image.save(str(folder / name))
    (folder / "one.png.json").write_text(json.dumps({"category": "danbooru", "tag_string_general": "sky",
                                                     "tag_string_artist": "painter", "rating": "g"}))
    (folder / "two.json").write_text(json.dumps({"category": "e621", "tags": {"general": ["clouds"]}}))
    db = get_database()
    scan_folder(db, folder, fingerprint)

    def tags(name):
        media_id = db.get_media_by_path(os.path.realpath(str(folder / name)))[0]
        return {r[0] for r in db.conn.execute(
            "SELECT t.name FROM media_tag mt JOIN tag t ON t.id = mt.tag_id WHERE mt.media_id = ?", (media_id,))}
    assert tags("one.png") == {"sky", "painter"} and tags("two.png") == {"clouds"} and tags("three.png") == set()
    assert db.conn.execute("SELECT rating FROM media WHERE name = 'one.png'").fetchone()[0] == 0
