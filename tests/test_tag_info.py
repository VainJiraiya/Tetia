# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a tag page says about its tag: other names, what it implies, what implies it."""
from tetia.models.database import get_database
from tetia.models.tagModel import TagModel


def test_a_tag_page_knows_aliases_and_implications(qapp):
    db = get_database()
    frieren = db.get_or_create_tag("frieren", "character")
    series = db.get_or_create_tag("sousou_no_frieren", "series")
    fern = db.get_or_create_tag("fern", "character")
    db.conn.execute("INSERT INTO tag_alias (alias, tag_id) VALUES ('frieren_(sousou_no_frieren)', ?)", (frieren,))
    db.conn.executemany("INSERT INTO tag_implication (antecedent_id, consequent_id) VALUES (?, ?)",
                        [(frieren, series), (fern, series)])
    db.conn.commit()
    info = TagModel().tagInfo("frieren")
    assert info["category"] == "character"
    assert info["aliases"] == ["frieren_(sousou_no_frieren)"]
    assert info["implies"] == [{"category": "series", "name": "sousou_no_frieren"}]
    assert TagModel().tagInfo("sousou_no_frieren")["implied_by"] == [
        {"category": "character", "name": "fern"}, {"category": "character", "name": "frieren"}]
    assert TagModel().tagInfo("nobody") == {}


def test_browsing_a_tab_counts_what_is_inside_its_folder_tiles(tmp_path, qapp):
    """A tab's top level shows folders; their files' tags are browsable too, and a series counts once."""
    import os
    from tetia.models import covers
    from tetia.models.database import get_database
    from tetia.models.mediaModel import MediaModel
    from tetia.models.subfolderModel import SubfolderModel
    from tetia.models.tagModel import TagModel
    lib = tmp_path / "Manga"
    for folder, names in (("Plain manga", ["1.cbz", "2.cbz"]), ("A series", ["Ch.1.cbz", "Ch.2.cbz"])):
        (lib / folder).mkdir(parents=True)
        for name in names:
            (lib / folder / name).write_bytes(b"x")
        MediaModel().load_from_qurl(str(lib / folder))
    db = get_database()
    plain = [db.get_media_by_path(os.path.realpath(str(lib / "Plain manga" / n)))[0] for n in ("1.cbz", "2.cbz")]
    db.insert_media_tags(plain, db.get_or_create_tag("inside_a_folder", "genre"))
    chapters = [db.get_media_by_path(os.path.realpath(str(lib / "A series" / n)))[0] for n in ("Ch.1.cbz", "Ch.2.cbz")]
    db.insert_media_tags(chapters, db.get_or_create_tag("on_chapters", "content"))
    subs = SubfolderModel()
    subs.filterMode = int(MediaModel.FilterMode.MangaOnly)
    subs.setSeries(covers.folder_uri(str(lib / "A series")), True)
    db.insert_folder_tags([os.path.realpath(str(lib / "A series"))], db.get_or_create_tag("the_series", "series"))
    subs.loadSources([str(lib)], [])
    scope = subs.browseScope()
    assert sorted(scope["ids"]) == sorted(plain)                       # the series' chapters are the series
    assert scope["series"] == [covers.folder_uri(str(lib / "A series"))]
    names = {t["name"]: t["count"] for g in TagModel().browse(scope["ids"], scope["series"]) for t in g["tags"]}
    assert names["inside_a_folder"] == 2 and "the_series" in names
    subs.loadSeries([str(lib / "A series")])                           # search results: they count what they show
    assert subs.browseScope() == {}
