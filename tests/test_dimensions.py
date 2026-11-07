# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The size of each picture as shown (images from their header, videos from the background probe) and when a file
was first seen: what pages need to lay files out in their own shape and to list what was recently added."""
import os
import shutil
import subprocess
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage, QImageIOHandler, QImageWriter

from tetia.models import covers, mpv, playbackStore, scanner
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel


def _image(path, width, height):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("teal"))
    assert image.save(str(path))


def _row(path):
    return get_database().conn.execute("SELECT * FROM media WHERE path = ?", (os.path.realpath(str(path)),)).fetchone()


def _aspects(model):
    return {model.data(model.index(r), MediaModel.Roles.FileNameRole): model.data(model.index(r), MediaModel.Roles.AspectRole)
            for r in range(model.rowCount())}


def test_an_older_library_gets_the_new_columns_and_added_time_from_mtime():
    db = get_database()
    db.conn.execute("INSERT INTO media (path, name, kind, size, mtime) VALUES ('/x/a.png', 'a.png', 'image', 1, 1700000000)")
    for name in ("width", "height", "added_at"):
        db.conn.execute(f"ALTER TABLE media DROP COLUMN {name}")
    db.conn.execute("PRAGMA user_version = 13")
    db.conn.commit()
    db._migrate()
    row = db.conn.execute("SELECT width, height, added_at FROM media WHERE path = '/x/a.png'").fetchone()
    assert tuple(row) == (None, None, 1700000000)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] >= 14


def test_a_new_file_is_stamped_when_first_seen_and_keeps_it(tmp_path):
    _image(tmp_path / "a.png", 4, 4)
    before = int(time.time())
    MediaModel().load_from_qurl(str(tmp_path))
    first = _row(tmp_path / "a.png")["added_at"]
    assert before - 1 <= first <= int(time.time()) + 1
    os.utime(tmp_path / "a.png", (1, 1))                       # changed later: still the same "added"
    MediaModel().load_from_qurl(str(tmp_path))
    assert _row(tmp_path / "a.png")["added_at"] == first


def test_an_image_size_is_read_from_its_header(tmp_path):
    _image(tmp_path / "wide.png", 64, 48)
    assert scanner.image_size(str(tmp_path / "wide.png")) == (64, 48)
    (tmp_path / "broken.png").write_bytes(b"not an image")
    assert scanner.image_size(str(tmp_path / "broken.png")) is None


def test_a_photo_turned_by_its_exif_is_measured_as_shown(tmp_path):
    path = tmp_path / "phone.jpg"
    writer = QImageWriter(str(path), b"jpeg")
    if not writer.supportsOption(QImageIOHandler.ImageOption.ImageTransformation):
        pytest.skip("this Qt cannot write an EXIF orientation")
    writer.setTransformation(QImageIOHandler.Transformation.TransformationRotate90)
    image = QImage(80, 40, QImage.Format_RGB32)
    image.fill(QColor("red"))
    assert writer.write(image)
    assert scanner.image_size(str(path)) == (40, 80)


def test_a_scan_gives_every_image_its_shape_and_fills_in_old_rows(tmp_path, qapp):
    _image(tmp_path / "wide.png", 64, 48)
    _image(tmp_path / "tall.png", 30, 60)
    model = MediaModel()
    model.load_from_qurl(str(tmp_path))
    assert _aspects(model) == {"tall.png": 0.5, "wide.png": pytest.approx(64 / 48)}
    assert (_row(tmp_path / "tall.png")["width"], _row(tmp_path / "tall.png")["height"]) == (30, 60)

    db = get_database()                                          # a row stored before sizes were kept
    db.conn.execute("UPDATE media SET width = NULL, height = NULL")
    db.conn.commit()
    model.load_from_qurl(str(tmp_path))
    assert _aspects(model)["tall.png"] == 0.5 and _row(tmp_path / "tall.png")["width"] == 30


def test_a_replaced_image_is_measured_again(tmp_path):
    _image(tmp_path / "a.png", 64, 48)
    MediaModel().load_from_qurl(str(tmp_path))
    _image(tmp_path / "a.png", 20, 80)
    os.utime(tmp_path / "a.png", (2_000_000_000, 2_000_000_000))
    MediaModel().load_from_qurl(str(tmp_path))
    assert (_row(tmp_path / "a.png")["width"], _row(tmp_path / "a.png")["height"]) == (20, 80)


def test_a_quarter_turn_in_a_videos_metadata_swaps_its_size():
    assert playbackStore.picture_size(1920, 1080, 90) == (1080, 1920)
    assert playbackStore.picture_size(1920, 1080, 180) == (1920, 1080)
    assert playbackStore.picture_size(1280.4, 720, 0) == (1280, 720)
    assert playbackStore.picture_size(None, 720, 0) is None


needs_video = pytest.mark.skipif(not mpv.available() or shutil.which("ffmpeg") is None, reason="needs libmpv and ffmpeg")


def _clip(path, size="160x90", rotate=None):
    command = ["ffmpeg", "-v", "error", "-y"]
    if rotate is not None:
        command += ["-display_rotation", str(rotate)]
    command += ["-f", "lavfi", "-i", "testsrc2=size=%s:rate=10:duration=1" % size, "-c:v", "libx264", str(path)]
    return subprocess.run(command, capture_output=True).returncode == 0


def _wait(condition, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.05)
    return False


@needs_video
def test_opening_a_folder_learns_its_videos_shapes_in_the_background(tmp_path, qapp):
    assert _clip(tmp_path / "wide.mp4")
    get_database().add_folder(covers.folder_uri(str(tmp_path)), "videos")
    model = MediaModel()
    model.load_from_qurl(str(tmp_path))
    assert _aspects(model)["wide.mp4"] == 0.0                    # not known yet: the probe runs
    assert _wait(lambda: _aspects(model)["wide.mp4"] > 0)
    assert _aspects(model)["wide.mp4"] == pytest.approx(16 / 9)
    media_id = _row(tmp_path / "wide.mp4")["id"]
    assert get_database().get_playback(media_id)["duration"] > 0  # its length came in the same pass
    assert not playbackStore.prober().needs(str(tmp_path / "wide.mp4"))
    playbackStore.prober().stop()


@needs_video
def test_a_phone_video_turned_by_its_metadata_is_tall(tmp_path, qapp):
    if not _clip(tmp_path / "phone.mp4", "160x90", rotate=90):
        pytest.skip("this ffmpeg cannot write a display rotation")
    model = MediaModel()
    model.load_from_qurl(str(tmp_path))
    assert _wait(lambda: _aspects(model)["phone.mp4"] > 0)
    assert _aspects(model)["phone.mp4"] == pytest.approx(9 / 16)
    playbackStore.prober().stop()
