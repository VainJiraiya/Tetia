#!/usr/bin/env python3
"""Throwaway prototype: can Tetia drive a KDE Plasma Vault over D-Bus?

Uses only PySide6.QtDBus + the standard library. It never asks for, sees, logs
or passes a password: `openVault` makes the Plasma Vault service show KDE's OWN
password dialog, and we just wait for the vault to become mounted.

Usage (from the repo root, inside `nix develop`):

    python tools/vault_prototype.py                  # steps a+b only: introspect + list vaults
    python tools/vault_prototype.py NAME             # the full flow on vault NAME
    python tools/vault_prototype.py NAME --hold-open # same, but keep a file open while locking
    python tools/vault_prototype.py --selftest-dir /some/dir   # steps d+e only, no D-Bus, no vault

Options: --timeout SECONDS (wait for you to type the password, default 300),
         --keep (don't delete the .tetia test files from the vault).
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Slot, SLOT
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

SERVICE = "org.kde.kded6"
PATH = "/modules/plasmavault"
IFACE = "org.kde.plasmavault"

# Facts for the final summary
notes = {
    "methods_used": set(),
    "signals_seen": {},       # name -> count
    "status_codes": {},       # code -> what we saw it mean
    "surprises": [],
}


def surprise(text):
    print(f"  !! {text}")
    notes["surprises"].append(text)


def heading(text):
    print(f"\n=== {text} " + "=" * max(0, 70 - len(text)))


# ---------------------------------------------------------------------------
# D-Bus plumbing
# ---------------------------------------------------------------------------

app = None
bus = None
vault_iface = None


def pump(seconds):
    """Let Qt deliver D-Bus signals for a while."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def wait_until(predicate, timeout, interval=0.3):
    """Pump events until predicate() is truthy or the timeout passes."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        result = predicate()
        if result:
            return result
        time.sleep(interval if interval else 0.02)
    return predicate()


def call(name, *args):
    """Call a method on the vault interface; returns the QDBusMessage reply."""
    notes["methods_used"].add(f"{IFACE}.{name}")
    reply = vault_iface.call(name, *args)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        print(f"  call {name}{args} -> ERROR {reply.errorName()}: {reply.errorMessage()}")
    return reply


# PySide6 cannot read D-Bus structs: QDBusArgument.beginStructure() only works
# for *writing*, and asVariant() hands back the same opaque struct. Qt's own
# debug dump of the message does contain every field, so the struct is decoded
# from that text. (This is a surprise worth knowing about; see the summary.)

def _split_top_level(text):
    """Split 'a, "b, c", {x, y}, 2' on commas that are not inside quotes/braces."""
    parts, depth, current, in_str, esc = [], 0, [], False, False
    for ch in text:
        if in_str:
            current.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            current.append(ch)
        elif ch in "{[(":
            depth += 1
            current.append(ch)
        elif ch in "}])":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _scalar(token):
    token = token.strip()
    if token.startswith('"') and token.endswith('"'):
        return re.sub(r'\\(.)', r'\1', token[1:-1])
    if token in ("true", "false"):
        return token == "true"
    if token.startswith("{") and token.endswith("}"):
        return [_scalar(t) for t in _split_top_level(token[1:-1])]
    try:
        return int(token)
    except ValueError:
        return token


def structs_from_message(message, signature="(sssqsasb)"):
    """All structs of the given signature found in a message, as lists of fields."""
    text = repr(message)
    marker = f"[Argument: {signature} "
    found, at = [], 0
    while True:
        start = text.find(marker, at)
        if start < 0:
            return found
        i, depth, in_str, esc = start + len(marker), 1, False, False
        body_start = i
        while i < len(text) and depth > 0:
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            i += 1
        body = text[body_start:i - 1]
        found.append([_scalar(t) for t in _split_top_level(body)])
        at = i


class Vault:
    """One vault, as reported by availableDevices / vaultChanged.
    Field order was OBSERVED on this machine as
    (name, device, <always empty>, status, message, activities, offlineOnly);
    name/device are told apart by which one looks like a path, in case
    another version swaps them."""

    def __init__(self, fields):
        self.raw = fields
        strings = [f for f in fields[:3] if isinstance(f, str)]
        first, second = fields[0], fields[1]
        if isinstance(first, str) and first.startswith("/") and not str(second).startswith("/"):
            self.device, self.name = first, second
        else:
            self.name, self.device = first, second
        self.status = fields[3]
        self.message = fields[4]                     # observed: the lock-failure text lands here
        self.struct_mount_field = fields[2]          # observed to be '' always; purpose unknown
        self.mount_point = mount_for(self.device)    # the real one, from /proc/self/mounts
        self.activities = fields[5]
        self.offline_only = fields[6]

    def __str__(self):
        return (f"name={self.name!r} device={self.device!r} status={self.status} "
                f"mount={self.mount_point!r} (struct field: {self.struct_mount_field!r}) "
                f"message={self.message!r}")


def list_vaults():
    reply = call("availableDevices")
    return [Vault(f) for f in structs_from_message(reply)]


def find_vault(name):
    for vault in list_vaults():
        if vault.name == name:
            return vault
    return None


class SignalListener(QObject):
    """Receives the service's signals and records them."""

    def __init__(self):
        super().__init__()
        self.log = []

    def _record(self, name, message):
        notes["signals_seen"][name] = notes["signals_seen"].get(name, 0) + 1
        detail = ""
        structs = structs_from_message(message) if name in ("vaultAdded", "vaultChanged") else []
        if structs:
            v = Vault(structs[0])
            detail = (f"name={v.name!r} status={v.status} struct-mount-field={v.struct_mount_field!r} "
                      f"live-mount={v.mount_point!r} message={v.message!r}")
        else:
            args = message.arguments()
            detail = ", ".join(str(a) for a in args)
        stamp = time.strftime("%H:%M:%S")
        self.log.append((name, detail))
        print(f"  [signal {stamp}] {name}({detail})")

    @Slot(QDBusMessage)
    def vaultChanged(self, message):
        self._record("vaultChanged", message)

    @Slot(QDBusMessage)
    def vaultAdded(self, message):
        self._record("vaultAdded", message)

    @Slot(QDBusMessage)
    def vaultRemoved(self, message):
        self._record("vaultRemoved", message)

    @Slot(QDBusMessage)
    def hasOpenVaultsChanged(self, message):
        self._record("hasOpenVaultsChanged", message)


# ---------------------------------------------------------------------------
# Step a: introspection
# ---------------------------------------------------------------------------

def introspect():
    heading("a. Introspection")
    probe = QDBusInterface(SERVICE, PATH, "org.freedesktop.DBus.Introspectable", bus)
    if not probe.isValid():
        print(f"Can't reach {SERVICE} {PATH}. Looking for the right service...")
        names = bus.interface().registeredServiceNames().value()
        for n in names:
            if "kded" in n.lower() or "vault" in n.lower():
                print("  candidate bus name:", n)
        return False
    reply = probe.call("Introspect")
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        print("Introspect failed:", reply.errorName(), reply.errorMessage())
        return False
    root = ET.fromstring(reply.arguments()[0])
    print(f"bus name {SERVICE}, object {PATH}")
    for iface in root.findall("interface"):
        name = iface.get("name")
        if name.startswith("org.freedesktop.DBus"):
            print(f"\ninterface {name}  (standard)")
            continue
        print(f"\ninterface {name}")
        for m in iface.findall("method"):
            args = ", ".join(f"{a.get('direction', 'in')} {a.get('type')}"
                             + (f" {a.get('name')}" if a.get("name") else "")
                             for a in m.findall("arg"))
            print(f"  method   {m.get('name')}({args})")
        for s in iface.findall("signal"):
            args = ", ".join(a.get("type") + (f" {a.get('name')}" if a.get("name") else "")
                             for a in s.findall("arg"))
            print(f"  signal   {s.get('name')}({args})")
        for p in iface.findall("property"):
            print(f"  property {p.get('name')} {p.get('type')} ({p.get('access')})")
        if not iface.findall("property"):
            print("  (no properties)")
    return True


# ---------------------------------------------------------------------------
# Mount helpers (plain /proc/mounts, no extra tools)
# ---------------------------------------------------------------------------

def mount_entry(mount_point):
    """(device, fstype, options) of the filesystem mounted exactly at mount_point, or None."""
    found = None
    try:
        wanted = os.path.realpath(mount_point)
        for line in Path("/proc/self/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 4 and os.path.realpath(parts[1].replace("\\040", " ")) == wanted:
                found = (parts[0], parts[2], parts[3])   # the last match is the live one
    except OSError:
        return None
    return found


def is_mounted(mount_point):
    return bool(mount_point) and mount_entry(mount_point) is not None


def _unescape_mount_field(text):
    """/proc/mounts writes spaces etc. as octal escapes, e.g. \\040."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), text)


def mount_for(device):
    """Where the vault with this encrypted-folder path is mounted right now, or ''.

    The service's struct has an EMPTY mount-point field even for an open vault,
    so the live mount point is looked up in /proc/self/mounts instead: the FUSE
    mount's source is the vault's encrypted folder (gocryptfs: the path itself;
    cryfs: 'cryfs@<path>')."""
    found = ""
    try:
        for line in Path("/proc/self/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) < 3 or not parts[2].startswith("fuse"):
                continue
            source = _unescape_mount_field(parts[0])
            if source == device or source.endswith("@" + device) or source.endswith(device):
                found = _unescape_mount_field(parts[1])
    except OSError:
        return ""
    return found


# ---------------------------------------------------------------------------
# Steps d and e: filesystem tests (work on any directory)
# ---------------------------------------------------------------------------

def sqlite_test(directory, mode):
    """Create a table, insert 1000 rows, commit, read back. Returns a result dict."""
    db_path = Path(directory) / "test.db"
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            Path(str(db_path) + suffix).unlink()
        except FileNotFoundError:
            pass

    result = {"requested": mode, "ok": False, "effective_mode": None, "error": None,
              "side_files": [], "seconds": None, "second_connection_ok": None}
    start = time.perf_counter()
    conn = None
    reader = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        effective = conn.execute(f"PRAGMA journal_mode={mode}").fetchone()[0]
        result["effective_mode"] = effective
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.executemany("INSERT INTO t (value) VALUES (?)",
                         [(f"row-{i}",) for i in range(1000)])
        conn.commit()
        count, total = conn.execute("SELECT COUNT(*), SUM(LENGTH(value)) FROM t").fetchone()
        result["rows_read_back"] = count
        result["side_files"] = sorted(p.name for p in Path(directory).glob("test.db-*"))
        # A second connection must also see the committed rows while the first stays open
        reader = sqlite3.connect(str(db_path), timeout=10)
        result["second_connection_ok"] = reader.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1000
        result["ok"] = (count == 1000 and result["second_connection_ok"]
                        and (mode.upper() == effective.upper()))
        if mode.upper() != effective.upper():
            result["error"] = f"asked for {mode}, SQLite kept {effective}"
    except sqlite3.Error as e:
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        for c in (reader, conn):
            if c is not None:
                try:
                    c.close()
                except sqlite3.Error:
                    pass
        result["seconds"] = time.perf_counter() - start
    return result


def thumbs_test(directory, label):
    """Write 500 files of ~20 KB, then read them all back. Returns timings."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    payload = os.urandom(20 * 1024)
    start = time.perf_counter()
    for i in range(500):
        (folder / f"{i:04d}.png").write_bytes(payload)
    write_seconds = time.perf_counter() - start
    start = time.perf_counter()
    total = 0
    for p in folder.iterdir():
        total += len(p.read_bytes())
    read_seconds = time.perf_counter() - start
    print(f"  {label}: wrote 500 x 20 KB in {write_seconds * 1000:.0f} ms "
          f"({500 / write_seconds:.0f} files/s), read back in {read_seconds * 1000:.0f} ms "
          f"({total // 1024} KB)")
    return write_seconds, read_seconds


def run_fs_tests(base, keep):
    work = Path(base) / ".tetia"
    work.mkdir(exist_ok=True)

    heading("d. SQLite on this filesystem")
    outcomes = {}
    for mode in ("WAL", "DELETE"):
        r = sqlite_test(work, mode)
        outcomes[mode] = r
        verdict = "WORKS" if r["ok"] else "FAILED"
        print(f"  journal_mode={mode}: {verdict}  (effective mode: {r['effective_mode']}, "
              f"{r['seconds'] * 1000:.0f} ms, side files: {r['side_files'] or 'none'})")
        if r.get("rows_read_back") is not None:
            print(f"     rows read back: {r['rows_read_back']}, "
                  f"second connection sees them: {r['second_connection_ok']}")
        if r["error"]:
            print(f"     problem: {r['error']}")
    if not outcomes["WAL"]["ok"]:
        surprise("WAL did NOT work on this mount: " + str(outcomes["WAL"]["error"]))
    if outcomes["WAL"]["ok"] and outcomes["DELETE"]["ok"]:
        faster = "WAL" if outcomes["WAL"]["seconds"] < outcomes["DELETE"]["seconds"] else "DELETE"
        print(f"  both modes work; {faster} was faster for this tiny test")

    heading("e. 500 small files (thumbnail cache stand-in)")
    thumbs_test(work / "thumbs", "inside the vault")
    baseline = tempfile.mkdtemp(prefix="tetia-baseline-", dir=Path.home() / ".cache"
                                if (Path.home() / ".cache").is_dir() else None)
    try:
        thumbs_test(baseline, "normal disk (baseline)")
    finally:
        shutil.rmtree(baseline, ignore_errors=True)

    if not keep:
        shutil.rmtree(work, ignore_errors=True)
        print(f"\n  cleaned up {work}")
    return outcomes


# ---------------------------------------------------------------------------
# Steps c and f: open and close
# ---------------------------------------------------------------------------

def open_vault(vault, timeout):
    heading("c. Opening the vault (KDE shows its own password dialog)")
    initial = find_vault(vault.name)
    closed_code = initial.status
    print(f"before: {initial}")
    if initial.mount_point:
        print("already mounted; skipping the open request (use --lock-first to test the password dialog)")
        return initial, 2
    print(f"asking the service to open {initial.device!r} ...")
    print(">>> Type the vault password in the KDE dialog now "
          f"(waiting up to {timeout}s). Nothing is asked for here. <<<")
    call("openVault", initial.device)

    def opened():
        v = find_vault(vault.name)
        return v if (v and v.mount_point) else None

    seen = {closed_code}

    def watch_status():
        v = find_vault(vault.name)
        if v and v.status not in seen:
            seen.add(v.status)
            print(f"  status code {v.status} appeared (message={v.message!r})")
        return opened()

    result = wait_until(watch_status, timeout, interval=0.5)
    if not result:
        v = find_vault(vault.name)
        print(f"timed out or cancelled; last state: {v}")
        return None, closed_code
    print(f"opened: {result}")
    print(f"mount point: {result.mount_point}")
    notes["status_codes"][result.status] = "opened (mounted)"
    notes["status_codes"][closed_code] = "closed (not mounted)"
    entry = mount_entry(result.mount_point)
    if entry:
        print(f"mounted as: device={entry[0]} fstype={entry[1]} options={entry[2]}")
        notes["backend"] = entry[1]
        for backend in ("gocryptfs", "cryfs", "encfs"):
            if backend in entry[1] or backend in entry[0]:
                notes["backend"] = f"{backend} ({entry[1]})"
    return result, closed_code


def close_vault(vault, closed_code, hold_handle):
    heading("f. Locking the vault")
    v = find_vault(vault.name)
    mount_point = v.mount_point or vault.mount_point
    device = v.device
    print(f"before: {v}")
    call("closeVault", v.device)

    def closed():
        cur = find_vault(vault.name)
        return (cur and not mount_for(device)) and cur

    if hold_handle is None:
        result = wait_until(closed, 30, interval=0.5)
        if result:
            print(f"closed: {result}")
            print(f"mount point still a mount? {bool(mount_for(device))}")
        else:
            surprise("vault did not lock within 30 s: " + str(find_vault(vault.name)))
        return

    print("a file inside the vault is still open on purpose; watching what the service says ...")
    result = wait_until(closed, 15, interval=0.5)
    cur = find_vault(vault.name)
    if result:
        surprise("vault locked even though a file was held open (the FUSE layer let go)")
    else:
        print(f"after 15 s the vault is still mounted: {cur}")
        print(f"  service message field: {cur.message!r}  status code: {cur.status}")
        surprise(f"locking with an open file: still mounted after 15 s, status={cur.status}, "
                 f"message={cur.message!r}")
    print("releasing the held file and asking again ...")
    hold_handle.close()
    call("closeVault", cur.device)
    result = wait_until(closed, 30, interval=0.5)
    if result:
        print(f"closed after releasing: {result}")
    else:
        surprise("still not locked after releasing the file: " + str(find_vault(vault.name)))
        print("(not using forceCloseVault; lock it manually if you want it closed)")


# ---------------------------------------------------------------------------

def main():
    global app, bus, vault_iface
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vault", nargs="?", help="name of the vault to open (omit to just list)")
    parser.add_argument("--hold-open", action="store_true",
                        help="keep a file open inside the vault while locking")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--lock-first", action="store_true",
                        help="if the vault is already open, lock it first so KDE asks for the password")
    parser.add_argument("--keep", action="store_true", help="keep the .tetia test files")
    parser.add_argument("--selftest-dir", help="run steps d+e on this directory; no D-Bus")
    args = parser.parse_args()

    if args.selftest_dir:
        run_fs_tests(args.selftest_dir, args.keep)
        return 0

    app = QCoreApplication(sys.argv[:1])
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        print("No D-Bus session bus.")
        return 1

    if not introspect():
        return 1
    vault_iface = QDBusInterface(SERVICE, PATH, IFACE, bus)
    if not vault_iface.isValid():
        print("Interface", IFACE, "is not available on", PATH)
        return 1

    listener = SignalListener()
    for name in ("vaultChanged", "vaultAdded", "vaultRemoved", "hasOpenVaultsChanged"):
        ok = bus.connect(SERVICE, PATH, IFACE, name, listener, SLOT(f"{name}(QDBusMessage)"))
        if not ok:
            surprise(f"could not subscribe to signal {name}")

    heading("b. Known vaults")
    vaults = list_vaults()
    if not vaults:
        print("(none)")
    for v in vaults:
        print(f"  name={v.name!r}\n    device={v.device!r}"
              f"\n    mount point (live, from /proc/self/mounts)={v.mount_point or '(not mounted)'}"
              f"\n    mount-point field in the service's struct={v.struct_mount_field!r}"
              f"\n    status code={v.status}\n    message={v.message!r}"
              f"\n    activities={v.activities} offlineOnly={v.offline_only}")
    reply = call("hasOpenVaults")
    print(f"  hasOpenVaults() = {reply.arguments()[0] if reply.arguments() else '?'}")

    if not args.vault:
        print("\nGive a vault name to run the full flow, e.g.:  python tools/vault_prototype.py "
              + (repr(vaults[0].name) if vaults else "NAME"))
        return 0

    target = find_vault(args.vault)
    if target is None:
        print(f"\nNo vault named {args.vault!r}. Known: {[v.name for v in vaults]}")
        return 1

    if args.lock_first and target.mount_point:
        heading("(lock-first) vault is open; locking it so the password dialog can be tested")
        close_vault(target, target.status, None)
        target = find_vault(args.vault)
        if target.mount_point:
            print("Could not lock it; stopping.")
            return 1

    opened, closed_code = open_vault(target, args.timeout)
    if opened is None:
        return 1

    hold_handle = None
    try:
        outcomes = run_fs_tests(opened.mount_point, args.keep)

        if args.hold_open:
            work = Path(opened.mount_point) / ".tetia"
            work.mkdir(exist_ok=True)
            hold_handle = open(work / "held-open.txt", "w")
            hold_handle.write("held open on purpose\n")
            hold_handle.flush()
            print(f"\n(holding {work / 'held-open.txt'} open for the lock test)")
    finally:
        close_vault(opened, closed_code, hold_handle)
        if hold_handle is not None and not hold_handle.closed:
            hold_handle.close()

    pump(1.0)

    heading("g. Summary")
    print("service:   ", SERVICE, PATH, IFACE)
    print("methods used:")
    for m in sorted(notes["methods_used"]):
        print("   ", m)
    print("signals seen during this run:",
          notes["signals_seen"] or "none (state was read by polling availableDevices)")
    print("status codes observed:", notes["status_codes"] or "n/a")
    print("how state is obtained: availableDevices() returns a(sssqsasb) = "
          "(name, device, <always empty>, status, message, activities, offlineOnly); "
          "vaultChanged carries the same struct")
    print("mount point: NOT the struct's 5th field (empty even when open); looked up in /proc/self/mounts "
          "as the target of the FUSE mount whose source is the vault's device path")
    print("backend:   ", notes.get("backend", "n/a"))
    print("WAL:       ", "works" if outcomes["WAL"]["ok"] else f"FAILED ({outcomes['WAL']['error']})")
    print("DELETE:    ", "works" if outcomes["DELETE"]["ok"] else f"FAILED ({outcomes['DELETE']['error']})")
    print("surprises:")
    notes["surprises"].insert(0, "the struct's mount-point field is empty even for an open vault")
    notes["surprises"].insert(0, "PySide6 cannot demarshal D-Bus structs (beginStructure() only "
                                 "marshals); struct fields were decoded from Qt's debug dump of the message")
    for s in notes["surprises"]:
        print("  -", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
