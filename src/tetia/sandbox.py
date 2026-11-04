# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Facts about running inside a Flatpak sandbox (pure Python, no Qt).

Tetia keeps real filesystem paths everywhere. The Flatpak grants access to the
user's Pictures, Videos and Documents folders, so those paths work unchanged;
only a few things differ, and they all ask this module.
"""
import os
from pathlib import Path

FLATPAK_INFO = "/.flatpak-info"          # Flatpak creates this file in every sandbox
_HOST_PATH_ATTR = "user.document-portal.host-path"


def in_flatpak() -> bool:
    return os.path.exists(FLATPAK_INFO) or bool(os.environ.get("FLATPAK_ID"))


def real_path(path: str) -> str:
    """The host path behind a document-portal path (/run/user/<uid>/doc/<id>/<name>).

    A file chooser returns such a path for a folder the sandbox was not granted
    directly. Anything else, or a path without the portal's attribute, comes
    back unchanged."""
    if "/doc/" not in path or not path.startswith("/run/user/"):
        return path
    try:
        host = os.getxattr(path, _HOST_PATH_ATTR).decode().rstrip("\x00")
    except (OSError, AttributeError):
        return path
    return host or path


def folder_problem(path: str) -> str:
    """'' if Tetia can scan this folder, else a sentence saying why not.

    Outside a sandbox every readable folder is fine, so this only ever
    complains inside one."""
    p = Path(path)
    if os.access(p, os.R_OK | os.X_OK) and p.is_dir():
        return ""
    if not in_flatpak():
        return f"Tetia can't read {path}."
    return (f"The Flatpak sandbox can't see {path}. Tetia can read Pictures, Videos and Documents "
            "and can't change its own permissions. To allow this folder, use Flatseal or run: "
            f"flatpak override --user --filesystem={path} io.github.VainJiraiya.Tetia")


def usable_folder(path: str) -> tuple[str, str]:
    """(folder to store, problem) for a folder a file chooser returned.

    Prefers the real host path behind a document-portal path, because that is
    stable; but if the sandbox can only reach the portal path (the user picked
    a folder it was not granted directly) that path is the access the portal
    just gave us, so keep it. Problem is '' when the folder is usable."""
    host = real_path(path)
    if folder_problem(host) == "":
        return host, ""
    if host != path and folder_problem(path) == "":
        return path, ""
    return host, folder_problem(host)
