# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os

from tetia import sandbox


def test_not_in_flatpak_by_default(monkeypatch):
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr(sandbox, "FLATPAK_INFO", "/nonexistent/.flatpak-info")
    assert not sandbox.in_flatpak()


def test_flatpak_detected_by_env_or_info_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "FLATPAK_INFO", str(tmp_path / "missing"))
    monkeypatch.setenv("FLATPAK_ID", "x.y.Z")
    assert sandbox.in_flatpak()
    monkeypatch.delenv("FLATPAK_ID")
    info = tmp_path / ".flatpak-info"
    info.write_text("")
    monkeypatch.setattr(sandbox, "FLATPAK_INFO", str(info))
    assert sandbox.in_flatpak()


def test_real_path_leaves_ordinary_paths_alone(tmp_path):
    assert sandbox.real_path(str(tmp_path)) == str(tmp_path)
    assert sandbox.real_path("/run/user/1000/doc/abc/Videos") == "/run/user/1000/doc/abc/Videos"  # no attribute


def test_real_path_reads_the_portal_attribute(monkeypatch):
    monkeypatch.setattr(os, "getxattr", lambda p, name: b"/home/u/Videos\x00")
    assert sandbox.real_path("/run/user/1000/doc/abc/Videos") == "/home/u/Videos"


def test_folder_problem(tmp_path, monkeypatch):
    assert sandbox.folder_problem(str(tmp_path)) == ""
    missing = str(tmp_path / "nope")
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: False)
    assert "can't read" in sandbox.folder_problem(missing)
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: True)
    assert "flatpak override" in sandbox.folder_problem(missing)


def test_vaults_unavailable_in_flatpak(monkeypatch, qapp):
    from tetia.models import vaultService
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: True)
    service = vaultService.VaultService()
    assert not service.available()
    assert "Flatpak" in service.unavailableReason()


def test_thumbnails_use_the_shared_cache_in_flatpak(monkeypatch, tmp_path):
    from tetia import paths
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "sandbox-cache"))
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: True)
    # no shared folder granted: stay in the private cache
    assert paths.thumbnails_dir() == tmp_path / "sandbox-cache" / "thumbnails"
    shared = tmp_path / "home" / ".cache" / "thumbnails"
    shared.mkdir(parents=True)
    assert paths.thumbnails_dir() == shared
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: False)
    assert paths.thumbnails_dir() == tmp_path / "sandbox-cache" / "thumbnails"


def test_usable_folder_prefers_host_path_but_keeps_portal_access(monkeypatch, tmp_path):
    host, portal = tmp_path / "host", tmp_path / "portal"
    host.mkdir(); portal.mkdir()
    monkeypatch.setattr(sandbox, "real_path", lambda p: str(host) if p == str(portal) else p)
    assert sandbox.usable_folder(str(portal)) == (str(host), "")           # host reachable: stable path
    host.rmdir()
    assert sandbox.usable_folder(str(portal)) == (str(portal), "")         # only portal reachable: keep it
    portal.rmdir()
    path, problem = sandbox.usable_folder(str(portal))
    assert problem
