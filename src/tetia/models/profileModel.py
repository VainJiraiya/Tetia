"""QML face of profiles.py: lists, creates, renames, deletes and switches
profiles. Switching relaunches the app into the chosen profile.

Switching to or from a vault profile is a short sequence (all of it visible to
the user through `busy`/`busyStage`/`busyText`):

  1. target is a vault -> ask Plasma Vault to unlock it (KDE shows its password
     dialog) and wait until it is mounted. Cancel or time out and nothing
     changes: the current profile keeps running.
  2. the current profile is a vault -> release every file and connection it
     uses, ask Plasma Vault to lock it, wait until it is unmounted. If it won't
     lock (something is using it) the user can try again or carry on without
     locking.
  3. start the new copy of the app in the target profile and quit this one.

Closing the window while in a vault profile runs step 2 first. The unlock
steps never wait on signals: "is it mounted?" is checked by polling, because
the service stays silent when a password dialog is cancelled.
"""
import os
import time

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QTimer, Property, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import profiles, vaults

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

UNLOCK_TIMEOUT = 300      # seconds to wait for the password to be entered
LOCK_TIMEOUT = 20         # seconds to wait for a lock before calling it stuck
POLL_MS = 300
WATCH_MS = 2000

STAGE_NONE = ""
STAGE_UNLOCKING = "unlocking"
STAGE_LOCKING = "locking"
STAGE_BLOCKED = "blocked"


def _default_relaunch(profile_id: str) -> bool:
    command = profiles.relaunch_command(profile_id)
    return QProcess.startDetached(command[0], command[1:], os.getcwd())


class _NoVaultService(QObject):
    """Stands in for the Plasma Vault client when it can't even be loaded (for
    example a PySide6 build without QtDBus). Everything reports 'unavailable'."""
    changed = Signal()
    lockBlocked = Signal(str, str)
    callFinished = Signal(str, str)

    def __init__(self, reason, parent=None):
        super().__init__(parent)
        self._reason = reason

    def available(self): return False
    def unavailableReason(self): return self._reason
    def vaults(self): return []

    def _unavailable(self, *args):
        raise RuntimeError(self._reason)

    open = close = requestNew = _unavailable


@QmlElement
class ProfileModel(QObject):
    profilesChanged = Signal()
    busyChanged = Signal()
    vaultsChanged = Signal()
    # An attempt ended without switching; the text says why
    switchFailed = Signal(str)
    # The vault of the running profile was locked from outside
    vaultLost = Signal()

    def __init__(self, parent=None, service=None, relaunch=None, quit_fn=None):
        super().__init__(parent)
        # The Plasma Vault client is created the first time it is needed, so a
        # normal start never touches D-Bus (and Plasma Vault stays optional).
        self._service = None
        self._probed = False           # have we asked whether Plasma Vault is usable?
        self._available = False
        self._unavailable_reason = ""
        if service is not None:
            self._attach(service)
        self._relaunch = relaunch or _default_relaunch
        self._quit = quit_fn or QCoreApplication.quit

        self._stage = STAGE_NONE
        self._text = ""
        self._action = None            # ("switch", profile_id) or ("quit",)
        self._deadline = 0.0
        self._blocked_text = ""
        self._released = False
        self._finished = False         # relaunching/quitting: let the window close
        self._unlock_target = None

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)

        # Notices that a vault profile's vault was locked behind our back
        self._watch = QTimer(self)
        self._watch.setInterval(WATCH_MS)
        self._watch.timeout.connect(self._check_vault_alive)
        if profiles.active_kind() == profiles.KIND_VAULT:
            self._watch.start()

    def _attach(self, service):
        self._service = service
        service.lockBlocked.connect(self._on_lock_blocked)
        service.changed.connect(self.vaultsChanged)
        service.callFinished.connect(self._on_call_finished)

    def _svc(self):
        """The Plasma Vault client, created on first use."""
        if self._service is None:
            try:
                from tetia.models.vaultService import VaultService
                service = VaultService(self)
            except ImportError as e:        # e.g. no QtDBus in this PySide6
                service = _NoVaultService(f"Plasma Vault support isn't available ({e}).", self)
            self._attach(service)
        return self._service

    # ---- what QML shows ------------------------------------------------------------

    @Property(list, notify=profilesChanged)
    def profiles(self):
        """[{id, name, isPrivate, kind, active}], General first."""
        active = profiles.active_id()
        return [{"id": p["id"], "name": p["name"], "isPrivate": p["private"],
                 "kind": p["kind"], "active": p["id"] == active}
                for p in profiles.all_profiles()]

    @Property(bool, constant=True)
    def isPrivate(self):
        return profiles.is_private()

    @Property(str, constant=True)
    def activeName(self):
        return profiles.active_name()

    @Property(str, constant=True)
    def activeKind(self):
        return profiles.active_kind()

    @Property(bool, notify=vaultsChanged)
    def vaultAvailable(self):
        """Whether Plasma Vault can be used. False until refreshVaults() has asked."""
        return self._probed and self._available

    @Property(str, notify=vaultsChanged)
    def vaultUnavailableReason(self):
        return self._unavailable_reason

    @Property(list, notify=vaultsChanged)
    def vaults(self):
        """Vaults a new profile could use: [{name, device, mounted}] (not yet used)."""
        if not (self._probed and self._available):
            return []
        used = {p["device"] for p in profiles.private_profiles() if p["kind"] == profiles.KIND_VAULT}
        return [{"name": v["name"], "device": v["device"], "mounted": v["mounted"]}
                for v in self._svc().vaults() if v["device"] not in used]

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._stage != STAGE_NONE

    @Property(str, notify=busyChanged)
    def busyStage(self):
        return self._stage

    @Property(str, notify=busyChanged)
    def busyText(self):
        return self._text

    def _set_stage(self, stage, text=""):
        self._stage, self._text = stage, text
        self.busyChanged.emit()

    # ---- managing profiles ---------------------------------------------------------

    @Slot()
    def refreshVaults(self):
        """Ask whether Plasma Vault is usable and re-read the vault list. This is
        the only place that probes D-Bus; call it when the user is about to need it."""
        service = self._svc()
        self._available = service.available()
        self._unavailable_reason = "" if self._available else service.unavailableReason()
        self._probed = True
        self.vaultsChanged.emit()

    @Slot(str, str, result=str)
    def nameError(self, name: str, profile_id: str) -> str:
        """Why `name` can't be used ('' if it can). profile_id is the profile
        being renamed, or '' when creating one."""
        return profiles.name_error(name, profile_id or None)

    @Slot(str, result=str)
    def createProfile(self, name: str) -> str:
        """Create a LOCAL (unencrypted) private profile. Returns its id, or ''."""
        profile, _ = profiles.create(name)
        if profile is None:
            return ""
        self.profilesChanged.emit()
        return profile["id"]

    @Slot(str, str, result=str)
    def createVaultProfile(self, name: str, device: str) -> str:
        """Create a profile backed by an existing Plasma Vault. Returns its id, or ''."""
        profile, _ = profiles.create_vault_profile(name, device)
        if profile is None:
            return ""
        self.profilesChanged.emit()
        return profile["id"]

    @Slot(str, str, result=str)
    def vaultProfileError(self, name: str, device: str) -> str:
        """Why a vault profile with this name/vault can't be created ('' if it can)."""
        problem = profiles.name_error(name)
        if problem:
            return problem
        if not device:
            return "Choose a vault."
        for existing in profiles.private_profiles():
            if existing["device"] == device:
                return f"That vault is already used by the profile “{existing['name']}”."
        return ""

    @Slot()
    def requestNewVault(self):
        """Open KDE's own wizard for making a new vault."""
        try:
            self._svc().requestNew()
        except Exception as e:
            self.switchFailed.emit(f"Couldn't open the vault wizard: {e}")

    @Slot(str, str, result=str)
    def renameProfile(self, profile_id: str, name: str) -> str:
        error = profiles.rename(profile_id, name)
        if not error:
            self.profilesChanged.emit()
        return error

    @Slot(str, result=str)
    def deleteProfile(self, profile_id: str) -> str:
        error = profiles.delete(profile_id)
        if not error:
            self.profilesChanged.emit()
        return error

    # ---- switching, quitting -------------------------------------------------------

    @Slot(str)
    def switchTo(self, profile_id: str):
        """Switch to a profile (relaunching into it), unlocking its vault first
        and locking the current one after."""
        if self.busy or profile_id == profiles.active_id():
            return
        target = profiles.get(profile_id)
        if target is None:
            return
        if target["kind"] == profiles.KIND_VAULT and not vaults.mount_for(target["device"]):
            # Needs Plasma Vault to unlock it: say so plainly if it isn't there
            self.refreshVaults()
            if not self._available:
                self.switchFailed.emit(
                    f"\u201c{target['name']}\u201d is stored in a Plasma Vault, which isn't available "
                    f"here: {self._unavailable_reason}")
                return
        self._action = ("switch", profile_id)
        self._begin_unlock(target)

    @Slot(result=bool)
    def requestQuit(self) -> bool:
        """Called when the window is closing. True: go ahead and close. False:
        the vault has to be locked first; the app quits once it is."""
        if self._finished:
            return True
        if self.busy:
            return False
        if profiles.active_kind() == profiles.KIND_VAULT and self._vault_mounted():
            self._action = ("quit",)
            self._begin_lock()
            return False
        return True

    @Slot()
    def cancelBusy(self):
        """Give up while waiting for an unlock. (A lock in progress can't be cancelled.)"""
        if self._stage == STAGE_UNLOCKING:
            self._timer.stop()
            self._action = None
            self._set_stage(STAGE_NONE)

    @Slot()
    def retryLock(self):
        if self._stage == STAGE_BLOCKED:
            self._begin_lock()

    @Slot()
    def continueWithoutLock(self):
        """Carry on (switch or quit) leaving the vault unlocked."""
        if self._stage == STAGE_BLOCKED:
            self._finish()

    @Slot()
    def leaveToGeneral(self):
        """The vault went away: drop everything and restart in General (nothing to lock)."""
        profiles.run_release_hooks()
        self._action = ("switch", profiles.GENERAL_ID)
        self._finish()

    # ---- the steps -----------------------------------------------------------------

    def _active_device(self):
        return profiles.active_device()

    def _vault_mounted(self) -> bool:
        return bool(vaults.mount_for(self._active_device()))

    def _begin_unlock(self, target):
        if target["kind"] != profiles.KIND_VAULT or vaults.mount_for(target["device"]):
            self._begin_lock()
            return
        self._unlock_target = target
        self._deadline = time.monotonic() + UNLOCK_TIMEOUT
        self._set_stage(STAGE_UNLOCKING,
                        f"Waiting for the vault “{target['name']}” to unlock.\n"
                        "Enter its password in the KDE window.")
        try:
            self._svc().open(target["device"])
        except Exception as e:                    # never leave the user waiting on a prompt that won't come
            self._fail(f"Couldn't ask Plasma Vault to unlock the vault: {e}")
            return
        self._timer.start()

    def _begin_lock(self):
        """Lock the vault of the running profile, if it has one."""
        if profiles.active_kind() != profiles.KIND_VAULT or not self._vault_mounted():
            self._finish()
            return
        if not self._released:
            profiles.run_release_hooks()
            self._released = True
        self._blocked_text = ""
        self._deadline = time.monotonic() + LOCK_TIMEOUT
        self._set_stage(STAGE_LOCKING, f"Locking “{profiles.active_name()}”…")
        try:
            self._svc().close(self._active_device())
        except Exception as e:
            self._blocked_text = f"Couldn't ask Plasma Vault to lock the vault: {e}"
            self._set_stage(STAGE_BLOCKED, self._blocked_text)
            return
        self._timer.start()

    def _tick(self):
        if self._stage == STAGE_UNLOCKING:
            target = self._unlock_target
            if vaults.mount_for(target["device"]):
                self._timer.stop()
                self._begin_lock()
            elif time.monotonic() > self._deadline:
                self._timer.stop()
                self._action = None
                self._set_stage(STAGE_NONE)
                self.switchFailed.emit("The vault wasn't unlocked in time.")
        elif self._stage == STAGE_LOCKING:
            if not self._vault_mounted():
                self._timer.stop()
                self._finish()
            elif self._blocked_text or time.monotonic() > self._deadline:
                self._timer.stop()
                self._set_stage(STAGE_BLOCKED,
                                self._blocked_text or "The vault is still in use, so it can't be locked.")

    def _fail(self, text):
        """End an attempt that can't go on, without switching."""
        self._timer.stop()
        self._action = None
        self._set_stage(STAGE_NONE)
        self.switchFailed.emit(text)

    def _on_call_finished(self, method, error):
        """The service answered a call with an error (e.g. it isn't there any more)."""
        if not error:
            return
        if self._stage == STAGE_UNLOCKING and method == "openVault":
            self._fail(f"Plasma Vault couldn't unlock the vault: {error}")
        elif self._stage == STAGE_LOCKING and method == "closeVault":
            self._timer.stop()
            self._blocked_text = f"Plasma Vault couldn't lock the vault: {error}"
            self._set_stage(STAGE_BLOCKED, self._blocked_text)

    def _on_lock_blocked(self, device, message):
        if device == self._active_device():
            self._blocked_text = message

    def _finish(self):
        """Everything is in place: relaunch into the target, or just quit."""
        self._timer.stop()
        action, self._action = self._action, None
        self._set_stage(STAGE_NONE)
        self._finished = True
        if action and action[0] == "switch":
            if not self._relaunch(action[1]):
                self._finished = False
                self.switchFailed.emit("Couldn't start the new profile.")
                return
        self._quit()

    def _check_vault_alive(self):
        if self.busy or profiles.active_kind() != profiles.KIND_VAULT:
            return
        if not self._vault_mounted():
            self._watch.stop()
            self.vaultLost.emit()
