# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Moving a file to the system Trash, inside and outside a Flatpak sandbox.

Outside a sandbox Qt does it. Inside one Qt cannot: it fills a private trash that the
user's file manager never shows (or a hidden .Trash-UID folder next to the file), so a
"deleted" file looks lost. A sandboxed app has to ask the desktop's Trash portal
(org.freedesktop.portal.Trash) and hand it a file descriptor opened for writing.

The portal can refuse. Tetia never falls back to Qt's private trash then: the file stays
where it is and the reason is reported, so nothing is lost silently. One reason is common on
KDE: KDE creates the Trash's info/ and files/ folders readable by everyone (755), and a recent
portal insists on 700.
"""
import errno
import logging
import os
from dataclasses import dataclass

from PySide6.QtCore import QFile
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage, QDBusUnixFileDescriptor

from tetia import sandbox

logger = logging.getLogger(__name__)

# why a file could not be moved ("" means it was)
FAILED = "failed"                 # outside a sandbox: Qt could not do it
REFUSED = "portal-refused"        # the portal answered "no"
UNAVAILABLE = "portal-unavailable"  # no portal on the session bus
NOT_WRITABLE = "not-writable"     # the file cannot be opened for writing, which the portal requires
NOT_A_FILE = "not-a-file"         # a folder or a link: the portal trashes plain files only

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.Trash"

# What to run once to make KDE's Trash folders acceptable to the portal
TRASH_FIX_COMMAND = "chmod 700 ~/.local/share/Trash/files ~/.local/share/Trash/info"


@dataclass(frozen=True)
class Outcome:
    ok: bool
    reason: str = ""


def _call_portal(fd: int):
    """The portal's answer to TrashFile for this open file: 1 trashed, 0 refused, None if
    the portal could not be reached."""
    interface = QDBusInterface(PORTAL_SERVICE, PORTAL_PATH, PORTAL_INTERFACE, QDBusConnection.sessionBus())
    if not interface.isValid():
        return None
    reply = interface.call("TrashFile", QDBusUnixFileDescriptor(fd))     # the descriptor is duplicated
    if reply.type() == QDBusMessage.MessageType.ErrorMessage or not reply.arguments():
        logger.warning("The Trash portal call failed: %s", reply.errorMessage())
        return None
    return int(reply.arguments()[0])


def _via_portal(path: str) -> Outcome:
    try:
        # O_NOFOLLOW: a link is never followed, so the portal cannot trash what it points to
        fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EISDIR):
            return Outcome(False, NOT_A_FILE)
        if e.errno in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ETXTBSY):
            return Outcome(False, NOT_WRITABLE)
        logger.warning("Could not open %s for the Trash portal: %s", path, e)
        return Outcome(False, FAILED)
    try:
        answer = _call_portal(fd)
    finally:
        os.close(fd)
    if answer is None:
        return Outcome(False, UNAVAILABLE)
    if answer == 1:
        return Outcome(True)
    logger.warning("The Trash portal refused %s", path)
    return Outcome(False, REFUSED)


def move_to_trash(path: str) -> Outcome:
    """Move one file to the user's Trash (see the module notes for the sandbox case)."""
    if sandbox.in_flatpak():
        return _via_portal(path)
    if QFile.moveToTrash(path):
        return Outcome(True)
    return Outcome(False, FAILED)


def explain(reason: str) -> str:
    """A sentence for the user saying why files could not be moved ('' for a plain failure)."""
    return {
        REFUSED: ("The system Trash would not take the files. The Flatpak version of Tetia can only reach the "
                  "Trash through the desktop portal, and the portal refuses Trash folders that other people can "
                  "read. KDE creates them that way. Run this once in a terminal, then try again:"),
        UNAVAILABLE: "The desktop's Trash service could not be reached, so nothing was moved. Is xdg-desktop-portal running?",
        NOT_WRITABLE: "Tetia cannot write to these files, and the desktop's Trash service only takes files that can be written.",
        NOT_A_FILE: "Folders and links cannot be moved to the Trash from the Flatpak version of Tetia.",
    }.get(reason, "")


def fix_command(reason: str) -> str:
    return TRASH_FIX_COMMAND if reason == REFUSED else ""
