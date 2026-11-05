# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pictures inside a comic archive, whatever its extension says.

A file called .cbz is sometimes really a RAR (or the other way round), so the format is
decided by the file's first bytes. Zip and tar are read with Python itself. RAR and 7z
need an external tool, the first of bsdtar (libarchive), 7-Zip or unrar that is installed;
without one an ArchiveError says which to install, so nothing fails silently.

Pages are read into memory. Only a tool-read archive touches the disk: the pages that were
asked for are unpacked once into a private folder that is removed again by close().
"""
import atexit
import logging
import os
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import threading
import zipfile
from pathlib import Path

from tetia.models.covers import natural_key

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".jxl", ".heic")
TOOL_TIMEOUT = 90            # seconds a tool may take to list or unpack
MAX_LISTING = 5000           # an archive with more entries than this is not a comic

# What to install for each format. Not every 7-Zip can read RAR (the RAR decoder has a separate
# licence and many builds leave it out), so for RAR the choice is bsdtar or unrar.
NEEDS_TOOL = {
    "rar": "RAR comics need bsdtar (libarchive) or unrar to be installed.",
    "7z": "7z comics need bsdtar (libarchive) or 7-Zip to be installed.",
}


class ArchiveError(Exception):
    """The archive cannot be read; str() is a sentence fit to show the user."""


def sniff(path: str) -> str:
    """'zip', 'rar', '7z', 'tar' or '' from the first bytes of the file."""
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except OSError:
        return ""
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head[257:262] == b"ustar":
        return "tar"
    return ""


def is_image(name: str) -> bool:
    return (name.lower().endswith(IMAGE_SUFFIXES) and not name.startswith("__MACOSX")
            and not posixpath.basename(name).startswith("."))


class Archive:
    """The members of an archive. Names are as stored; only files are listed."""

    def names(self) -> list:
        raise NotImplementedError

    def read(self, name: str, limit: int) -> bytes:
        """The bytes of one member (ArchiveError if it is missing or bigger than `limit`)."""
        raise NotImplementedError

    def prefetch(self, names: list):
        """A hint that these members will be read next (a tool unpacks them in one go)."""

    def close(self):
        pass

    def image_names(self) -> list:
        return sorted((n for n in self.names() if is_image(n)), key=natural_key)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class ZipArchive(Archive):
    def __init__(self, path):
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as e:
            raise ArchiveError("The archive could not be read.") from e

    def names(self):
        return [i.filename for i in self._zip.infolist() if not i.is_dir()]

    def read(self, name, limit):
        try:
            if self._zip.getinfo(name).file_size > limit:
                raise ArchiveError("A page is too large to read.")
            return self._zip.read(name)
        except (KeyError, zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as e:
            raise ArchiveError("A page could not be read.") from e

    def close(self):
        self._zip.close()


class TarArchive(Archive):
    def __init__(self, path):
        try:
            self._tar = tarfile.open(path)
        except (tarfile.TarError, OSError) as e:
            raise ArchiveError("The archive could not be read.") from e

    def names(self):
        return [m.name for m in self._tar.getmembers() if m.isfile()]

    def read(self, name, limit):
        try:
            member = self._tar.getmember(name)
            if member.size > limit:
                raise ArchiveError("A page is too large to read.")
            return self._tar.extractfile(member).read()
        except (KeyError, tarfile.TarError, OSError, AttributeError) as e:
            raise ArchiveError("A page could not be read.") from e

    def close(self):
        self._tar.close()


# ---- RAR and 7z through an external tool ----------------------------------------------------

# Which tools can read which format, best first
_TOOLS = {
    "rar": (("bsdtar", ("bsdtar",)), ("unrar", ("unrar",)), ("7z", ("7zz", "7z", "7za"))),
    "7z": (("bsdtar", ("bsdtar",)), ("7z", ("7zz", "7z", "7za"))),
}


def find_tools(kind: str) -> list:
    """[(tool kind, executable)] for the installed tools that may read this archive format."""
    found = []
    for tool, names in _TOOLS.get(kind, ()):
        for name in names:
            exe = shutil.which(name)
            if exe:
                found.append((tool, exe))
                break
    return found


def _run(command, **kwargs):
    try:
        return subprocess.run(command, capture_output=True, timeout=TOOL_TIMEOUT, check=False, **kwargs)
    except (subprocess.SubprocessError, OSError) as e:
        raise ArchiveError("The archive could not be read.") from e


def _escape_glob(name: str) -> str:
    """bsdtar matches member names as patterns; quote the characters that mean something."""
    return "".join("\\" + c if c in "*?[]\\" else c for c in name)


_temp_dirs = set()
_temp_lock = threading.Lock()


def _remove_temp_dirs():
    for folder in list(_temp_dirs):
        shutil.rmtree(folder, ignore_errors=True)


atexit.register(_remove_temp_dirs)


class ToolArchive(Archive):
    def __init__(self, path, tool):
        self._path = str(path)
        self._kind, self._exe = tool
        self._folder = None
        self._unpacked = {}          # member name -> file on disk
        self._lock = threading.Lock()
        self._names = self._list()

    # -- listing

    def _list(self):
        if self._kind == "bsdtar":
            result = _run([self._exe, "-tf", self._path])
            lines = result.stdout.decode("utf-8", "surrogateescape").splitlines()
            names = [n for n in lines if n and not n.endswith("/")]
        elif self._kind == "unrar":
            result = _run([self._exe, "lb", self._path])
            lines = result.stdout.decode("utf-8", "surrogateescape").splitlines()
            names = [n.replace("\\", "/") for n in lines if n]
        else:
            result = _run([self._exe, "l", "-ba", "-slt", self._path])
            names, block = [], {}
            for line in result.stdout.decode("utf-8", "surrogateescape").splitlines() + [""]:
                if line.strip():
                    key, _, value = line.partition(" = ")
                    block[key] = value
                else:
                    if block.get("Path") and block.get("Folder", "-") != "+" and not block.get("Attributes", "").startswith("D"):
                        names.append(block["Path"].replace("\\", "/"))
                    block = {}
        if result.returncode not in (0, 1) and not names:      # 1 is a warning for most tools
            raise ArchiveError("The archive could not be read.")
        return names[:MAX_LISTING]

    def names(self):
        return list(self._names)

    # -- reading: unpack what is asked for once, into a private folder

    def _safe(self, name):
        """A member name that cannot climb out of the folder it is unpacked into."""
        parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
        return bool(parts) and ".." not in parts and not name.startswith("/")

    def prefetch(self, names):
        wanted = [n for n in names if n in self._names and self._safe(n) and n not in self._unpacked]
        if not wanted:
            return
        with self._lock:
            if self._folder is None:
                self._folder = tempfile.mkdtemp(prefix="tetia-pages-")
                os.chmod(self._folder, 0o700)
                with _temp_lock:
                    _temp_dirs.add(self._folder)
            if self._kind == "bsdtar":
                command = [self._exe, "-xf", self._path, "-C", self._folder, "--"] + [_escape_glob(n) for n in wanted]
            elif self._kind == "unrar":
                command = [self._exe, "x", "-y", "-inul", self._path] + wanted + [self._folder + os.sep]
            else:
                command = [self._exe, "x", "-y", "-bd", f"-o{self._folder}", self._path] + wanted
            _run(command)
            for name in wanted:
                target = os.path.join(self._folder, *name.replace("\\", "/").split("/"))
                if os.path.isfile(target):
                    self._unpacked[name] = target

    def read(self, name, limit):
        if name not in self._unpacked:
            self.prefetch([name])
        target = self._unpacked.get(name)
        if not target:
            raise ArchiveError("A page could not be read.")
        try:
            if os.path.getsize(target) > limit:
                raise ArchiveError("A page is too large to read.")
            return Path(target).read_bytes()
        except OSError as e:
            raise ArchiveError("A page could not be read.") from e

    def close(self):
        with self._lock:
            if self._folder:
                shutil.rmtree(self._folder, ignore_errors=True)
                with _temp_lock:
                    _temp_dirs.discard(self._folder)
                self._folder = None
                self._unpacked = {}


def open_archive(path: str) -> Archive:
    """Open the comic archive at `path` (ArchiveError, with a message for the user, if not)."""
    kind = sniff(path)
    if kind == "zip":
        return ZipArchive(path)
    if kind == "tar":
        return TarArchive(path)
    if kind in ("rar", "7z"):
        tools = find_tools(kind)
        if not tools:
            raise ArchiveError(NEEDS_TOOL[kind])
        for tool in tools:
            try:
                return ToolArchive(path, tool)
            except ArchiveError as e:      # this tool cannot read it (a 7-Zip without RAR support)
                logger.info("%s could not open %s: %s", tool[0], path, e)
        # a tool that really handles this format failed: the file is damaged. Only a 7-Zip that
        # may lack the RAR decoder failed: ask for one that has it.
        capable = {"rar": ("bsdtar", "unrar"), "7z": ("bsdtar", "7z")}[kind]
        if any(tool[0] in capable for tool in tools):
            raise ArchiveError("The archive could not be read.")
        raise ArchiveError(NEEDS_TOOL[kind])
    raise ArchiveError("This is not a comic archive that can be read.")
