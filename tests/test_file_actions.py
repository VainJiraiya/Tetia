# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""A file's menu: rename on disk (the library keeps what it knows about the file)."""
import os

from PySide6.QtCore import QUrl

from tetia.models.database import get_database
from tetia.models.mediaActions import MediaActions
from tetia.models.mediaModel import MediaModel


def test_a_renamed_file_keeps_its_favorite(tmp_path, qapp):
    (tmp_path / "old.png").write_bytes(b"\x89PNG not really")
    (tmp_path / "taken.png").write_bytes(b"other")
    MediaModel().load_from_qurl(str(tmp_path))
    db = get_database()
    media_id = db.get_media_by_path(os.path.realpath(str(tmp_path / "old.png")))[0]
    db.set_media_favorite(media_id, True) if hasattr(db, "set_media_favorite") else db.conn.execute(
        "UPDATE media SET favorite = 1 WHERE id = ?", (media_id,))
    db.conn.commit()
    actions = MediaActions()
    uri = QUrl.fromLocalFile(str(tmp_path / "old.png")).toString()
    assert actions.rename(uri, "taken.png").startswith("There is already")
    assert actions.rename(uri, "a/b.png") == "That is not a file name"
    assert actions.rename(uri, "new.png") == ""
    assert (tmp_path / "new.png").exists() and not (tmp_path / "old.png").exists()
    MediaModel().load_from_qurl(str(tmp_path))                  # the next scan finds it by its contents
    found = db.get_media_by_path(os.path.realpath(str(tmp_path / "new.png")))
    assert found[0] == media_id and found[1] == 1

