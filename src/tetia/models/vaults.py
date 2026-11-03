# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plasma Vault helpers that need no Qt, so they can be tested on their own.

Tetia never encrypts anything and never sees a password: the Plasma Vault
service (a KDED module) does the work and shows KDE's own password dialog.
What Tetia needs from it is small: which vaults exist, whether one is mounted
and where, and the text the service gives when a vault can't be locked.

Facts established by tools/vault_prototype.py on a real machine:
  * availableDevices() and the vaultChanged/vaultAdded signals carry a struct
    (sssqsasb) = (name, device, <empty>, status, message, activities, offlineOnly).
    The 5th field is the message, e.g. "Unable to lock the vault because it is
    being used by python3.14"; there is no usable mount-point field.
  * status 1 = opened, 2 = closed (4 and 5 were seen while opening/closing).
  * cancelling the dialog or typing a wrong password produces no error and no
    distinctive signal, so "is it mounted?" is the only reliable test.
"""
import os
import re
import shutil
from pathlib import Path

BACKENDS = ("gocryptfs", "cryfs", "encfs")
STATUS_OPENED = 1
STATUS_CLOSED = 2

STRUCT_SIGNATURE = "(sssqsasb)"


def installed_backends() -> list[str]:
    """Encryption back-ends Plasma Vault can use that are on PATH."""
    return [name for name in BACKENDS if shutil.which(name)]


# ---- Where a vault is mounted ------------------------------------------------

def _unescape(field: str) -> str:
    """/proc/mounts writes spaces and the like as octal escapes (\\040)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def mount_for(device: str, mounts_file: str = "/proc/self/mounts") -> str:
    """The mount point of the vault whose encrypted folder is `device`, or ''.

    The FUSE mount's source is that folder (gocryptfs: the path itself; cryfs:
    'cryfs@<path>'), so the live mount is found by matching the source."""
    if not device:
        return ""
    found = ""
    try:
        for line in Path(mounts_file).read_text().splitlines():
            parts = line.split()
            if len(parts) < 3 or not parts[2].startswith("fuse"):
                continue
            source = _unescape(parts[0])
            if source == device or source.endswith("@" + device):
                found = _unescape(parts[1])   # the last match is the live one
    except OSError:
        return ""
    return found


# ---- Reading the service's struct ---------------------------------------------
# PySide6 can't demarshal D-Bus structs (beginStructure() only marshals), but
# Qt's debug dump of a message contains every field, so structs are decoded
# from that text.

def _split_top_level(text: str) -> list[str]:
    """Split 'a, "b, c", {x, y}, 2' on commas outside quotes and brackets."""
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


def _scalar(token: str):
    token = token.strip()
    if token.startswith('"') and token.endswith('"'):
        return re.sub(r"\\(.)", r"\1", token[1:-1])
    if token in ("true", "false"):
        return token == "true"
    if token.startswith("{") and token.endswith("}"):
        return [_scalar(t) for t in _split_top_level(token[1:-1])]
    try:
        return int(token)
    except ValueError:
        return token


def structs_from_text(text: str, signature: str = STRUCT_SIGNATURE) -> list[list]:
    """Every struct of `signature` in a message's debug text, as field lists."""
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
        found.append([_scalar(t) for t in _split_top_level(text[body_start:i - 1])])
        at = i


def vault_from_fields(fields: list):
    """{'name','device','status','message'} from one struct, or None if it
    doesn't look like one. name/device are told apart by which looks like a
    path, in case a version swaps them."""
    if len(fields) < 5 or not isinstance(fields[3], int):
        return None
    first, second = str(fields[0]), str(fields[1])
    if first.startswith("/") and not second.startswith("/"):
        first, second = second, first
    return {"name": first, "device": second, "status": fields[3], "message": str(fields[4])}


def vaults_from_text(text: str) -> list[dict]:
    return [v for v in (vault_from_fields(f) for f in structs_from_text(text)) if v]
