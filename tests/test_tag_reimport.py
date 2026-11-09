# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Re-import tags (a file or a folder, everything below it) in the background, and the switch for imports."""
import json
import os
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from tetia.models.database import get_database
from tetia.models.scanner import fingerprint, scan_folder
from tetia.models.tagImportService import TagImportService


def _picture(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor("blue"))
    image.save(str(path))


def _tags(db, path):
    media_id = db.get_media_by_path(os.path.realpath(str(path)))[0]
    return {r[0] for r in db.conn.execute(
        "SELECT t.name FROM media_tag mt JOIN tag t ON t.id = mt.tag_id WHERE mt.media_id = ?", (media_id,))}


def _wait(service, done):
    deadline = time.monotonic() + 10
    while not done and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return done


def test_files_scanned_before_imports_get_their_tags_and_lose_stale_ones(tmp_path, qapp):
    db = get_database()
    service = TagImportService()
    service.enabled = False
    _picture(tmp_path / "Lib" / "a.png")
    _picture(tmp_path / "Lib" / "Sub" / "b.png")
    scan_folder(db, tmp_path / "Lib", fingerprint)
    scan_folder(db, tmp_path / "Lib" / "Sub", fingerprint)
    service.enabled = True
    (tmp_path / "Lib" / "a.png.json").write_text(json.dumps({"tags": ["sky"]}))
    (tmp_path / "Lib" / "Sub" / "b.png.json").write_text(json.dumps({"tags": ["sea"]}))
    done = []
    service.finished.connect(lambda n: done.append(n))
    service.reimport([str(tmp_path / "Lib")])
    assert _wait(service, done) == [2]                                # the folder and everything below it
    assert _tags(db, tmp_path / "Lib" / "a.png") == {"sky"} and _tags(db, tmp_path / "Lib" / "Sub" / "b.png") == {"sea"}
    (tmp_path / "Lib" / "a.png.json").unlink()                         # it no longer says anything
    done.clear()
    service.reimport(["file://" + str(tmp_path / "Lib" / "a.png")])
    assert _wait(service, done) == [1] and _tags(db, tmp_path / "Lib" / "a.png") == set()


def test_the_switch_is_kept(qapp):
    service = TagImportService()
    assert service.enabled
    service.enabled = False
    assert get_database().get_setting("import.tags") == "off" and not TagImportService().enabled
    service.enabled = True
    assert TagImportService().enabled
