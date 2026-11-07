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
