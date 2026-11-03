# Plasma Vault support without a real vault, D-Bus or password: the service is
# replaced by a fake and "is it mounted?" by a dict. HOME is a throwaway (see conftest.py).
import os, sys, tempfile, time, unittest
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

SRC = str(Path(__file__).resolve().parent.parent / "src")
app = QCoreApplication.instance() or QCoreApplication([])

from tetia.models import profiles, vaults, profileModel as pm

# ---- the real texts the service produced on a real machine -----------------------
CLOSED_LIST = ('QDBusMessage(type=MethodReturn, signature="a(sssqsasb)", contents=([Argument: a(sssqsasb) '
               '{[Argument: (sssqsasb) "Archive", "/home/u/.local/share/plasma-vault/Archive.enc", "", 2, "", {}, false], '
               '[Argument: (sssqsasb) "tetia-test", "/home/u/.local/share/plasma-vault/tetia-test.enc", "", 2, "", {}, false]}]) )')
BLOCKED = ('QDBusMessage(type=Signal, contents=([Argument: (sssqsasb) "tetia-test", '
           '"/home/u/.local/share/plasma-vault/tetia-test.enc", "", 1, '
           '"Unable to lock the vault because it is being used by python3.14", {}, false]) )')


class FakeService(QObject):
    changed = Signal()
    lockBlocked = Signal(str, str)
    callFinished = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.ok = True
        self.reason = ""
        self.raise_on = None       # method name that should blow up

    def available(self): return self.ok
    def unavailableReason(self): return self.reason
    def vaults(self): return [
        {"name": "Safe", "device": "/v/safe.enc", "status": 2, "message": "", "mountPoint": "", "mounted": False},
        {"name": "Free", "device": "/v/free.enc", "status": 2, "message": "", "mountPoint": "", "mounted": False}]
    def _maybe_raise(self, name):
        if self.raise_on == name:
            raise TypeError("QDBusInterface.asyncCall() takes exactly one argument (2 given)")
    def open(self, device): self._maybe_raise("open"); self.calls.append(("open", device))
    def close(self, device): self._maybe_raise("close"); self.calls.append(("close", device))
    def requestNew(self): self.calls.append(("new",))


MOUNTS = {}                      # device -> mount point; what "is it mounted?" answers


@pytest.fixture(autouse=True)
def fake_mounts(monkeypatch):
    MOUNTS.clear()
    monkeypatch.setattr(vaults, "mount_for", lambda device, *a, **k: MOUNTS.get(device, ""))
    monkeypatch.setattr(pm, "POLL_MS", 15)
    yield
    MOUNTS.clear()


def pump(seconds=0.0, until=None, limit=3.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.005)
    return bool(until and until())


class PureTests(unittest.TestCase):
    def test_parse_service_texts(self):
        listed = vaults.vaults_from_text(CLOSED_LIST)
        self.assertEqual([v["name"] for v in listed], ["Archive", "tetia-test"])
        self.assertEqual(listed[0]["status"], 2)
        blocked = vaults.vaults_from_text(BLOCKED)[0]
        self.assertEqual(blocked["status"], 1)
        self.assertIn("used by python3.14", blocked["message"])

    def test_parse_survives_odd_text(self):
        self.assertEqual(vaults.vaults_from_text("nothing here"), [])
        self.assertEqual(vaults.vaults_from_text('[Argument: (sssqsasb) "a", "b"]'), [])
        tricky = '[Argument: (sssqsasb) "na,me ]", "/d/x.enc", "", 1, "say \\"hi\\", ok", {"a", "b"}, true]'
        v = vaults.vaults_from_text(tricky)[0]
        self.assertEqual((v["name"], v["message"]), ("na,me ]", 'say "hi", ok'))

    def test_mount_lookup(self):
        mounts = Path.home() / "mounts"
        mounts.write_text(
            "tmpfs /tmp tmpfs rw 0 0\n"
            "/home/u/.local/share/plasma-vault/a.enc /home/u/.vault/a fuse.gocryptfs rw 0 0\n"
            "cryfs@/home/u/.local/share/plasma-vault/b.enc /home/u/.vault/b\\040space fuse.cryfs rw 0 0\n"
            "/home/u/.local/share/plasma-vault/c.enc /mnt/not-fuse ext4 rw 0 0\n")
        import importlib.util
        spec = importlib.util.spec_from_file_location("vaults_fresh", os.path.join(SRC, "tetia", "models", "vaults.py"))
        fresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(fresh)
        self.assertEqual(fresh.mount_for("/home/u/.local/share/plasma-vault/a.enc", str(mounts)), "/home/u/.vault/a")
        self.assertEqual(fresh.mount_for("/home/u/.local/share/plasma-vault/b.enc", str(mounts)), "/home/u/.vault/b space")
        self.assertEqual(fresh.mount_for("/home/u/.local/share/plasma-vault/c.enc", str(mounts)), "")
        self.assertEqual(fresh.mount_for("/nope.enc", str(mounts)), "")
        self.assertEqual(fresh.mount_for("", str(mounts)), "")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        for f in (profiles._registry_path(),):
            if f.exists(): f.unlink()
        MOUNTS.clear()
        profiles.activate(None)

    def test_vault_profile_lifecycle(self):
        prof, err = profiles.create_vault_profile("Secret", "/v/safe.enc")
        self.assertEqual(err, "")
        self.assertEqual((prof["kind"], prof["device"]), ("vault", "/v/safe.enc"))
        self.assertTrue(profiles.create_vault_profile("Other", "/v/safe.enc")[1])      # one profile per vault
        self.assertTrue(profiles.create_vault_profile("Other", "relative")[1])
        self.assertTrue(profiles.create_vault_profile("secret", "/v/b.enc")[1])        # unique names
        self.assertEqual(profiles.rename(prof["id"], "Safe box"), "")
        self.assertEqual(profiles.delete(prof["id"]), "")
        self.assertIsNone(profiles.get(prof["id"]))

    def test_old_entries_are_local(self):
        profiles._registry_path().write_text('{"profiles": [{"id": "0123456789ab", "name": "old"}]}')
        self.assertEqual(profiles.get("0123456789ab")["kind"], "local")

    def test_vault_registry_validation(self):
        profiles._registry_path().write_text('{"profiles": [{"id": "0123456789ab", "name": "x", "kind": "vault"},'
                                             '{"id": "0123456789ac", "name": "y", "kind": "weird"}]}')
        self.assertEqual(profiles.private_profiles(), [])

    def test_locked_vault_means_general(self):
        prof, _ = profiles.create_vault_profile("Secret", "/v/safe.enc")
        self.assertEqual(profiles.activate(prof["id"]), "general")       # not mounted
        mount = tempfile.mkdtemp(prefix="mount")
        MOUNTS["/v/safe.enc"] = mount
        self.assertEqual(profiles.activate(prof["id"]), prof["id"])
        self.assertEqual(profiles.profile_dir(), Path(mount) / ".tetia")
        self.assertEqual(profiles.thumbnail_base(), Path(mount) / ".tetia" / "thumbnails")
        self.assertTrue((Path(mount) / ".tetia").is_dir())
        self.assertEqual((profiles.active_kind(), profiles.active_device()), ("vault", "/v/safe.enc"))
        self.assertTrue(profiles.delete(prof["id"]))                      # in use
        profiles.activate(None)
        self.assertEqual(profiles.delete(prof["id"]), "")
        self.assertTrue((Path(mount) / ".tetia").is_dir(), "deleting a vault profile must leave the vault's data alone")

    def test_local_delete_removes_folder_vault_does_not(self):
        local, _ = profiles.create("Local one")
        folder = profiles.base_dir() / "profiles" / local["id"]
        self.assertTrue(folder.is_dir())
        self.assertEqual(profiles.delete(local["id"]), "")
        self.assertFalse(folder.exists())

    def test_release_hooks_run_in_order(self):
        order = []
        profiles.add_release_hook(lambda: order.append("late"), order=900)
        profiles.add_release_hook(lambda: order.append("early"), order=-5)
        profiles.add_release_hook(lambda: 1 / 0, order=0)         # a broken hook must not stop the rest
        profiles.run_release_hooks()
        self.assertEqual([o for o in order if o in ("early", "late")], ["early", "late"])


class FlowTests(unittest.TestCase):
    def setUp(self):
        for f in (profiles._registry_path(),):
            if f.exists(): f.unlink()
        MOUNTS.clear()
        profiles.activate(None)
        profiles._release_hooks[:] = [h for h in profiles._release_hooks if getattr(h[1], "__module__", "") != "flowtest"]
        self.service = FakeService()
        self.relaunched, self.quit = [], []
        self.released = []
        def hook(): self.released.append(True)
        hook.__module__ = "flowtest"
        profiles.add_release_hook(hook, order=1)
        self.vault, _ = profiles.create_vault_profile("Secret", "/v/safe.enc")
        self.vault2, _ = profiles.create_vault_profile("Second", "/v/second.enc")

    def model(self):
        return pm.ProfileModel(service=self.service,
                               relaunch=lambda pid: (self.relaunched.append(pid), True)[1],
                               quit_fn=lambda: self.quit.append(True))

    def enter_vault(self, profile=None, device="/v/safe.enc"):
        profile = profile or self.vault
        MOUNTS[device] = tempfile.mkdtemp(prefix="mount")
        profiles.activate(profile["id"])

    # -- unlocking ------------------------------------------------------------------

    def test_switch_to_vault_unlocks_then_relaunches(self):
        m = self.model()
        m.switchTo(self.vault["id"])
        self.assertEqual((m.busyStage, self.service.calls), ("unlocking", [("open", "/v/safe.enc")]))
        pump(0.1)
        self.assertEqual(self.relaunched, [], "must keep waiting while the vault is still locked")
        MOUNTS["/v/safe.enc"] = "/mnt/x"                   # the user typed the password
        self.assertTrue(pump(until=lambda: self.quit))
        self.assertEqual(self.relaunched, [self.vault["id"]])
        self.assertEqual(self.released, [], "General has nothing to release or lock")
        self.assertNotIn(("close", "/v/safe.enc"), self.service.calls)

    def test_already_unlocked_skips_the_prompt(self):
        MOUNTS["/v/safe.enc"] = "/mnt/x"
        m = self.model()
        m.switchTo(self.vault["id"])
        self.assertTrue(pump(until=lambda: self.quit))
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.relaunched, [self.vault["id"]])

    def test_cancel_keeps_the_current_profile(self):
        m = self.model()
        m.switchTo(self.vault["id"])
        m.cancelBusy()
        MOUNTS["/v/safe.enc"] = "/mnt/x"                   # even if it unlocks later
        pump(0.2)
        self.assertEqual((m.busy, self.relaunched, self.quit), (False, [], []))

    def test_unlock_timeout(self):
        old = pm.UNLOCK_TIMEOUT
        pm.UNLOCK_TIMEOUT = 0.1
        try:
            m = self.model()
            failures = []
            m.switchFailed.connect(failures.append)
            m.switchTo(self.vault["id"])
            self.assertTrue(pump(until=lambda: failures))
            self.assertEqual((m.busy, self.relaunched), (False, []))
        finally:
            pm.UNLOCK_TIMEOUT = old

    def test_local_profile_switch_needs_no_vault(self):
        local, _ = profiles.create("Plain")
        m = self.model()
        m.switchTo(local["id"])
        self.assertTrue(pump(until=lambda: self.quit))
        self.assertEqual((self.relaunched, self.service.calls), ([local["id"]], []))

    def test_busy_blocks_a_second_switch(self):
        m = self.model()
        m.switchTo(self.vault["id"])
        m.switchTo(self.vault2["id"])
        self.assertEqual(self.service.calls, [("open", "/v/safe.enc")])

    def test_failing_open_call_stops_instead_of_waiting(self):
        """The bug that hid KDE's prompt: the call raised and the UI sat waiting."""
        self.service.raise_on = "open"
        m = self.model()
        failures = []
        m.switchFailed.connect(failures.append)
        m.switchTo(self.vault["id"])
        self.assertEqual((m.busy, len(failures)), (False, 1))
        self.assertIn("Couldn't ask Plasma Vault", failures[0])
        self.assertEqual((self.relaunched, self.quit), ([], []))

    def test_service_error_reply_while_unlocking(self):
        m = self.model()
        failures = []
        m.switchFailed.connect(failures.append)
        m.switchTo(self.vault["id"])
        self.service.callFinished.emit("openVault", "")           # fine: no error
        self.assertEqual(m.busyStage, "unlocking")
        self.service.callFinished.emit("openVault", "no such device")
        self.assertEqual((m.busy, len(failures)), (False, 1))
        self.assertIn("no such device", failures[0])

    def test_failing_close_call_is_offered_as_blocked(self):
        self.enter_vault()
        self.service.raise_on = "close"
        m = self.model()
        m.requestQuit()
        self.assertEqual(m.busyStage, "blocked")
        self.assertIn("Couldn't ask Plasma Vault", m.busyText)
        self.service.raise_on = None
        m.retryLock()
        self.assertEqual(m.busyStage, "locking")

    def test_service_error_reply_while_locking(self):
        self.enter_vault()
        m = self.model()
        m.requestQuit()
        self.service.callFinished.emit("closeVault", "denied")
        self.assertEqual(m.busyStage, "blocked")
        self.assertIn("denied", m.busyText)

    # -- locking --------------------------------------------------------------------

    def test_leaving_a_vault_profile_locks_it_first(self):
        self.enter_vault()
        m = self.model()
        m.switchTo("general")
        self.assertEqual(m.busyStage, "locking")
        self.assertEqual(self.released, [True], "files and connections are released before locking")
        self.assertEqual(self.service.calls, [("close", "/v/safe.enc")])
        pump(0.1)
        self.assertEqual(self.relaunched, [])
        del MOUNTS["/v/safe.enc"]                         # the service locked it
        self.assertTrue(pump(until=lambda: self.quit))
        self.assertEqual(self.relaunched, ["general"])

    def test_closing_the_window_locks_then_quits(self):
        self.enter_vault()
        m = self.model()
        self.assertFalse(m.requestQuit(), "the window must stay open until the vault is locked")
        self.assertEqual(self.service.calls, [("close", "/v/safe.enc")])
        del MOUNTS["/v/safe.enc"]
        self.assertTrue(pump(until=lambda: self.quit))
        self.assertEqual(self.relaunched, [])
        self.assertTrue(m.requestQuit(), "the quit that follows must not start another lock")

    def test_closing_general_is_immediate(self):
        m = self.model()
        self.assertTrue(m.requestQuit())
        self.assertEqual(self.service.calls, [])

    def test_blocked_lock_then_retry(self):
        self.enter_vault()
        m = self.model()
        m.requestQuit()
        self.service.lockBlocked.emit("/v/safe.enc", "Unable to lock the vault because it is being used by mpv")
        self.assertTrue(pump(until=lambda: m.busyStage == "blocked"))
        self.assertIn("used by mpv", m.busyText)
        self.assertEqual(self.quit, [])
        m.retryLock()
        self.assertEqual(m.busyStage, "locking")
        self.assertEqual(self.service.calls, [("close", "/v/safe.enc")] * 2)
        self.assertEqual(self.released, [True], "release hooks run once, not on every retry")
        del MOUNTS["/v/safe.enc"]
        self.assertTrue(pump(until=lambda: self.quit))

    def test_blocked_lock_can_be_abandoned(self):
        self.enter_vault()
        m = self.model()
        m.switchTo("general")
        self.service.lockBlocked.emit("/v/safe.enc", "in use")
        self.assertTrue(pump(until=lambda: m.busyStage == "blocked"))
        m.continueWithoutLock()
        self.assertEqual(self.relaunched, ["general"])
        self.assertTrue(self.quit)
        self.assertTrue(m.requestQuit(), "quitting after 'carry on' must not try to lock again")

    def test_stuck_lock_times_out_into_blocked(self):
        self.enter_vault()
        old = pm.LOCK_TIMEOUT
        pm.LOCK_TIMEOUT = 0.1
        try:
            m = self.model()
            m.requestQuit()
            self.assertTrue(pump(until=lambda: m.busyStage == "blocked"))
            self.assertIn("still in use", m.busyText)
        finally:
            pm.LOCK_TIMEOUT = old

    def test_other_vaults_messages_are_ignored(self):
        self.enter_vault()
        m = self.model()
        m.requestQuit()
        self.service.lockBlocked.emit("/v/other.enc", "other vault is busy")
        pump(0.1)
        self.assertEqual(m.busyStage, "locking")

    def test_vault_to_vault_unlocks_new_before_locking_old(self):
        self.enter_vault()
        m = self.model()
        m.switchTo(self.vault2["id"])
        self.assertEqual(self.service.calls, [("open", "/v/second.enc")], "the old vault stays unlocked until the new one is open")
        MOUNTS["/v/second.enc"] = "/mnt/2"
        self.assertTrue(pump(until=lambda: ("close", "/v/safe.enc") in self.service.calls))
        del MOUNTS["/v/safe.enc"]
        self.assertTrue(pump(until=lambda: self.quit))
        self.assertEqual(self.relaunched, [self.vault2["id"]])
        self.assertEqual(self.service.calls, [("open", "/v/second.enc"), ("close", "/v/safe.enc")])

    def test_cancelled_unlock_leaves_the_old_vault_alone(self):
        self.enter_vault()
        m = self.model()
        m.switchTo(self.vault2["id"])
        m.cancelBusy()
        self.assertEqual(self.service.calls, [("open", "/v/second.enc")])
        self.assertEqual(self.released, [])

    # -- vault locked from outside ---------------------------------------------------

    def test_vault_lost_is_noticed(self):
        self.enter_vault()
        m = self.model()
        lost = []
        m.vaultLost.connect(lambda: lost.append(True))
        del MOUNTS["/v/safe.enc"]
        m._check_vault_alive()
        self.assertEqual(lost, [True])
        m.leaveToGeneral()
        self.assertEqual(self.relaunched, ["general"])
        self.assertEqual(self.service.calls, [], "nothing left to lock")

    # -- what QML sees ------------------------------------------------------------------

    def test_profile_list_and_vault_choices(self):
        m = self.model()
        kinds = {p["name"]: p["kind"] for p in m.profiles}
        self.assertEqual(kinds, {"General": "general", "Secret": "vault", "Second": "vault"})
        self.assertEqual([v["name"] for v in m.vaults], ["Free"])        # "Safe" already has a profile
        self.assertTrue(m.vaultAvailable)
        self.service.ok, self.service.reason = False, "Plasma Vault isn't installed"
        self.assertFalse(m.vaultAvailable)
        self.assertEqual(m.vaultUnavailableReason, "Plasma Vault isn't installed")

    def test_vault_profile_error_messages(self):
        m = self.model()
        self.assertTrue(m.vaultProfileError("", "/v/safe.enc"))
        self.assertTrue(m.vaultProfileError("New", ""))
        self.assertIn("Secret", m.vaultProfileError("New", "/v/safe.enc"))
        self.assertEqual(m.vaultProfileError("New", "/v/free.enc"), "")
        self.assertTrue(m.createVaultProfile("New", "/v/free.enc"))


class RealBusTests(unittest.TestCase):
    """The real D-Bus call path, against the bus daemon itself (harmless, no vault involved)."""

    def test_async_call_with_arguments_reaches_the_bus(self):
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
        from tetia.models.vaultService import VaultService
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            self.skipTest("no D-Bus session bus")
        service = VaultService()
        daemon = QDBusInterface("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                "org.freedesktop.DBus", bus)
        service._interface = lambda: daemon
        results = []
        service.callFinished.connect(lambda method, error: results.append((method, error)))
        service._async("NameHasOwner", ["org.freedesktop.DBus"])   # a call WITH an argument
        self.assertTrue(pump(until=lambda: results))
        self.assertEqual(results, [("NameHasOwner", "")])
        service._async("NoSuchMethod", ["x"])
        self.assertTrue(pump(until=lambda: len(results) == 2))
        self.assertEqual(results[1][0], "NoSuchMethod")
        self.assertTrue(results[1][1], "an error reply must be reported, not swallowed")


if __name__ == "__main__":
    unittest.main()
