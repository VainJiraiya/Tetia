# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Move to Private Profile: a local profile takes files at once; a vault profile's vault is unlocked first (KDE
asks), its destinations stay inside the vault, and it is locked again after the move if Tetia unlocked it."""
import os
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from tetia.models import covers, privateMoveService, profiles
from tetia.models.database import Database, get_database
from tetia.models.privateMoveService import PrivateMoveService
from tetia.models.scanner import fingerprint, scan_folder


def _wait(done, timeout=10):
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return done()


def _picture(tmp_path):
    here = tmp_path / "General"
    here.mkdir()
    image = QImage(4, 4, QImage.Format_RGB32)
    image.fill(QColor("red"))
    image.save(str(here / "a.png"))
    db = get_database()
    scan_folder(db, here, fingerprint)
    return here, db.get_media_by_path(os.path.realpath(str(here / "a.png")))[0]


def test_a_local_profile_takes_files_at_once(tmp_path, qapp):
    here, a = _picture(tmp_path)
    profile, _ = profiles.create("Hidden")
    folder = tmp_path / "Hidden art"
    folder.mkdir()
    target = Database(profiles.profile_dir(profile["id"]) / "gallery.db")
    target.add_folder(covers.folder_uri(str(folder)), "photos")
    target.close()
    service = PrivateMoveService()
    assert [t["name"] for t in service.targets()] == ["Hidden"] and not service.targets()[0]["locked"]
    ready, done = [], []
    service.ready.connect(lambda pid, dests: ready.append(dests))
    service.finished.connect(lambda n, problems: done.append((n, list(problems))))
    service.prepare(profile["id"])
    assert ready and ready[0] == [{"path": str(folder), "name": "Hidden art"}]
    service.move(profile["id"], str(folder), [a], False)
    assert _wait(lambda: done) and done[0] == (1, [])
    assert (folder / "a.png").exists() and not (here / "a.png").exists()


def test_a_vault_is_unlocked_used_from_inside_and_locked_again(tmp_path, qapp, monkeypatch):
    here, a = _picture(tmp_path)
    mount = tmp_path / "mnt"
    (mount / "Art").mkdir(parents=True)
    profile, _ = profiles.create_vault_profile("Vault", "/enc/device")
    unlocked = []
    monkeypatch.setattr(privateMoveService.vaults, "mount_for", lambda device: str(mount) if unlocked else "")
    monkeypatch.setattr(profiles.vaults, "mount_for", lambda device: str(mount) if unlocked else "")
    calls = []

    class FakeVault:
        def open(self, device):
            calls.append(("open", device))
            unlocked.append(1)                    # (the user typed the password in KDE's dialog)

        def close(self, device):
            calls.append(("close", device))
    service = PrivateMoveService()
    monkeypatch.setattr(service, "_service", lambda: FakeVault())
    target = None
    assert service.targets()[0]["locked"]
    ready, done = [], []
    service.ready.connect(lambda pid, dests: ready.append(dests))
    service.finished.connect(lambda n, problems: done.append(n))
    service.prepare(profile["id"])
    assert _wait(lambda: ready)
    target = Database(profiles.profile_dir(profile["id"]) / "gallery.db")
    target.add_folder(covers.folder_uri(str(mount / "Art")), "photos")
    target.add_folder(covers.folder_uri(str(tmp_path / "Outside")), "photos")        # outside the vault: never offered
    target.close()
    (tmp_path / "Outside").mkdir()
    destinations = service._destinations(profile["id"])
    assert [d["path"] for d in destinations] == [str(mount / "Art"), str(mount)]
    service.move(profile["id"], str(tmp_path / "Outside"), [a], True)                 # refused
    service.move(profile["id"], str(mount / "Art"), [a], True)
    assert _wait(lambda: done) and done == [1]
    assert calls == [("open", "/enc/device"), ("close", "/enc/device")]               # locked again: Tetia opened it
    assert (mount / "Art" / "a.png").exists()
