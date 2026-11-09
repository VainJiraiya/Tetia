# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The app lists folder tiles, and works out what each reads from the disk, on a worker: the window never waits
for a hard drive. A newer load wins, and drawing a listed tile reads nothing."""
import time

from PySide6.QtCore import QCoreApplication

from tetia.models import covers, series
from tetia.models.mediaModel import MediaModel
from tetia.models.subfolderModel import SubfolderModel


def _touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


def _wait(model, rows, timeout=5.0):
    deadline = time.monotonic() + timeout
    while model.rowCount() != rows and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return model.rowCount()


def _names(model):
    return [model.data(model.index(r), model.Roles.NameRole) for r in range(model.rowCount())]


def test_tiles_come_from_the_worker_ready_to_draw(tmp_path, qapp, monkeypatch):
    _touch(tmp_path / "Lib" / "Frieren", "Ch.1.cbz", "Ch.2.cbz")
    _touch(tmp_path / "Lib" / "Art", "a.cbz")
    model = SubfolderModel()
    model.filterMode = int(MediaModel.FilterMode.MangaOnly)
    model.background = True
    model.setSeries(covers.folder_uri(str(tmp_path / "Lib" / "Frieren")), True)
    model.load(str(tmp_path / "Lib"))
    assert model.rowCount() == 0                                      # not on the caller's thread
    assert _wait(model, 2) == 2 and _names(model) == ["Art", "Frieren"]
    # drawing them reads nothing from the disk: no listing, no chapters
    monkeypatch.setattr(series, "chapters", lambda *a: (_ for _ in ()).throw(AssertionError("read on draw")))
    monkeypatch.setattr("tetia.models.subfolderModel._scan", lambda *a: (_ for _ in ()).throw(AssertionError("listed on draw")))
    for row in range(2):
        for role in model.roleNames():
            model.data(model.index(row), role)
    frieren = _names(model).index("Frieren")
    assert model.data(model.index(frieren), model.Roles.ItemCountRole) == 2
    assert model.data(model.index(frieren), model.Roles.LeftRole) == 2


def test_the_latest_load_wins(tmp_path, qapp):
    _touch(tmp_path / "One" / "A", "1.cbz")
    _touch(tmp_path / "Two" / "B", "1.cbz")
    _touch(tmp_path / "Two" / "C", "1.cbz")
    model = SubfolderModel()
    model.filterMode = int(MediaModel.FilterMode.MangaOnly)
    model.background = True
    model.load(str(tmp_path / "One"))
    model.load(str(tmp_path / "Two"))
    assert _wait(model, 2) == 2 and _names(model) == ["B", "C"]
    time.sleep(0.1)
    QCoreApplication.processEvents()
    assert _names(model) == ["B", "C"]                                # the older result never replaced it


def test_a_new_load_clears_the_old_tiles_at_once(tmp_path, qapp):
    _touch(tmp_path / "One" / "A", "1.cbz")
    _touch(tmp_path / "Two" / "B", "1.cbz")
    model = SubfolderModel()
    model.filterMode = int(MediaModel.FilterMode.MangaOnly)
    model.background = True
    model.load(str(tmp_path / "One"))
    assert _wait(model, 1) == 1
    model.load(str(tmp_path / "Two"))
    assert model.rowCount() == 0                                      # A is never shown on Two's page
    assert _wait(model, 1) == 1 and _names(model) == ["B"]


def test_locking_the_vault_stops_the_worker(tmp_path, qapp):
    _touch(tmp_path / "One" / "A", "1.cbz")
    model = SubfolderModel()
    model.filterMode = int(MediaModel.FilterMode.MangaOnly)
    model.background = True
    model.load(str(tmp_path / "One"))
    model._stop_worker()
    model.load(str(tmp_path / "One"))                                 # after the release: nothing more is started
    QCoreApplication.processEvents()
    assert model._worker._shutdown
