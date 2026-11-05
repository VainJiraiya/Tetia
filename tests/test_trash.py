# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import fcntl
import os
from pathlib import Path

import pytest
from PySide6.QtDBus import QDBusMessage

from tetia import sandbox
from tetia.models import mediaActions, trash
from tetia.models.database import get_database
from tetia.models.mediaActions import MediaActions


def media_id(path, db=None):
    db = db or get_database()
    info = os.stat(path)
    row = db.upsert_media(str(path), os.path.basename(path), "image", info.st_size, int(info.st_mtime), "h" + os.path.basename(path))[0]
    db.conn.commit()
    return row


class FakePortal:
    """Stands in for the Trash portal and records what it was given."""
    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def __call__(self, fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        self.seen.append(flags & os.O_ACCMODE)         # how the descriptor was opened
        return self.answer


@pytest.fixture
def in_flatpak(monkeypatch):
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: True)


# ---- outside a sandbox: Qt does it ------------------------------------------------------

def test_outside_a_sandbox_qt_moves_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: False)
    (Path(os.environ["HOME"]) / ".local" / "share").mkdir(parents=True, exist_ok=True)   # Qt makes the Trash inside an existing data folder
    path = tmp_path / "pic.png"
    path.write_bytes(b"x")
    outcome = trash.move_to_trash(str(path))
    assert outcome.ok and not path.exists()


def test_a_failure_outside_a_sandbox_is_reported_plainly(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "in_flatpak", lambda: False)
    outcome = trash.move_to_trash(str(tmp_path / "missing.png"))
    assert not outcome.ok and outcome.reason == trash.FAILED
    assert trash.explain(trash.FAILED) == "" and trash.fix_command(trash.FAILED) == ""


# ---- inside a sandbox: the portal, never Qt's private trash ---------------------------------

def test_the_portal_is_given_a_file_opened_for_writing(tmp_path, in_flatpak, monkeypatch):
    path = tmp_path / "pic.png"
    path.write_bytes(b"x")
    portal = FakePortal(1)
    monkeypatch.setattr(trash, "_call_portal", portal)
    assert trash.move_to_trash(str(path)) == trash.Outcome(True)
    assert portal.seen == [os.O_RDWR]                       # the portal only takes a descriptor opened read/write


def test_a_refusal_leaves_the_file_alone_and_does_not_use_qt(tmp_path, in_flatpak, monkeypatch):
    path = tmp_path / "pic.png"
    path.write_bytes(b"keep me")
    monkeypatch.setattr(trash, "_call_portal", FakePortal(0))
    monkeypatch.setattr(trash.QFile, "moveToTrash", staticmethod(lambda p: pytest.fail("Qt's private trash was used")))
    outcome = trash.move_to_trash(str(path))
    assert outcome == trash.Outcome(False, trash.REFUSED)
    assert path.read_bytes() == b"keep me"


def test_no_portal_is_reported(tmp_path, in_flatpak, monkeypatch):
    path = tmp_path / "pic.png"
    path.write_bytes(b"x")
    monkeypatch.setattr(trash, "_call_portal", lambda fd: None)
    assert trash.move_to_trash(str(path)) == trash.Outcome(False, trash.UNAVAILABLE)
    assert path.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anything")
def test_a_read_only_file_is_not_offered_to_the_portal(tmp_path, in_flatpak, monkeypatch):
    path = tmp_path / "pic.png"
    path.write_bytes(b"x")
    path.chmod(0o444)
    portal = FakePortal(1)
    monkeypatch.setattr(trash, "_call_portal", portal)
    assert trash.move_to_trash(str(path)) == trash.Outcome(False, trash.NOT_WRITABLE)
    assert portal.seen == []


def test_folders_and_links_are_never_offered_and_a_link_is_not_followed(tmp_path, in_flatpak, monkeypatch):
    portal = FakePortal(1)
    monkeypatch.setattr(trash, "_call_portal", portal)
    folder = tmp_path / "dir"
    folder.mkdir()
    target = tmp_path / "real.png"
    target.write_bytes(b"x")
    link = tmp_path / "link.png"
    os.symlink(str(target), str(link))
    assert trash.move_to_trash(str(folder)) == trash.Outcome(False, trash.NOT_A_FILE)
    assert trash.move_to_trash(str(link)) == trash.Outcome(False, trash.NOT_A_FILE)
    assert portal.seen == [] and target.exists()            # the link's target was never at risk


def test_a_file_that_is_gone_is_a_plain_failure(tmp_path, in_flatpak, monkeypatch):
    monkeypatch.setattr(trash, "_call_portal", FakePortal(1))
    assert trash.move_to_trash(str(tmp_path / "gone.png")) == trash.Outcome(False, trash.FAILED)


# ---- talking to the portal -------------------------------------------------------------------

class FakeReply:
    def __init__(self, kind, args=(), error=""):
        self._kind, self._args, self._error = kind, list(args), error
    def type(self): return self._kind
    def arguments(self): return self._args
    def errorMessage(self): return self._error


class FakeInterface:
    valid, reply, calls = True, None, []
    def __init__(self, *args): pass
    def isValid(self): return type(self).valid
    def call(self, method, *args):
        type(self).calls.append((method, len(args)))
        return type(self).reply


def test_the_portal_call_and_its_answers(monkeypatch, tmp_path):
    monkeypatch.setattr(trash, "QDBusInterface", FakeInterface)
    monkeypatch.setattr(trash, "QDBusUnixFileDescriptor", lambda fd: ("fd", fd))
    path = tmp_path / "f"
    path.write_bytes(b"x")
    fd = os.open(path, os.O_RDWR)
    try:
        FakeInterface.valid, FakeInterface.calls = True, []
        FakeInterface.reply = FakeReply(QDBusMessage.MessageType.ReplyMessage, [1])
        assert trash._call_portal(fd) == 1
        FakeInterface.reply = FakeReply(QDBusMessage.MessageType.ReplyMessage, [0])
        assert trash._call_portal(fd) == 0
        FakeInterface.reply = FakeReply(QDBusMessage.MessageType.ErrorMessage, [], "boom")
        assert trash._call_portal(fd) is None
        FakeInterface.reply = FakeReply(QDBusMessage.MessageType.ReplyMessage, [])
        assert trash._call_portal(fd) is None
        FakeInterface.valid = False                          # no portal on the bus
        assert trash._call_portal(fd) is None
        assert FakeInterface.calls[0] == ("TrashFile", 1)
    finally:
        os.close(fd)


# ---- the messages --------------------------------------------------------------------------------

def test_only_a_refusal_comes_with_the_fix_command():
    assert trash.fix_command(trash.REFUSED) == "chmod 700 ~/.local/share/Trash/files ~/.local/share/Trash/info"
    for reason in (trash.UNAVAILABLE, trash.NOT_WRITABLE, trash.NOT_A_FILE, trash.FAILED, ""):
        assert trash.fix_command(reason) == ""
    assert "terminal" in trash.explain(trash.REFUSED) and "KDE" in trash.explain(trash.REFUSED)
    assert all(trash.explain(r) for r in (trash.REFUSED, trash.UNAVAILABLE, trash.NOT_WRITABLE, trash.NOT_A_FILE))


# ---- through MediaActions, as the app uses it --------------------------------------------------

def test_a_refused_trash_keeps_files_rows_and_explains(tmp_path, monkeypatch, qapp):
    files = []
    for name in ("a.png", "b.png", "c.png"):
        path = tmp_path / name
        path.write_bytes(b"x")
        files.append(path)
    ids = [media_id(p) for p in files]
    actions = MediaActions()
    changes = []
    actions.trashProblemChanged.connect(lambda: changes.append(actions.trashProblem))
    monkeypatch.setattr(mediaActions, "_trash", lambda p: trash.Outcome(False, trash.REFUSED))
    assert actions.moveToTrash(ids) == []
    assert all(p.exists() for p in files)                                  # nothing moved
    assert get_database().get_media_paths(ids) == {i: str(p) for i, p in zip(ids, files)}   # rows kept: the user can retry
    assert "portal" in actions.trashProblem and actions.trashFixCommand.startswith("chmod 700")
    assert len(changes) == 1


def test_a_partial_success_removes_only_what_moved(tmp_path, monkeypatch, qapp):
    good, bad = tmp_path / "good.png", tmp_path / "bad.png"
    for p in (good, bad):
        p.write_bytes(b"x")
    ids = [media_id(good), media_id(bad)]

    def fake(path):
        if path.endswith("good.png"):
            os.remove(path)
            return trash.Outcome(True)
        return trash.Outcome(False, trash.REFUSED)

    actions = MediaActions()
    monkeypatch.setattr(mediaActions, "_trash", fake)
    assert actions.moveToTrash(ids) == [ids[0]]
    assert list(get_database().get_media_paths(ids)) == [ids[1]]            # the refused one stays in the library
    assert actions.trashProblem


def test_the_problem_clears_after_a_success(tmp_path, monkeypatch, qapp):
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    mid = media_id(path)
    actions = MediaActions()
    monkeypatch.setattr(mediaActions, "_trash", lambda p: trash.Outcome(False, trash.REFUSED))
    actions.moveToTrash([mid])
    assert actions.trashProblem
    monkeypatch.setattr(mediaActions, "_trash", lambda p: (os.remove(p), trash.Outcome(True))[1])
    assert actions.moveToTrash([mid]) == [mid]
    assert actions.trashProblem == "" and actions.trashFixCommand == ""


def test_a_plain_failure_has_nothing_to_explain(tmp_path, monkeypatch, qapp):
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    mid = media_id(path)
    actions = MediaActions()
    monkeypatch.setattr(mediaActions, "_trash", lambda p: trash.Outcome(False, trash.FAILED))
    assert actions.moveToTrash([mid]) == []
    assert actions.trashProblem == ""                                       # the app falls back to its short toast


def test_a_file_already_gone_counts_as_removed(tmp_path, monkeypatch, qapp):
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    mid = media_id(path)
    path.unlink()
    monkeypatch.setattr(mediaActions, "_trash", lambda p: pytest.fail("nothing to trash"))
    assert MediaActions().moveToTrash([mid]) == [mid]
