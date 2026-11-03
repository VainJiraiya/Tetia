# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Talks to the Plasma Vault service (a KDED module) over D-Bus.

Tetia never encrypts and never sees a password: openVault makes KDE show its
own password dialog. This class only asks, listens and reports. Which vault is
open, and where, is read from /proc/self/mounts (see vaults.py), because the
service gives no mount point and says nothing when the dialog is cancelled.
"""
import logging

from PySide6.QtCore import QObject, SLOT, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage, QDBusPendingCallWatcher

from tetia.models import vaults

logger = logging.getLogger(__name__)

SERVICE = "org.kde.kded6"
PATH = "/modules/plasmavault"
INTERFACE = "org.kde.plasmavault"


class VaultService(QObject):
    # Something about the vaults changed (opened, locked, added, removed)
    changed = Signal()
    # The service refused to lock a vault; the text names what is using it
    lockBlocked = Signal(str, str)      # device, message
    # A method call finished: (method name, error text or '' if it worked)
    callFinished = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bus = QDBusConnection.sessionBus()
        self._iface = None
        self._subscribed = False

    # ---- availability ----------------------------------------------------------

    def _interface(self):
        if self._iface is None or not self._iface.isValid():
            self._iface = QDBusInterface(SERVICE, PATH, INTERFACE, self._bus)
        return self._iface

    def unavailableReason(self) -> str:
        """'' if Plasma Vault can be used, else a short reason."""
        if not self._bus.isConnected():
            return "There is no D-Bus session bus."
        if not self._interface().isValid():
            return "The Plasma Vault service isn't running (is Plasma Vault installed?)."
        if not vaults.installed_backends():
            return "No encryption back-end (gocryptfs, CryFS or EncFS) is installed."
        return ""

    def available(self) -> bool:
        return self.unavailableReason() == ""

    # ---- listing -----------------------------------------------------------------

    def vaults(self) -> list[dict]:
        """[{name, device, status, message, mountPoint, mounted}] for every vault."""
        iface = self._interface()
        if not iface.isValid():
            return []
        reply = iface.call("availableDevices")
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            return []
        out = []
        for vault in vaults.vaults_from_text(repr(reply)):
            mount = vaults.mount_for(vault["device"])
            out.append({**vault, "mountPoint": mount, "mounted": bool(mount)})
        return out

    # ---- actions -----------------------------------------------------------------

    def _async(self, method: str, args=()):
        """Call a method without blocking. NB: PySide6's QDBusInterface.asyncCall()
        takes no arguments for the method; asyncCallWithArgumentList() does.
        The outcome arrives on callFinished."""
        pending = self._interface().asyncCallWithArgumentList(method, list(args))
        watcher = QDBusPendingCallWatcher(pending, self)
        watcher.finished.connect(lambda w=watcher: self._reply(method, w))

    def _reply(self, method, watcher):
        error = ""
        if watcher.isError():
            err = watcher.error()
            error = err.message() or err.name() or "the call failed"
            logger.warning("Plasma Vault %s failed: %s", method, error)
        watcher.deleteLater()
        self.callFinished.emit(method, error)

    def open(self, device: str):
        """Ask the service to unlock a vault; KDE shows its password dialog."""
        self._subscribe()
        self._async("openVault", [device])

    def close(self, device: str):
        self._subscribe()
        self._async("closeVault", [device])

    def requestNew(self):
        """Open KDE's own 'create a vault' wizard."""
        self._subscribe()
        self._async("requestNewVault")

    # ---- signals -----------------------------------------------------------------

    def _subscribe(self):
        if self._subscribed:
            return
        self._subscribed = True
        for name in ("vaultChanged", "vaultAdded", "vaultRemoved", "hasOpenVaultsChanged"):
            ok = self._bus.connect(SERVICE, PATH, INTERFACE, name, self,
                                   SLOT(f"{name}(QDBusMessage)"))
            if not ok:
                logger.warning("Could not subscribe to Plasma Vault signal %s", name)

    def _on_vault_signal(self, message):
        for vault in vaults.vaults_from_text(repr(message)):
            # A message on a vault that is still unlocked means it wouldn't lock
            if vault["message"] and vault["status"] == vaults.STATUS_OPENED:
                self.lockBlocked.emit(vault["device"], vault["message"])
        self.changed.emit()

    @Slot(QDBusMessage)
    def vaultChanged(self, message):
        self._on_vault_signal(message)

    @Slot(QDBusMessage)
    def vaultAdded(self, message):
        self._on_vault_signal(message)

    @Slot(QDBusMessage)
    def vaultRemoved(self, message):
        self.changed.emit()

    @Slot(QDBusMessage)
    def hasOpenVaultsChanged(self, message):
        self.changed.emit()
