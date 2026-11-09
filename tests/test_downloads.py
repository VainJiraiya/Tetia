# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Downloads with gallery-dl (a stand-in here): files land in the chosen folder, are counted, scanned and tagged;
a failure says why, a download can be cancelled, and they run one at a time."""
import base64
import os
import stat
import sys
import time

from PySide6.QtCore import QCoreApplication

from tetia.models import downloadService
from tetia.models.database import get_database
from tetia.models.downloadService import DownloadService

PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415408d763f8cfc0000003010100"
    "18dd8db00000000049454e44ae426082")).decode()

STUB = '''#!{python}
import base64, json, os, sys, time
args = sys.argv[1:]
folder = args[args.index("-D") + 1]
url = args[-1]
if "fail" in url:
    sys.stderr.write("[site][error] Unsupported URL '%s'\\n" % url)
    sys.exit(64)
if "slow" in url:
    time.sleep(30)
for i in range(2):
    path = os.path.join(folder, "pic%d.png" % i)
    with open(path, "wb") as f:
        f.write(base64.b64decode("{png}"))
    with open(path + ".json", "w") as f:
        json.dump({{"category": "danbooru", "tag_string_general": "downloaded", "rating": "g"}}, f)
    print(path, flush=True)
print("# " + os.path.join(folder, "old.png"), flush=True)     # already there: skipped
'''


def _stub(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gallery-dl"
    script.write_text(STUB.format(python=sys.executable, png=PNG))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))


def _wait(service, done, timeout=15):
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return done()


def test_without_gallery_dl_nothing_is_offered(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(downloadService.importlib.util, "find_spec", lambda name: None)
    service = DownloadService()
    assert not service.available and service.add("https://example.org/x", str(tmp_path)) == 0


def test_a_download_lands_counted_scanned_and_tagged(tmp_path, monkeypatch, qapp):
    _stub(tmp_path, monkeypatch)
    folder = tmp_path / "Art"
    folder.mkdir()
    service = DownloadService()
    arrived = []
    service.downloaded.connect(lambda f: arrived.append(f))
    job_id = service.add("https://example.org/posts?tags=sky", "file://" + str(folder))
    assert job_id and service.busy
    assert _wait(service, lambda: service.jobs[0]["state"] == "done")
    assert service.jobs[0]["files"] == 2 and arrived == [str(folder)] and not service.busy
    db = get_database()
    media_id = db.get_media_by_path(os.path.realpath(str(folder / "pic0.png")))[0]
    tags = {r[0] for r in db.conn.execute(
        "SELECT t.name FROM media_tag mt JOIN tag t ON t.id = mt.tag_id WHERE mt.media_id = ?", (media_id,))}
    assert tags == {"downloaded"}
    service.clearFinished()
    assert service.jobs == []


def test_a_failure_says_why_and_the_queue_goes_on(tmp_path, monkeypatch, qapp):
    _stub(tmp_path, monkeypatch)
    folder = tmp_path / "Art"
    folder.mkdir()
    service = DownloadService()
    service.add("https://example.org/fail", str(folder))
    service.add("https://example.org/ok", str(folder))
    assert _wait(service, lambda: [j["state"] for j in service.jobs] == ["failed", "done"])
    assert service.jobs[0]["message"].startswith("Unsupported URL")


def test_a_download_can_be_cancelled_and_locking_stops_them(tmp_path, monkeypatch, qapp):
    _stub(tmp_path, monkeypatch)
    folder = tmp_path / "Art"
    folder.mkdir()
    service = DownloadService()
    first = service.add("https://example.org/slow", str(folder))
    second = service.add("https://example.org/slow-too", str(folder))
    assert _wait(service, lambda: service.jobs[0]["state"] == "downloading")
    service.cancel(second)                                            # still waiting: never starts
    service.cancel(first)
    assert _wait(service, lambda: [j["state"] for j in service.jobs] == ["cancelled", "cancelled"])
    service.add("https://example.org/slow", str(folder))
    assert _wait(service, lambda: service.jobs[-1]["state"] == "downloading")
    started = time.monotonic()
    service.stop()                                                    # a vault being locked
    assert time.monotonic() - started < 10 and service.add("https://example.org/x", str(folder)) == 0
