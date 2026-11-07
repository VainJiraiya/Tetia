# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Opening a folder shows what the library knows at once and scans in the background; the indexer and a page
reaching the same folder together fingerprint each file once."""
import threading
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from tetia.models import scanner
from tetia.models.database import Database, get_database
from tetia.models.mediaModel import MediaModel


def _images(folder: Path, names):
    folder.mkdir(exist_ok=True)
    for name in names:
        image = QImage(8, 6, QImage.Format_RGB32)
        image.fill(QColor("orange"))
        image.save(str(folder / name))


def _names(model):
    return [model.data(model.index(r), MediaModel.Roles.FileNameRole) for r in range(model.rowCount())]


def _wait(condition, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def _slow(model, seconds):
    real = model._compute_content_hash
    model._compute_content_hash = lambda path: (time.sleep(seconds), real(path))[1]


def test_a_new_folder_says_it_is_being_read_then_fills_in(tmp_path, qapp):
    _images(tmp_path / "pics", ["b.png", "a.png"])
    model = MediaModel()
    model.openFolder(str(tmp_path / "pics"))
    assert model.scanning is True and _names(model) == []          # nothing known yet: the page waits for the scan
    assert _wait(lambda: not model.scanning)
    assert _names(model) == ["a.png", "b.png"]


def test_a_known_folder_shows_at_once_and_is_not_reset_when_nothing_changed(tmp_path, qapp):
    _images(tmp_path / "pics", ["a.png", "b.png"])
    MediaModel().load_from_qurl(str(tmp_path / "pics"))             # seen before
    model = MediaModel()
    resets = []
    model.modelReset.connect(lambda: resets.append(1))
    model.openFolder(str(tmp_path / "pics"))
    assert _names(model) == ["a.png", "b.png"] and model.scanning is True
    assert _wait(lambda: not model.scanning)
    assert _names(model) == ["a.png", "b.png"] and resets == [1]    # the scan found nothing new: no second reset
    aspect = model.data(model.index(0), MediaModel.Roles.AspectRole)
    assert abs(aspect - 8 / 6) < 0.001


def test_what_changed_on_disk_meanwhile_arrives_with_the_scan(tmp_path, qapp):
    _images(tmp_path / "pics", ["a.png", "b.png"])
    MediaModel().load_from_qurl(str(tmp_path / "pics"))
    (tmp_path / "pics" / "b.png").unlink()
    _images(tmp_path / "pics", ["c.png"])
    model = MediaModel()
    model.openFolder(str(tmp_path / "pics"))
    assert _names(model) == ["a.png", "b.png"]                      # what the library knew
    assert _wait(lambda: not model.scanning)
    assert _names(model) == ["a.png", "c.png"]


def test_a_scan_for_a_folder_left_behind_is_dropped(tmp_path, qapp):
    _images(tmp_path / "slow", ["s1.png", "s2.png", "s3.png"])
    _images(tmp_path / "fast", ["f.png"])
    model = MediaModel()
    _slow(model, 0.2)
    model.openFolder(str(tmp_path / "slow"))
    model.load_from_qurl(str(tmp_path / "fast"))                    # moved on before it finished
    assert _names(model) == ["f.png"] and model.scanning is False
    time.sleep(1.0)
    _wait(lambda: False, 0.3)
    assert _names(model) == ["f.png"]


def test_stopping_before_a_vault_is_locked_ends_the_scan(tmp_path, qapp):
    _images(tmp_path / "pics", ["%02d.png" % n for n in range(20)])
    model = MediaModel()
    _slow(model, 0.1)
    model.openFolder(str(tmp_path / "pics"))
    thread = model._scan_thread
    model._stop_scan()
    assert not thread.is_alive() and model.scanning is False
    assert get_database().conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0   # stopped before writing


def test_two_scans_of_one_folder_read_each_new_file_once(tmp_path, qapp):
    _images(tmp_path / "pics", ["%02d.png" % n for n in range(6)])
    get_database()                 # the app's own connection made the database first, as when Tetia runs
    calls, finished = [], []
    lock = threading.Lock()

    def counting_hash(path):
        with lock:
            calls.append(path)
        time.sleep(0.05)
        return "h-" + Path(path).name

    def scan():
        db = Database()
        try:
            scanner.scan_folder(db, tmp_path / "pics", counting_hash)
            finished.append(1)
        finally:
            db.close()

    threads = [threading.Thread(target=scan) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert finished == [1, 1]
    assert sorted(calls) == sorted(str((tmp_path / "pics" / ("%02d.png" % n)).resolve()) for n in range(6))
