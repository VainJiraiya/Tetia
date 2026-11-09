# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import stat
import subprocess
import sys
import tarfile

import pytest

from tetia.models import archive, bookcovers, bookpages
from test_bookcovers import BLUE, cbz, middle, picture, png


# ---- the format is what the bytes say, not the extension --------------------------------------

def test_sniff_reads_the_first_bytes(tmp_path):
    cbz(tmp_path / "real.cbz", [("1.png", picture(40, 60))])
    assert archive.sniff(str(tmp_path / "real.cbz")) == "zip"
    (tmp_path / "x.cbz").write_bytes(b"Rar!\x1a\x07\x00 rest")
    assert archive.sniff(str(tmp_path / "x.cbz")) == "rar"
    (tmp_path / "y.cbr").write_bytes(b"7z\xbc\xaf\x27\x1c rest")
    assert archive.sniff(str(tmp_path / "y.cbr")) == "7z"
    (tmp_path / "t.cbt").write_bytes(b"\0" * 257 + b"ustar" + b"\0" * 20)
    assert archive.sniff(str(tmp_path / "t.cbt")) == "tar"
    (tmp_path / "z.cbz").write_bytes(b"just text")
    assert archive.sniff(str(tmp_path / "z.cbz")) == ""
    assert archive.sniff(str(tmp_path / "missing.cbz")) == ""


def test_a_zip_with_a_rar_extension_is_still_read(tmp_path):
    path = cbz(tmp_path / "book.cbz", [("1.png", picture(200, 300, ink=0.4))])
    renamed = tmp_path / "book.cbr"
    shutil.copy(path, renamed)
    assert middle(bookcovers.make_cover(str(renamed), 128)) == BLUE
    refs, message = bookpages.list_pages(str(renamed))
    assert refs == ["1.png"] and message == ""


def test_a_tar_comic_is_read(tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    for name, image in (("page10.png", picture(200, 300, color="red")), ("page2.png", picture(200, 300))):
        (folder / name).write_bytes(png(image))
    path = tmp_path / "book.cbt"
    with tarfile.open(path, "w") as tar:
        for name in ("page10.png", "page2.png"):
            tar.add(folder / name, arcname=name)
    with archive.open_archive(str(path)) as comic:
        assert comic.image_names() == ["page2.png", "page10.png"]
        assert comic.read("page2.png", 10**7)[:4] == b"\x89PNG"
        with pytest.raises(archive.ArchiveError):
            comic.read("page2.png", 10)                       # over the size limit
        with pytest.raises(archive.ArchiveError):
            comic.read("nope.png", 10**7)
    assert middle(bookcovers.make_cover(str(path), 128)) == BLUE


def test_what_is_not_an_archive_says_so(tmp_path):
    (tmp_path / "t.cbz").write_bytes(b"hello")
    with pytest.raises(archive.ArchiveError, match="not a comic archive"):
        archive.open_archive(str(tmp_path / "t.cbz"))


# ---- RAR and 7z through an external tool ------------------------------------------------------------

STUB = '''#!{python}
import os, shutil, sys
# a stand-in for {tool}: the "archive" is the folder <archive>.dir next to the file
args = sys.argv[1:]
with open({log!r}, "a") as f:
    f.write(repr(args) + "\\n")
def listing(path):
    root = path + ".dir"
    return [os.path.relpath(os.path.join(d, n), root) for d, _, files in os.walk(root) for n in files]
def unescape(name):
    return name.replace("\\\\", "")
{body}
'''

BSDTAR_BODY = '''
import io, tarfile
if args[0] == "-tf":
    print("\\n".join(listing(args[1]) + [d + "/" for d in ["dir_entry"]]))
elif args[0] == "-cf":
    # the archive rewritten as a tar stream on standard output
    archive_path = args[-1][1:]
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as out:
        for name in sorted(listing(archive_path)):
            out.add(os.path.join(archive_path + ".dir", name), arcname=name)
elif args[0] == "-xOf":
    name = unescape(args[args.index("--") + 1])
    with open(os.path.join(args[1] + ".dir", name), "rb") as f:
        sys.stdout.buffer.write(f.read())
'''

UNRAR_BODY = '''
if args[0] == "lt":
    root = args[-1] + ".dir"
    for name in sorted(listing(args[-1])):
        print("        Name: " + name.replace("/", "\\\\"))
        print("        Type: File")
        print("        Size: %d" % os.path.getsize(os.path.join(root, name)))
        print()
elif args[0] == "p":
    rest = args[args.index("--") + 1:]
    archive_path, members = rest[0], rest[1:] or sorted(listing(rest[0]))
    for name in members:
        with open(os.path.join(archive_path + ".dir", name), "rb") as f:
            sys.stdout.buffer.write(f.read())
'''

FAILING_7Z_BODY = '''
sys.stderr.write("ERROR: Can not open the file as archive\\n")
sys.exit(2)
'''


def make_tool(tmp_path, monkeypatch, tool, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / f"{tool}.log"
    script = bin_dir / tool
    script.write_text(STUB.format(python=sys.executable, tool=tool, log=str(log), body=body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir))
    return log


def fake_rar(tmp_path, members, name="old.cbz"):
    path = tmp_path / name
    path.write_bytes(b"Rar!\x1a\x07\x00 not really")
    for member, image in members.items():
        target = tmp_path / (name + ".dir") / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png(image))
    return str(path)


MEMBERS = {"Series [v1] (English)/page10.png": picture(200, 300, color="red"),
           "Series [v1] (English)/page2.png": picture(200, 300),
           "Series [v1] (English)/notes.txt": picture(10, 10)}


def test_a_rar_named_cbz_is_read_through_bsdtar(tmp_path, monkeypatch):
    path = fake_rar(tmp_path, MEMBERS)
    log = make_tool(tmp_path, monkeypatch, "bsdtar", BSDTAR_BODY)
    with archive.open_archive(path) as comic:
        names = comic.image_names()
        assert names == ["Series [v1] (English)/page2.png", "Series [v1] (English)/page10.png"]     # natural order
        assert comic.read(names[0], 10**7)[:4] == b"\x89PNG"                    # one page: its own run
        assert comic._pages
    assert not comic._pages                                                    # close() let go of the pages
    commands = log.read_text()
    assert "'-xOf'" in commands and "'--'" in commands and "'-C'" not in commands
    assert "page2.png" in commands and "\\\\[v1\\\\]" in commands                # glob characters were escaped for bsdtar
    assert middle(bookcovers.make_cover(path, 128)) == BLUE                    # a whole book: one tar stream
    assert "'-cf'" in log.read_text()


def test_unrar_is_used_when_bsdtar_is_missing(tmp_path, monkeypatch):
    path = fake_rar(tmp_path, MEMBERS)
    log = make_tool(tmp_path, monkeypatch, "unrar", UNRAR_BODY)
    assert [t for t, _ in archive.find_tools("rar")] == ["unrar"]
    with archive.open_archive(path) as comic:
        names = comic.image_names()
        assert names == ["Series [v1] (English)/page2.png", "Series [v1] (English)/page10.png"]
        comic.prefetch(names)                                                  # cut apart by the listed sizes
        for name in names:
            assert comic._pages[name] == (tmp_path / "old.cbz.dir" / name).read_bytes()
    assert middle(bookcovers.make_cover(path, 128)) == BLUE
    assert "'lt'" in log.read_text() and "'p'" in log.read_text()


def test_a_7zip_without_rar_support_is_skipped_for_the_next_tool(tmp_path, monkeypatch):
    path = fake_rar(tmp_path, MEMBERS)
    make_tool(tmp_path, monkeypatch, "7z", FAILING_7Z_BODY)
    make_tool(tmp_path, monkeypatch, "unrar", UNRAR_BODY)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert [t for t, _ in archive.find_tools("rar")] == ["unrar", "7z"]       # unrar is tried first for RAR
    assert middle(bookcovers.make_cover(path, 128)) == BLUE


def test_the_messages_say_what_to_install_without_blaming_a_good_tool(tmp_path, monkeypatch):
    path = fake_rar(tmp_path, MEMBERS)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(archive.ArchiveError, match="bsdtar \\(libarchive\\) or unrar"):       # nothing installed
        archive.open_archive(path)
    make_tool(tmp_path, monkeypatch, "7z", FAILING_7Z_BODY)                    # only a 7-Zip that cannot do RAR
    with pytest.raises(archive.ArchiveError, match="bsdtar \\(libarchive\\) or unrar"):
        archive.open_archive(path)
    make_tool(tmp_path, monkeypatch, "unrar", FAILING_7Z_BODY)                 # a capable tool, a damaged file
    with pytest.raises(archive.ArchiveError, match="could not be read"):
        archive.open_archive(path)


@pytest.mark.skipif(not shutil.which("7z") and not shutil.which("7zz"), reason="needs 7-Zip")
def test_a_real_7z_comic_is_read(tmp_path):
    folder = tmp_path / "pages"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "p2.png").write_bytes(png(picture(200, 300)))
    (folder / "sub" / "p10.png").write_bytes(png(picture(200, 300, color="red")))
    seven = tmp_path / "book.cb7"
    exe = shutil.which("7zz") or shutil.which("7z")
    subprocess.run([exe, "a", "-bd", str(seven), "."], cwd=folder, capture_output=True, check=True)
    assert archive.sniff(str(seven)) == "7z"
    with archive.open_archive(str(seven)) as comic:
        assert comic.image_names() == ["sub/p2.png", "sub/p10.png"]
        comic.prefetch(comic.image_names())                                     # one run, cut by the listed sizes
        for name in ("sub/p2.png", "sub/p10.png"):
            assert comic._pages[name] == (folder / name).read_bytes()
        comic._pages.clear()
        assert comic.read("sub/p10.png", 10**7) == (folder / "sub" / "p10.png").read_bytes()   # one page alone
    assert middle(bookcovers.make_cover(str(seven), 128)) == BLUE


def test_pages_are_never_written_to_disk(tmp_path, monkeypatch):
    import tempfile
    path = fake_rar(tmp_path, {f"{i}.png": picture(50, 80) for i in range(4)})
    log = make_tool(tmp_path, monkeypatch, "bsdtar", BSDTAR_BODY)
    temp = tempfile.gettempdir()
    before = set(os.listdir(temp))
    with archive.open_archive(path) as comic:
        comic.prefetch(comic.image_names())
        assert comic.read("3.png", 10**6)[:4] == b"\x89PNG"
    assert not [n for n in set(os.listdir(temp)) - before if n.startswith("tetia")]
    assert "'-C'" not in log.read_text() and "'-xf'" not in log.read_text()     # no unpacking into a folder


def test_only_the_asked_for_pages_are_kept(tmp_path, monkeypatch):
    path = fake_rar(tmp_path, {f"{i}.png": picture(50, 80) for i in range(10)})
    log = make_tool(tmp_path, monkeypatch, "bsdtar", BSDTAR_BODY)
    with archive.open_archive(path) as comic:
        comic.prefetch(["0.png", "1.png"])
        assert sorted(comic._pages) == ["0.png", "1.png"]
        comic.read("0.png", 10**6)                                              # already read: no second run
    assert log.read_text().count("'-cf'") == 1 and "'-xOf'" not in log.read_text()


def test_memory_is_capped_and_a_dropped_page_is_read_again(tmp_path, monkeypatch):
    path = fake_rar(tmp_path, {f"{i}.png": picture(50, 80) for i in range(4)})
    log = make_tool(tmp_path, monkeypatch, "bsdtar", BSDTAR_BODY)
    page = len((tmp_path / "old.cbz.dir" / "0.png").read_bytes())
    monkeypatch.setattr(archive, "MEMORY_BUDGET", page * 2 + 1)
    with archive.open_archive(path) as comic:
        comic.prefetch(comic.image_names())
        assert len(comic._pages) <= 3 and comic._held <= page * 3
        first = comic.image_names()[0]
        comic._pages.pop(first, None)                                           # (dropped)
        assert comic.read(first, 10**6)[:4] == b"\x89PNG"
    assert "'-xOf'" in log.read_text()


# ---- the picker keeps a tool-read comic unpacked while it is open --------------------------------

def test_the_picker_reads_a_rar_once_and_lets_go(tmp_path, monkeypatch, qapp):
    path = fake_rar(tmp_path, {f"{i:02d}.png": picture(200, 300, ink=0.4, color=c)
                               for i, c in enumerate(("#1e4fd0", "red", "#00aa00"))})
    log = make_tool(tmp_path, monkeypatch, "bsdtar", BSDTAR_BODY)
    refs, message = bookpages.list_pages(path)
    assert refs == ["00.png", "01.png", "02.png"] and message == ""
    token = bookpages.register(path, refs)
    provider = bookpages.BookPageProvider()
    from PySide6.QtCore import QSize
    pages = [provider.requestImage(f"{token}/{i}", QSize(), QSize()) for i in range(3)]
    assert all(not p.isNull() for p in pages) and middle(pages[2])[1] > 120
    assert log.read_text().count("'-cf'") == 1                                  # one read for all three pages
    comic = bookpages._kept[path][0]
    assert len(comic._pages) == 3
    bookpages.unregister(token)
    bookpages.release(path)
    assert not comic._pages and path not in bookpages._kept
