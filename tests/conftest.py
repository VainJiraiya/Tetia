# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared test setup.

Every test runs with a throwaway HOME (and no XDG overrides), so nothing here
can touch real Tetia data, and with the process-wide profile state reset.
Qt runs on the offscreen platform, so no display is needed.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))               # so `tetia` imports without installing it
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)

    from tetia.models import database, profiles
    monkeypatch.setattr(profiles, "_active", profiles.GENERAL_ID)
    monkeypatch.setattr(profiles, "_active_mount", "")
    monkeypatch.setattr(profiles, "_release_hooks", list(profiles._release_hooks))
    database.reset_singleton()
    yield home
    database.reset_singleton()


@pytest.fixture(scope="session")
def qapp():
    """A QCoreApplication for tests that use timers, signals or QtDBus."""
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])
