# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Profiles: the built-in General profile plus any number of private ones.

General uses the app's normal locations (the database in the XDG data folder,
$XDG_DATA_HOME/tetia, and the shared freedesktop thumbnail cache), so nothing about it changes.

A private profile keeps EVERYTHING it creates in one place of its own (database
with folders, tags, favorites and ratings; covers; thumbnail cache), never reads
or writes General's data and never touches the shared thumbnail cache ($XDG_CACHE_HOME/thumbnails), which file
managers can see. It comes in two kinds:

  vault  the data lives in <mount>/.tetia inside a KDE Plasma Vault, so it is
         encrypted at rest and only exists while the vault is unlocked. Tetia
         only remembers which vault; Plasma Vault does the encryption and asks
         for the password (see vaults.py).
  local  the data lives in <data folder>/profiles/<id>/. Separate
         from General but NOT encrypted. Offered for people without Plasma Vault.

The active profile is fixed for the life of the process: it is chosen once at
startup (activate), before any model opens the database. Switching profiles
relaunches the app. Plain module, no Qt, so it can be tested on its own.
"""
import json
import logging
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from tetia import paths
from tetia.models import vaults

logger = logging.getLogger(__name__)

GENERAL_ID = "general"
GENERAL_NAME = "General"
MAX_NAME_LENGTH = 40

KIND_GENERAL = "general"
KIND_LOCAL = "local"
KIND_VAULT = "vault"

_active = GENERAL_ID
_active_mount = ""      # the vault's mount point, for an active vault profile


# ---- Locations -------------------------------------------------------------

def base_dir() -> Path:
    """The app's data folder: General's data and the profile registry live here."""
    path = paths.data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path() -> Path:
    return base_dir() / "profiles.json"


def profile_dir(profile_id=None) -> Path:
    """The data folder of a profile (the active one by default). Created on use.
    For a vault profile that is <mount>/.tetia, which only exists while the
    vault is unlocked."""
    profile_id = profile_id or _active
    if profile_id == GENERAL_ID:
        return base_dir()
    profile = get(profile_id)
    if profile is not None and profile["kind"] == KIND_VAULT:
        mount = _active_mount if profile_id == _active else vaults.mount_for(profile["device"])
        if not mount:
            raise RuntimeError("The vault for this profile is locked.")
        path = Path(mount) / ".tetia"
    else:
        path = base_dir() / "profiles" / profile_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbnail_base() -> Path:
    """Where the active profile keeps thumbnails (freedesktop layout).
    General shares the system cache; a private profile has its own."""
    if _active == GENERAL_ID:
        return paths.thumbnails_dir()
    return profile_dir() / "thumbnails"


# ---- Registry --------------------------------------------------------------

def private_profiles() -> list[dict]:
    """[{'id', 'name', 'kind', 'device'}, ...] of the private profiles, oldest
    first. 'device' is the vault's encrypted folder ('' for local profiles)."""
    try:
        data = json.loads(_registry_path().read_text(encoding="utf-8"))
        items = data.get("profiles", [])
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for item in items:
        if not (isinstance(item, dict) and isinstance(item.get("id"), str)
                and re.fullmatch(r"[0-9a-f]{12}", item["id"])
                and isinstance(item.get("name"), str)):
            continue
        kind = item.get("kind", KIND_LOCAL)
        device = item.get("device", "")
        if kind == KIND_VAULT:
            if not isinstance(device, str) or not device.startswith("/"):
                continue
        elif kind == KIND_LOCAL:
            device = ""
        else:
            continue
        out.append({"id": item["id"], "name": item["name"], "kind": kind, "device": device})
    return out


def _save(profiles: list[dict]):
    path = _registry_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"profiles": profiles}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def all_profiles() -> list[dict]:
    """General first, then the private ones:
    [{'id','name','private','kind','device'}]."""
    general = {"id": GENERAL_ID, "name": GENERAL_NAME, "private": False,
               "kind": KIND_GENERAL, "device": ""}
    return [general] + [{**p, "private": True} for p in private_profiles()]


def get(profile_id: str):
    return next((p for p in all_profiles() if p["id"] == profile_id), None)


# ---- The active profile ----------------------------------------------------

def activate(profile_id=None) -> str:
    """Choose the profile for this process. Anything unknown (or no choice at
    all) means General, so a stale or mistyped id can never open a private
    profile by accident. A vault profile whose vault is not unlocked also
    means General. Returns the id actually activated."""
    global _active, _active_mount
    _active, _active_mount = GENERAL_ID, ""
    if not profile_id or profile_id == GENERAL_ID:
        return _active
    profile = get(profile_id)
    if profile is None:
        return _active
    if profile["kind"] == KIND_VAULT:
        mount = vaults.mount_for(profile["device"])
        if not mount:
            return _active
        _active_mount = mount
    _active = profile_id
    return _active


def active_id() -> str:
    return _active


def active_kind() -> str:
    profile = get(_active)
    return profile["kind"] if profile else KIND_GENERAL


def active_device() -> str:
    """The active vault profile's encrypted folder, or ''."""
    profile = get(_active)
    return profile["device"] if profile else ""


def is_private() -> bool:
    return _active != GENERAL_ID


def active_name() -> str:
    profile = get(_active)
    return profile["name"] if profile else GENERAL_NAME


# ---- Letting go of files (so a vault can be locked) --------------------------

_release_hooks: list[tuple[int, object]] = []


def add_release_hook(fn, order: int = 50):
    """Register a function that stops using files and connections in the
    profile's folder. Lower `order` runs first (stop workers, then close
    databases)."""
    _release_hooks.append((order, fn))
    _release_hooks.sort(key=lambda pair: pair[0])


def run_release_hooks():
    for _, fn in list(_release_hooks):
        try:
            fn()
        except Exception:
            logger.exception("A release hook failed")


# ---- Managing profiles -------------------------------------------------------

def _clean_name(name: str, ignore_id=None):
    """(clean name, error). Names are unique ignoring case."""
    name = re.sub(r"\s+", " ", (name or "")).strip()
    if not name:
        return "", "Give the profile a name."
    if len(name) > MAX_NAME_LENGTH:
        return "", f"Names can be at most {MAX_NAME_LENGTH} characters."
    if any(ord(ch) < 32 for ch in name):
        return "", "That name has characters that can't be used."
    for profile in all_profiles():
        if profile["id"] != ignore_id and profile["name"].casefold() == name.casefold():
            return "", "A profile with that name already exists."
    return name, ""


def name_error(name: str, ignore_id=None) -> str:
    """'' if the name is usable for a (new or renamed) profile, else why not."""
    return _clean_name(name, ignore_id)[1]


def create(name: str):
    """Create a LOCAL private profile (own folder, not encrypted).
    Returns (profile dict, '') or (None, error)."""
    clean, error = _clean_name(name)
    if error:
        return None, error
    profile = {"id": uuid.uuid4().hex[:12], "name": clean, "kind": KIND_LOCAL, "device": ""}
    try:
        (base_dir() / "profiles" / profile["id"]).mkdir(parents=True)
        _save(private_profiles() + [profile])
    except OSError as e:
        return None, f"Couldn't create the profile: {e.strerror or e}"
    return {**profile, "private": True}, ""


def create_vault_profile(name: str, device: str):
    """Register a private profile backed by an existing Plasma Vault (`device`
    is its encrypted folder). Nothing is written to the vault until the profile
    is first used. Returns (profile dict, '') or (None, error)."""
    clean, error = _clean_name(name)
    if error:
        return None, error
    if not device or not device.startswith("/"):
        return None, "Choose a vault."
    for existing in private_profiles():
        if existing["device"] == device:
            return None, f"That vault is already used by the profile \u201c{existing['name']}\u201d."
    profile = {"id": uuid.uuid4().hex[:12], "name": clean, "kind": KIND_VAULT, "device": device}
    try:
        _save(private_profiles() + [profile])
    except OSError as e:
        return None, f"Couldn't create the profile: {e.strerror or e}"
    return {**profile, "private": True}, ""


def rename(profile_id: str, name: str) -> str:
    """Returns '' on success, else an error message."""
    if profile_id == GENERAL_ID:
        return "The General profile can't be renamed."
    profiles = private_profiles()
    target = next((p for p in profiles if p["id"] == profile_id), None)
    if target is None:
        return "That profile no longer exists."
    clean, error = _clean_name(name, ignore_id=profile_id)
    if error:
        return error
    target["name"] = clean
    try:
        _save(profiles)
    except OSError as e:
        return f"Couldn't rename the profile: {e.strerror or e}"
    return ""


def delete(profile_id: str) -> str:
    """Delete a private profile. A local profile's folder is deleted with it.
    A vault profile is only forgotten: its data stays inside the vault, which
    Tetia doesn't open for this (delete the .tetia folder there, or the vault
    itself in KDE, to get rid of it). The profile in use can't be deleted.
    Returns '' on success, else an error message."""
    if profile_id == GENERAL_ID:
        return "The General profile can't be deleted."
    if profile_id == _active:
        return "Switch to another profile before deleting this one."
    profiles = private_profiles()
    target = next((p for p in profiles if p["id"] == profile_id), None)
    if target is None:
        return "That profile no longer exists."
    try:
        if target["kind"] == KIND_LOCAL:
            folder = base_dir() / "profiles" / profile_id
            if folder.exists():
                shutil.rmtree(folder)
        _save([p for p in profiles if p["id"] != profile_id])
    except OSError as e:
        return f"Couldn't delete the profile: {e.strerror or e}"
    return ""


# ---- Launching ---------------------------------------------------------------

def _own_launcher() -> list[str] | None:
    """The `tetia` command this process was started with, if it was started with one.

    A launcher can set up more than a bare Python interpreter has: the Nix package, for one, is a wrapper
    that puts Tetia, PySide6 and Qt's paths in place, and `sys.executable` alone cannot import Tetia there.
    Starting again through the same launcher gives the new process the same surroundings."""
    argv0 = sys.argv[0] if sys.argv else ""
    if os.path.basename(argv0) != "tetia":
        return None                       # `python -m tetia`, a test runner, ...
    path = argv0 if os.sep in argv0 else shutil.which(argv0)
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return [os.path.abspath(path)]
    return None


def relaunch_command(profile_id: str) -> list[str]:
    """argv that starts the app again, in a profile: through the launcher this process was started with, or as a
    module (which works from a source tree, a virtualenv or a distro package alike). General is the default, so
    it gets no argument at all."""
    command = _own_launcher() or [sys.executable, "-m", "tetia"]
    if profile_id != GENERAL_ID:
        command += ["--profile", profile_id]
    return command


def pop_profile_argument(argv: list[str]):
    """Remove '--profile <id>' from argv (in place) and return the id, or None."""
    if "--profile" not in argv:
        return None
    at = argv.index("--profile")
    value = argv[at + 1] if at + 1 < len(argv) else None
    del argv[at:at + (2 if value is not None else 1)]
    return value
