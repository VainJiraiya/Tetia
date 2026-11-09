# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pictures inside a comic archive, whatever its extension says.

A file called .cbz is sometimes really a RAR (or the other way round), so the format is
decided by the file's first bytes. Zip and tar are read with Python itself. RAR and 7z
need an external tool, the first of bsdtar (libarchive), 7-Zip or unrar that is installed;
without one an ArchiveError says which to install, so nothing fails silently.

Pages are read into memory, and only there: a tool writes them to its standard output, never to a folder,
so nothing of a private profile's comics lands outside its vault (the system's temp folder is an ordinary disk).
"""
import logging
import os
import posixpath
import shutil
import subprocess
import tarfile
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path

from tetia.models.covers import natural_key

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".jxl", ".heic")
TOOL_TIMEOUT = 90            # seconds a tool may take to list or unpack
MAX_LISTING = 5000           # an archive with more entries than this is not a comic
MEMORY_BUDGET = 512 * 1024 * 1024    # pages of one open tool-read archive kept in memory (the oldest go first)
MAX_PAGE = 128 * 1024 * 1024         # a member bigger than this is not kept from a whole-book read

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
        """A hint that these members will be read next (a tool reads them in one go)."""

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


def _read_up_to(stream, size: int) -> bytes:
    """`size` bytes from a pipe (fewer only if it ends)."""
    chunks, left = [], size
    while left > 0:
        chunk = stream.read(min(left, 1 << 20))
        if not chunk:
            break
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


class _Tool:
    """A tool run whose output is read as it comes; killed when done with, or after TOOL_TIMEOUT."""

    def __init__(self, command):
        try:
            self.proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
        except OSError as e:
            raise ArchiveError("The archive could not be read.") from e
        self._timer = threading.Timer(TOOL_TIMEOUT, self.proc.kill)
        self._timer.daemon = True
        self._timer.start()

    def __enter__(self):
        return self.proc.stdout

    def __exit__(self, *exc):
        self._timer.cancel()
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.stdout.close()
        self.proc.wait()


class ToolArchive(Archive):
    """A RAR or 7z read through bsdtar, unrar or 7-Zip. The tool writes pages to its standard output: a whole
    book in one run (prefetch), or one page at a time (read). bsdtar turns the archive into a tar stream, which
    names each member; unrar and 7-Zip write the members one after the other, in the order they list them, so
    their listed sizes tell where each one ends."""

    def __init__(self, path, tool):
        self._path = str(path)
        self._kind, self._exe = tool
        self._pages = OrderedDict()  # member name -> bytes, oldest first (never written anywhere)
        self._held = 0
        self._lock = threading.Lock()
        self._order = []             # unrar and 7-Zip: [(member name, size)] in the archive's order
        self._names = self._list()

    # -- listing

    def _list(self):
        if self._kind == "bsdtar":
            result = _run([self._exe, "-tf", self._path])
            lines = result.stdout.decode("utf-8", "surrogateescape").splitlines()
            names = [n for n in lines if n and not n.endswith("/")]
        elif self._kind == "unrar":
            result = _run([self._exe, "lt", "--", self._path])
            block = {}
            for line in result.stdout.decode("utf-8", "surrogateescape").splitlines() + [""]:
                key, sep, value = line.lstrip().partition(": ")
                if sep and key in ("Name", "Type", "Size"):
                    if key == "Name" and block:
                        self._add_listed(block.get("Name"), block.get("Type") == "File", block.get("Size"))
                        block = {}
                    block[key] = value
            if block:
                self._add_listed(block.get("Name"), block.get("Type") == "File", block.get("Size"))
            names = [name for name, _ in self._order]
        else:
            result = _run([self._exe, "l", "-ba", "-slt", self._path])
            block = {}
            for line in result.stdout.decode("utf-8", "surrogateescape").splitlines() + [""]:
                if line.strip():
                    key, _, value = line.partition(" = ")
                    block[key] = value
                else:
                    if block.get("Path"):
                        folder = block.get("Folder", "-") == "+" or block.get("Attributes", "").startswith("D")
                        self._add_listed(block["Path"], not folder, block.get("Size"))
                    block = {}
            names = [name for name, _ in self._order]
        if result.returncode not in (0, 1) and not names:      # 1 is a warning for most tools
            raise ArchiveError("The archive could not be read.")
        return names[:MAX_LISTING]

    def _add_listed(self, name, is_file, size):
        if name and is_file:
            try:
                self._order.append((name.replace("\\", "/"), int(size or 0)))
            except ValueError:
                self._order.append((name.replace("\\", "/"), 0))

    def names(self):
        return list(self._names)

    # -- reading, into memory only

    def _keep(self, name, data):
        if name in self._pages:
            self._held -= len(self._pages.pop(name))
        self._pages[name] = data
        self._held += len(data)
        while self._held > MEMORY_BUDGET and len(self._pages) > 1:
            _, dropped = self._pages.popitem(last=False)
            self._held -= len(dropped)

    def prefetch(self, names):
        with self._lock:
            listed = set(self._names)
            wanted = {n for n in names if n in listed and n not in self._pages}
            if not wanted:
                return
            try:
                if self._kind == "bsdtar":
                    self._stream_tar(wanted)
                else:
                    self._stream_members(wanted)
            except (ArchiveError, tarfile.TarError, OSError) as e:
                logger.info("Reading a whole comic at once failed (%s); its pages are read one by one",
                            type(e).__name__)

    def _stream_tar(self, wanted):
        """bsdtar rewrites the archive as a tar stream on its standard output, read here member by member; it is
        stopped once every wanted page has come (a cover needs only the first ones)."""
        with _Tool([self._exe, "-cf", "-", "--format", "pax", "@" + self._path]) as out:
            with tarfile.open(fileobj=out, mode="r|") as stream:
                for member in stream:
                    if member.name in wanted and member.isfile() and member.size <= MAX_PAGE:
                        self._keep(member.name, stream.extractfile(member).read())
                        wanted.discard(member.name)
                        if not wanted or self._held >= MEMORY_BUDGET:
                            break

    def _stream_members(self, wanted):
        """unrar and 7-Zip write every member, one after the other in the listed order; the listed sizes cut them
        apart. Stopped once every wanted page has come."""
        command = ([self._exe, "p", "-inul", "-y", "--", self._path] if self._kind == "unrar"
                   else [self._exe, "x", "-so", "-y", "--", self._path])
        with _Tool(command) as out:
            for name, size in self._order:
                if name in wanted and size <= MAX_PAGE:
                    data = _read_up_to(out, size)
                    if len(data) < size:
                        break                                   # the output ended early: keep nothing more
                    self._keep(name, data)
                    wanted.discard(name)
                    if not wanted or self._held >= MEMORY_BUDGET:
                        break
                else:
                    skipped = 0
                    while skipped < size:
                        chunk = out.read(min(size - skipped, 1 << 20))
                        if not chunk:
                            return
                        skipped += len(chunk)

    def _read_one(self, name, limit):
        """One member, from its own tool run (names are taken literally, not as patterns)."""
        if self._kind == "bsdtar":
            command = [self._exe, "-xOf", self._path, "--", _escape_glob(name)]
        elif self._kind == "unrar":
            command = [self._exe, "p", "-inul", "-y", "--", self._path, name]
        else:
            command = [self._exe, "x", "-so", "-y", "-spd", "--", self._path, name]
        with _Tool(command) as out:
            data = _read_up_to(out, limit + 1)
        if not data:
            raise ArchiveError("A page could not be read.")
        if len(data) > limit:
            raise ArchiveError("A page is too large to read.")
        return data

    def read(self, name, limit):
        if name not in self._names:
            raise ArchiveError("A page could not be read.")
        with self._lock:
            data = self._pages.get(name)
            if data is None:
                data = self._read_one(name, limit)
                self._keep(name, data)
            else:
                self._pages.move_to_end(name)
        if len(data) > limit:
            raise ArchiveError("A page is too large to read.")
        return data

    def close(self):
        with self._lock:
            self._pages.clear()
            self._held = 0


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
