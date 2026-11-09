# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Moving files into a private profile: the files and what goes with them land in its folder, their tags, favorite
and rating in its library, and nothing of them stays behind; a file that can't be copied safely stays put."""
import os

from PySide6.QtGui import QColor, QImage

from tetia.models import privatemove, scanner
from tetia.models.database import Database, get_database
from tetia.models.scanner import fingerprint, scan_folder


def _setup(tmp_path):
    here = tmp_path / "General"
    here.mkdir()
    for name in ("a.png", "b.png"):
        image = QImage(10, 6, QImage.Format_RGB32)
        image.fill(QColor("orange" if name == "a.png" else "purple"))
        image.save(str(here / name))
    (here / "a.png.json").write_text("{}")
    (here / "a.en.vtt").write_text("WEBVTT")
    general = get_database()
    scan_folder(general, here, fingerprint)
    a = general.get_media_by_path(os.path.realpath(str(here / "a.png")))[0]
    general.insert_media_tags([a], general.get_or_create_tag("secret_character", "character"))
    general.insert_media_tags([a], general.get_or_create_tag("shared_tag", "content"))
    b = general.get_media_by_path(os.path.realpath(str(here / "b.png")))[0]
    general.insert_media_tags([b], general.resolve_tag_id("shared_tag"))
    general.set_media_favorite(a, True)
    general.set_media_rating(a, 3)
    vault = tmp_path / "Vault" / "Private art"
    vault.mkdir(parents=True)
    (vault / "a.png").write_bytes(b"already here")                    # a name taken: the move picks another
    target = Database(tmp_path / "Vault" / "gallery.db")
    return here, vault, general, target, a, b


def test_a_file_moves_with_its_tags_and_leaves_nothing_behind(tmp_path, qapp):
    here, vault, general, target, a, b = _setup(tmp_path)
    forgotten = []
    result = privatemove.move(general, target, str(vault), [a], forget_thumbnails=forgotten.append)
    assert result == {"moved": [a], "failed": []}
    assert not (here / "a.png").exists() and not (here / "a.png.json").exists() and not (here / "a.en.vtt").exists()
    assert (vault / "a (2).png").exists() and (vault / "a (2).png.json").exists() and (vault / "a (2).en.vtt").exists()
    row = target.conn.execute("SELECT id, favorite, rating, width FROM media WHERE name = 'a (2).png'").fetchone()
    assert (row["favorite"], row["rating"], row["width"]) == (1, 3, 10)
    tags = {(r[0], r[1]) for r in target.conn.execute(
        "SELECT c.name, t.name FROM media_tag mt JOIN tag t ON t.id = mt.tag_id JOIN tag_category c "
        "ON c.id = t.category_id WHERE mt.media_id = ?", (row["id"],))}
    assert tags == {("character", "secret_character"), ("content", "shared_tag")}
    assert general.conn.execute("SELECT COUNT(*) FROM media WHERE id = ?", (a,)).fetchone()[0] == 0
    assert general.resolve_tag_id("secret_character") is None                     # only it had that tag: gone
    assert general.resolve_tag_id("shared_tag") is not None                        # b still has this one
    assert forgotten == [os.path.realpath(str(here / "a.png"))]
    assert (here / "b.png").exists()


def test_a_file_that_cannot_be_copied_safely_stays_put(tmp_path, qapp, monkeypatch):
    here, vault, general, target, a, b = _setup(tmp_path)
    real = scanner.fingerprint
    monkeypatch.setattr(scanner, "fingerprint", lambda p: "different" if privatemove.TEMPORARY in p else real(p))
    result = privatemove.move(general, target, str(vault), [a, b])
    assert result["moved"] == [] and len(result["failed"]) == 2
    assert (here / "a.png").exists() and (here / "b.png").exists()
    assert not [n for n in os.listdir(vault) if n.startswith(privatemove.TEMPORARY)]   # no half copy left
    assert general.conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 2


def test_the_destinations_are_the_profiles_library_folders(tmp_path, qapp):
    target = Database(tmp_path / "gallery.db")
    target.add_folder("file://" + str(tmp_path / "Private art"), "photos")
    assert privatemove.library_folders(target) == [{"path": str(tmp_path / "Private art"), "name": "Private art",
                                                    "category": "photos"}]
