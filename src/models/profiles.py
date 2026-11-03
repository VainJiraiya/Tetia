"""Profiles: the built-in General profile plus any number of private ones.

General uses the app's normal locations (the database in ~/.local/share/GalleryApp
and the shared freedesktop thumbnail cache), so nothing about it changes.

A private profile keeps EVERYTHING it creates inside its own folder,
~/.local/share/GalleryApp/profiles/<id>/ (database with folders, tags, favorites
and ratings; covers; thumbnail cache). It never reads or writes General's data
and never touches ~/.cache/thumbnails, which file managers can see. Deleting the
profile deletes that folder.

The active profile is fixed for the life of the process: it is chosen once at
startup (activate), before any model opens the database. Switching profiles
relaunches the app. Plain module, no Qt, so it can be tested on its own.
"""
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

GENERAL_ID = "general"
GENERAL_NAME = "General"
MAX_NAME_LENGTH = 40

_active = GENERAL_ID


# ---- Locations -------------------------------------------------------------

def base_dir() -> Path:
    """The app's data folder: General's data and the profile registry live here."""
    path = Path.home() / ".local" / "share" / "GalleryApp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path() -> Path:
    return base_dir() / "profiles.json"


def profile_dir(profile_id=None) -> Path:
    """The data folder of a profile (the active one by default). Created on use."""
    profile_id = profile_id or _active
    if profile_id == GENERAL_ID:
        return base_dir()
    path = base_dir() / "profiles" / profile_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbnail_base() -> Path:
    """Where the active profile keeps thumbnails (freedesktop layout).
    General shares the system cache; a private profile has its own."""
    if _active == GENERAL_ID:
        return Path.home() / ".cache" / "thumbnails"
    return profile_dir() / "thumbnails"


# ---- Registry --------------------------------------------------------------

def private_profiles() -> list[dict]:
    """[{'id', 'name'}, ...] of the private profiles, oldest first."""
    try:
        data = json.loads(_registry_path().read_text(encoding="utf-8"))
        items = data.get("profiles", [])
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for item in items:
        if (isinstance(item, dict) and isinstance(item.get("id"), str)
                and re.fullmatch(r"[0-9a-f]{12}", item["id"])
                and isinstance(item.get("name"), str)):
            out.append({"id": item["id"], "name": item["name"]})
    return out


def _save(profiles: list[dict]):
    path = _registry_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"profiles": profiles}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def all_profiles() -> list[dict]:
    """General first, then the private ones: [{'id','name','private'}]."""
    return ([{"id": GENERAL_ID, "name": GENERAL_NAME, "private": False}]
            + [{**p, "private": True} for p in private_profiles()])


def get(profile_id: str):
    return next((p for p in all_profiles() if p["id"] == profile_id), None)


# ---- The active profile ----------------------------------------------------

def activate(profile_id=None) -> str:
    """Choose the profile for this process. Anything unknown (or no choice at
    all) means General, so a stale or mistyped id can never open a private
    profile by accident. Returns the id actually activated."""
    global _active
    _active = GENERAL_ID
    if profile_id and profile_id != GENERAL_ID and get(profile_id) is not None:
        _active = profile_id
    return _active


def active_id() -> str:
    return _active


def is_private() -> bool:
    return _active != GENERAL_ID


def active_name() -> str:
    profile = get(_active)
    return profile["name"] if profile else GENERAL_NAME


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
    """Create a private profile. Returns (profile dict, '') or (None, error)."""
    clean, error = _clean_name(name)
    if error:
        return None, error
    profile = {"id": uuid.uuid4().hex[:12], "name": clean}
    try:
        profile_dir(profile["id"])   # make its folder
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
    """Delete a private profile and everything in its folder. The profile in
    use can't be deleted. Returns '' on success, else an error message."""
    if profile_id == GENERAL_ID:
        return "The General profile can't be deleted."
    if profile_id == _active:
        return "Switch to another profile before deleting this one."
    profiles = private_profiles()
    if not any(p["id"] == profile_id for p in profiles):
        return "That profile no longer exists."
    folder = base_dir() / "profiles" / profile_id
    try:
        if folder.exists():
            shutil.rmtree(folder)
        _save([p for p in profiles if p["id"] != profile_id])
    except OSError as e:
        return f"Couldn't delete the profile: {e.strerror or e}"
    return ""


# ---- Launching ---------------------------------------------------------------

def relaunch_command(profile_id: str, script: str) -> list[str]:
    """argv that starts the app in a profile. General is the default, so it
    gets no argument at all."""
    command = [sys.executable, script]
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
