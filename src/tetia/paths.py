"""Where Tetia keeps its files, following the XDG Base Directory spec.

$XDG_DATA_HOME and $XDG_CACHE_HOME are honoured (a relative value is invalid
per the spec and ignored). That matters for Flatpak, which points them into the
app's sandbox. Pure Python, no Qt, so the tests need no display.
"""
import os
from pathlib import Path

APP_DIR = "tetia"
# What the app was called before it was renamed; its data is migrated once
# (see migration.py). It was never XDG-aware: it always lived under ~/.local/share.
LEGACY_APP_DIR = "GalleryApp"


def _xdg_dir(variable: str, default_under_home: str) -> Path:
    value = os.environ.get(variable, "")
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / default_under_home


def data_home() -> Path:
    return _xdg_dir("XDG_DATA_HOME", ".local/share")


def cache_home() -> Path:
    return _xdg_dir("XDG_CACHE_HOME", ".cache")


def data_dir() -> Path:
    """Tetia's data folder (not created here)."""
    return data_home() / APP_DIR


def legacy_data_dir() -> Path:
    """The pre-rename data folder, ~/.local/share/GalleryApp."""
    return Path.home() / ".local" / "share" / LEGACY_APP_DIR


def thumbnails_dir() -> Path:
    """The shared freedesktop thumbnail cache that General uses."""
    return cache_home() / "thumbnails"
