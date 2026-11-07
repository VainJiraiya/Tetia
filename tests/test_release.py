# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Everything that reads a vault's files must be able to stop quickly, or the vault cannot be locked."""
import os
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from tetia.models import covers, profiles, searchModel
from tetia.models.database import get_database
from tetia.models.scanner import ScanStopped, scan_folder
from tetia.models.thumbModel import ThumbnailProvider


def pictures(folder: Path, count: int):
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(count):
        image = QImage(40, 30, QImage.Format_RGB32)
        image.fill(0xFF000000 + n)
        image.save(str(folder / ("p%03d.png" % n)))


def test_a_scan_that_is_asked_to_stop_stops_between_files_and_writes_nothing(tmp_path):
    pictures(tmp_path / "pics", 30)
    calls = []
    stop = []

    def slow_hash(path):
        calls.append(path)
        if len(calls) == 3:
            stop.append(True)                      # asked to stop while the third file is being read
        return "h"

    with pytest.raises(ScanStopped):
        scan_folder(get_database(), tmp_path / "pics", slow_hash, should_stop=lambda: bool(stop))
    assert len(calls) <= 4, "it stopped between files, not after all thirty"
    assert get_database().conn.execute("select count(*) from media").fetchone()[0] == 0     # nothing half-written


def test_a_scan_without_a_stop_request_is_unchanged(tmp_path):
    pictures(tmp_path / "pics", 5)
    images, *_ = scan_folder(get_database(), tmp_path / "pics", lambda path: "h")
    assert len(images) == 5


def test_the_indexer_stops_in_the_middle_of_a_big_folder(tmp_path, monkeypatch, qapp):
    pictures(tmp_path / "pics", 150)
    get_database().add_folder(covers.folder_uri(str(tmp_path / "pics")), "photos")
    monkeypatch.setattr(searchModel, "content_hash", lambda path: (time.sleep(0.1), "h")[1])    # a slow drive
    model = searchModel.SearchModel()
    model.indexLibrary()
    time.sleep(0.5)
    started = time.monotonic()
    model.stop_indexing()                          # what locking a vault does; used to wait for the whole folder
    assert time.monotonic() - started < 3, "150 files at 0.1 s each would take 15 s"
    assert model._thread is None or not model._thread.is_alive()


def test_thumbnails_stop_when_the_profile_is_released(tmp_path, monkeypatch):
    pictures(tmp_path / "pics", 3)
    provider = ThumbnailProvider()
    started = threading.Event()

    def slow_generate(path, size):                 # a read from a hard drive
        started.set()
        time.sleep(0.5)
        return QImage(10, 10, QImage.Format_RGB32)

    monkeypatch.setattr(provider, "_generate", slow_generate)
    path = str(tmp_path / "pics" / "p000.png")
    result = []
    worker = threading.Thread(target=lambda: result.append(provider.requestImage(path, QSize(), QSize(256, 256))))
    worker.start()
    assert started.wait(2)
    began = time.monotonic()
    profiles.run_release_hooks()                   # the release hook waits for the request under way
    waited = time.monotonic() - began
    worker.join()
    assert waited > 0.3 and not worker.is_alive(), "it waited for the thumbnail being read"
    assert provider._active == 0
    # and from now on it makes nothing, at once
    began = time.monotonic()
    image = provider.requestImage(str(tmp_path / "pics" / "p001.png"), QSize(), QSize(256, 256))
    assert image.isNull() and time.monotonic() - began < 0.2
