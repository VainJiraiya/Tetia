# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tags read from the files themselves replace only earlier imported tags, never the user's; a rating,
description or format is only filled in where none was set."""
import os

from tetia.models import tagimport
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel
from tetia.models.tagimport import Imported


def _file(tmp_path, name="a.cbz"):
    (tmp_path / name).write_bytes(b"x")
    MediaModel().load_from_qurl(str(tmp_path))
    return get_database().get_media_by_path(os.path.realpath(str(tmp_path / name)))[0]


def _tags(db, media_id):
    return {(r[0], r[1]) for r in db.conn.execute(
        "SELECT t.name, mt.source FROM media_tag mt JOIN tag t ON t.id = mt.tag_id WHERE mt.media_id = ?", (media_id,))}


def test_an_import_replaces_only_imported_tags(tmp_path, qapp):
    db = get_database()
    media_id = _file(tmp_path)
    db.insert_media_tags([media_id], db.get_or_create_tag("my_pick", "content"))          # the user's own
    tagimport.apply_to_file(db, media_id, Imported(tags=[("creator", "Some Artist"), ("genre", "Action")], rating=2))
    assert _tags(db, media_id) == {("my_pick", "manual"), ("some_artist", "import"), ("action", "import")}
    assert db.conn.execute("SELECT rating FROM media WHERE id = ?", (media_id,)).fetchone()[0] == 2
    tagimport.apply_to_file(db, media_id, Imported(tags=[("genre", "Drama")], rating=0))  # the file changed
    assert _tags(db, media_id) == {("my_pick", "manual"), ("drama", "import")}
    assert db.conn.execute("SELECT rating FROM media WHERE id = ?", (media_id,)).fetchone()[0] == 2  # kept
    assert db.resolve_tag_id("some_artist") is None                                      # left unused: gone


def test_a_tag_given_by_hand_after_an_import_is_kept(tmp_path, qapp):
    db = get_database()
    media_id = _file(tmp_path)
    tagimport.apply_to_file(db, media_id, Imported(tags=[("character", "Frieren")]))
    db.insert_media_tags([media_id], db.resolve_tag_id("frieren"))                       # the user agrees: theirs
    assert _tags(db, media_id) == {("frieren", "manual")}
    tagimport.forget_file(db, media_id)
    assert _tags(db, media_id) == {("frieren", "manual")}


def test_a_series_gets_its_tags_and_only_empty_details(tmp_path, qapp):
    db = get_database()
    folder = str(tmp_path / "Frieren")
    db.set_collection_series(folder, True)
    db.set_collection_description(folder, "Mine")
    tagimport.apply_to_series(db, folder, Imported(tags=[("series", "Sousou no Frieren"), ("genre", "Fantasy")],
                                                   rating=0, description="From the file", format="manga"))
    rows = {(r[0], r[1]) for r in db.conn.execute(
        "SELECT t.name, ft.source FROM folder_tag ft JOIN tag t ON t.id = ft.tag_id WHERE ft.folder = ?", (folder,))}
    assert rows == {("sousou_no_frieren", "import"), ("fantasy", "import")}
    meta = db.get_collection_meta(folder)
    assert (meta["rating"], meta["description"], meta["format"]) == (0, "Mine", "manga")
    db.insert_folder_tags([folder], db.resolve_tag_id("fantasy"))                         # the user's now
    tagimport.apply_to_series(db, folder, Imported())
    rows = {r[0] for r in db.conn.execute("SELECT source FROM folder_tag WHERE folder = ?", (folder,))}
    assert rows == {"manual"}


def test_what_all_chapters_share_belongs_to_the_series():
    one = Imported(tags=[("series", "x"), ("character", "a")], rating=1, format="manga")
    two = Imported(tags=[("series", "x"), ("character", "b")], rating=1, format="manga", description="d")
    common = tagimport.shared([one, two])
    assert common.tags == [("series", "x")] and common.rating == 1 and common.format == "manga"
    assert common.description == ""                                                      # they disagree
    assert not tagimport.shared([])


def test_names_that_cannot_be_tags_are_skipped(tmp_path, qapp):
    db = get_database()
    media_id = _file(tmp_path)
    tagimport.apply_to_file(db, media_id, Imported(tags=[("genre", "   "), ("nonsense", "x"), ("genre", "ok")]))
    assert _tags(db, media_id) == {("ok", "import")}
