# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The QML face of moving files into a private profile (see privatemove): which profiles can take them, unlocking
a vault profile's vault (KDE asks for the password; Tetia never sees it), the destinations (that profile's library
folders, and for a vault the vault itself), the move on a worker thread, and locking the vault again afterwards if
Tetia was the one that unlocked it."""
import logging
import os
import threading
import weakref

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import privatemove, profiles, vaults
from tetia.models.database import Database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

POLL_MS = 500
UNLOCK_SECONDS = 120


@QmlElement
class PrivateMoveService(QObject):
    ready = Signal(str, "QVariantList")      # (profile id, destinations [{path, name}]) once its data can be reached
    failed = Signal(str)                    # why it can't be reached or moved (a sentence)
    progress = Signal(int, int)             # (done, total)
    finished = Signal(int, "QStringList")   # (files moved, what went wrong with the others)
    busyChanged = Signal()
    _worker_progress = Signal(int, int)
    _worker_done = Signal(int, "QStringList")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._vault = None
        self._waiting = None              # the profile whose vault is being unlocked
        self._waited = 0
        self._unlocked_here = set()       # vaults Tetia unlocked (locked again after the move)
        self._thread = None
        self._stop = threading.Event()
        self._lock_after = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._worker_progress.connect(self.progress)
        self._worker_done.connect(self._on_done)
        stop = weakref.WeakMethod(self.stop)
        profiles.add_release_hook(lambda: stop() and stop()(), order=0)

    def _service(self):
        if self._vault is None:
            from tetia.models.vaultService import VaultService
            self._vault = VaultService(self)
        return self._vault

    @Slot(result="QVariantList")
    def targets(self) -> list:
        """The private profiles files can be moved into (not the open one): [{id, name, kind, locked}]."""
        out = []
        for p in profiles.private_profiles():
            if p["id"] == profiles.active_id():
                continue
            locked = p["kind"] == profiles.KIND_VAULT and not vaults.mount_for(p["device"])
            out.append({"id": p["id"], "name": p["name"], "kind": p["kind"], "locked": locked})
        return out

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._waiting is not None or (self._thread is not None and self._thread.is_alive())

    @Slot(str)
    def prepare(self, profile_id: str):
        """Get a profile ready to take files: its vault unlocked (KDE asks for the password), then ready()."""
        profile = profiles.get(profile_id)
        if profile is None:
            self.failed.emit("That profile no longer exists.")
            return
        if profile["kind"] == profiles.KIND_VAULT and not vaults.mount_for(profile["device"]):
            self._waiting, self._waited = profile_id, 0
            self._service().open(profile["device"])
            self._timer.start()
            self.busyChanged.emit()
            return
        self._announce(profile_id)

    def _poll(self):
        profile = profiles.get(self._waiting) if self._waiting else None
        if profile is None:
            self._timer.stop()
            return
        self._waited += POLL_MS
        if vaults.mount_for(profile["device"]):
            self._timer.stop()
            self._unlocked_here.add(profile["id"])
            self._waiting = None
            self.busyChanged.emit()
            self._announce(profile["id"])
        elif self._waited >= UNLOCK_SECONDS * 1000:
            self._timer.stop()
            self._waiting = None
            self.busyChanged.emit()
            self.failed.emit("The vault was not unlocked.")

    @Slot()
    def cancelUnlock(self):
        self._timer.stop()
        self._waiting = None
        self.busyChanged.emit()

    def _destinations(self, profile_id: str) -> list:
        """Where its files can go: its library folders (inside the vault, for a vault profile), and the vault
        itself."""
        profile = profiles.get(profile_id)
        db = Database(profiles.profile_dir(profile_id) / "gallery.db")
        try:
            folders = privatemove.library_folders(db)
        finally:
            db.close()
        if profile["kind"] == profiles.KIND_VAULT:
            mount = vaults.mount_for(profile["device"]).rstrip("/") + "/"
            folders = [f for f in folders if (f["path"].rstrip("/") + "/").startswith(mount)]   # never outside it
            folders.append({"path": mount.rstrip("/"), "name": "The vault itself", "category": ""})
        seen, out = set(), []
        for f in folders:
            if f["path"] not in seen and os.path.isdir(f["path"]):
                seen.add(f["path"])
                out.append({"path": f["path"], "name": f["name"]})
        return out

    def _announce(self, profile_id: str):
        try:
            self.ready.emit(profile_id, self._destinations(profile_id))
        except Exception as e:
            logger.error("Reading a private profile failed: %s", type(e).__name__)
            self.failed.emit("That profile's library could not be read.")

    @Slot(str, str, "QVariantList", bool)
    def move(self, profile_id: str, folder: str, media_ids, lock_after: bool):
        """Move these files of the open profile into `folder` of that profile, in the background; finished()."""
        if self.busy:
            return
        allowed = {d["path"] for d in self._destinations(profile_id)}
        if folder not in allowed:
            self.failed.emit("That folder is not one of the profile's.")
            return
        self._stop = threading.Event()
        stop = self._stop
        self._lock_after = profile_id if lock_after else None
        ids = [int(i) for i in media_ids]

        def work():
            from tetia.models import thumbModel
            source = target = None
            result = {"moved": [], "failed": []}
            try:
                source = Database()
                target = Database(profiles.profile_dir(profile_id) / "gallery.db")
                result = privatemove.move(source, target, folder, ids, forget_thumbnails=thumbModel.forget_thumbnails,
                                          stop=stop.is_set, progress=lambda d, t: self._worker_progress.emit(d, t))
            except Exception as e:
                logger.error("Moving files into a private profile failed: %s", type(e).__name__)
                result["failed"].append(("", "the move stopped (%s)" % type(e).__name__))
            finally:
                for db in (source, target):
                    if db is not None:
                        db.close()
            self._worker_done.emit(len(result["moved"]),
                                   [("%s: %s" % (name, why)) if name else why for name, why in result["failed"]])

        self._thread = threading.Thread(target=work, name="private-move", daemon=True)
        self._thread.start()
        self.busyChanged.emit()

    def _on_done(self, moved: int, problems: list):
        profile_id, self._lock_after = self._lock_after, None
        if profile_id and profile_id in self._unlocked_here:
            profile = profiles.get(profile_id)
            if profile is not None:
                self._service().close(profile["device"])      # (nothing of Tetia's is open in it any more)
            self._unlocked_here.discard(profile_id)
        self.busyChanged.emit()
        self.finished.emit(moved, problems)

    def stop(self):
        """Before the open profile's vault is locked (or Tetia quits): the file being moved is finished, no other."""
        self._timer.stop()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=60)
