# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""How a scan reads new files: once each, in the order they lie on the disk, with a 64 KB fingerprint, and still
recognising a renamed file whose row has the fingerprint of an older Tetia."""
import os
import struct

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

from tetia.models import scanner
from tetia.models.database import get_database
from tetia.models.scanner import fingerprint, scan_folder


def _picture(path, w, h, fmt="PNG"):
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor("teal"))
    image.save(str(path), fmt)
    return path


@pytest.fixture
def counted(monkeypatch):
    """The files the scanner opens itself, in order, and how often it falls back to a second open for a size."""
    opened, fallbacks = [], []
    real_open, real_size = open, scanner.image_size
    monkeypatch.setattr(scanner, "open", lambda path, *a, **k: (opened.append(str(path)), real_open(path, *a, **k))[1],
                        raising=False)
    monkeypatch.setattr(scanner, "image_size", lambda path: (fallbacks.append(path), real_size(path))[1])
    return opened, fallbacks


def test_each_new_file_is_opened_once_in_disk_order(tmp_path, counted, qapp):
    opened, fallbacks = counted
    folder = tmp_path / "pics"
    folder.mkdir()
    for i in range(6):
        _picture(folder / f"{i}.png", 30 + i, 20)
    (folder / "clip.mp4").write_bytes(os.urandom(300 * 1024))
    db = get_database()
    images, videos, *_ = scan_folder(db, folder, fingerprint)
    assert len(images) == 6 and len(videos) == 1
    assert sorted(opened) == sorted(str(p) for p in folder.iterdir())             # one open each
    assert opened == sorted(opened, key=lambda p: os.stat(p).st_ino)              # in inode order
    assert fallbacks == []                                                        # sizes came from the same read
    assert [(i["width"], i["height"]) for i in images] == [(30 + i, 20) for i in range(6)]
    row = db.conn.execute("SELECT content_hash FROM media WHERE name = 'clip.mp4'").fetchone()
    assert row["content_hash"].startswith("v2:")
    opened.clear()
    scan_folder(db, folder, fingerprint)
    assert opened == []                                                           # nothing new: nothing read


def test_a_jpeg_whose_header_is_longer_than_the_read_is_measured_apart(tmp_path, counted, qapp):
    opened, fallbacks = counted
    folder = tmp_path / "pics"
    folder.mkdir()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image = QImage(40, 25, QImage.Format_RGB32)
    image.fill(QColor("red"))
    image.save(buffer, "JPEG")
    jpeg = bytes(data)
    padding = b"".join(b"\xff\xe2" + struct.pack(">H", 60002) + b"\0" * 60000 for _ in range(2))  # 120 KB of APP2
    (folder / "big header.jpg").write_bytes(jpeg[:2] + padding + jpeg[2:])
    images, *_ = scan_folder(get_database(), folder, fingerprint)
    assert (images[0]["width"], images[0]["height"]) == (40, 25)
    assert len(fallbacks) == 1


def test_a_renamed_file_with_an_old_fingerprint_keeps_its_row(tmp_path, qapp):
    folder = tmp_path / "pics"
    folder.mkdir()
    _picture(folder / "before.png", 50, 50)
    db = get_database()
    scan_folder(db, folder, fingerprint)
    path = os.path.realpath(folder / "before.png")
    media_id = db.get_media_by_path(path)[0]
    old = scanner._old_fingerprint(path, os.path.getsize(path))
    db.conn.execute("UPDATE media SET content_hash = ?, favorite = 1 WHERE id = ?", (old, media_id))   # an older Tetia's row
    db.conn.commit()
    os.rename(folder / "before.png", folder / "after.png")
    scan_folder(db, folder, fingerprint)
    row = db.get_media_by_path(os.path.realpath(folder / "after.png"))
    assert row[0] == media_id                                                     # the same item, favorite kept
    assert db.conn.execute("SELECT favorite, content_hash FROM media WHERE id = ?", (media_id,)).fetchone()[0] == 1


def test_the_old_fingerprint_is_only_worked_out_when_a_file_went_missing(tmp_path, monkeypatch, qapp):
    folder = tmp_path / "pics"
    folder.mkdir()
    _picture(folder / "a.png", 20, 20)
    db = get_database()
    scan_folder(db, folder, fingerprint)
    calls = []
    real = scanner._old_fingerprint
    monkeypatch.setattr(scanner, "_old_fingerprint", lambda *a: (calls.append(1), real(*a))[1])
    _picture(folder / "b.png", 20, 30)                                            # a new file, nothing gone
    scan_folder(db, folder, fingerprint)
    assert calls == []


def test_an_unreadable_folder_is_not_taken_for_an_empty_one(tmp_path, qapp):
    folder = tmp_path / "pics"
    folder.mkdir()
    _picture(folder / "a.png", 20, 20)
    db = get_database()
    scan_folder(db, folder, fingerprint)
    folder.chmod(0)
    try:
        with pytest.raises(OSError):
            scan_folder(db, folder, fingerprint)
    finally:
        folder.chmod(0o755)
    assert db.conn.execute("SELECT missing FROM media WHERE name = 'a.png'").fetchone()[0] == 0
