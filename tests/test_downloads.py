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


YT_STUB = '''#!{python}
import json, os, sys
args = sys.argv[1:]
folder = args[args.index("-P") + 1]
url = args[-1]
if "fail" in url:
    sys.stderr.write("ERROR: [youtube] abc123: Video unavailable\\n")
    sys.exit(1)
path = os.path.join(folder, "A Video [abc123].mp4")
with open(path, "wb") as f:
    f.write(b"not really a video")
with open(os.path.join(folder, "A Video [abc123].info.json"), "w") as f:
    json.dump({{"extractor": "youtube", "uploader": "Some Channel", "channel": "Some Channel",
               "tags": ["lofi", "study music"], "categories": ["Music"], "age_limit": 18}}, f)
print(path, flush=True)
'''


def _yt_stub(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "yt-dlp"
    script.write_text(YT_STUB.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))


def test_video_sites_go_to_yt_dlp_and_the_rest_to_gallery_dl():
    both = {"gallery-dl": ["g"], "yt-dlp": ["y"]}
    assert downloadService.tool_for("https://www.youtube.com/watch?v=x", both) == "yt-dlp"
    assert downloadService.tool_for("https://youtu.be/x", both) == "yt-dlp"
    assert downloadService.tool_for("https://danbooru.donmai.us/posts?tags=x", both) == "gallery-dl"
    assert downloadService.tool_for("https://danbooru.donmai.us/posts", {"gallery-dl": None, "yt-dlp": ["y"]}) == "yt-dlp"
    assert downloadService.tool_for("https://youtube.com/x", {"gallery-dl": ["g"], "yt-dlp": None}) == "gallery-dl"
    assert downloadService.tool_for("https://x", {"gallery-dl": None, "yt-dlp": None}) == ""
    assert downloadService._short("ERROR: [youtube] abc123: Video unavailable") == "abc123: Video unavailable"
    assert downloadService._short("[danbooru][error] Unsupported URL") == "Unsupported URL"


def test_a_video_download_lands_with_its_info_json_tags(tmp_path, monkeypatch, qapp):
    _yt_stub(tmp_path, monkeypatch)
    folder = tmp_path / "Videos"
    folder.mkdir()
    service = DownloadService()
    assert "yt-dlp" in service.tools
    service.add("https://www.youtube.com/watch?v=abc123", str(folder))
    assert service.jobs[0]["tool"] == "yt-dlp"
    assert _wait(service, lambda: service.jobs[0]["state"] == "done") and service.jobs[0]["files"] == 1
    db = get_database()
    media_id = db.get_media_by_path(os.path.realpath(str(folder / "A Video [abc123].mp4")))[0]
    tags = {(r[0], r[1]) for r in db.conn.execute(
        "SELECT c.name, t.name FROM media_tag mt JOIN tag t ON t.id = mt.tag_id JOIN tag_category c "
        "ON c.id = t.category_id WHERE mt.media_id = ?", (media_id,))}
    assert tags == {("creator", "some_channel"), ("content", "lofi"), ("content", "study_music"), ("genre", "music")}
    assert db.conn.execute("SELECT rating FROM media WHERE id = ?", (media_id,)).fetchone()[0] == 2
    service.addWith("https://www.youtube.com/watch?v=fail", str(folder), "yt-dlp")
    assert _wait(service, lambda: service.jobs[-1]["state"] == "failed")
    assert service.jobs[-1]["message"] == "abc123: Video unavailable"


def test_the_options_become_the_tools_arguments():
    g = downloadService.command_for(["gallery-dl"], "u", "/f", "gallery-dl", first=1, last=200)
    assert g[g.index("--range") + 1] == "1-200" and g[-2:] == ["--", "u"]
    assert g[g.index("-o") + 1] == "extractor.tags=true"             # the boorus' tag categories
    y = downloadService.command_for(["yt-dlp"], "u", "/f", "yt-dlp", last=20, height=1080)
    assert y[y.index("--playlist-items") + 1] == ":20" and y[y.index("-S") + 1] == "res:1080"
    plain = downloadService.command_for(["yt-dlp"], "u", "/f", "yt-dlp")
    assert "--playlist-items" not in plain and "-S" not in plain
    assert downloadService.clean_folder_name(" Frieren / art ") == "Frieren - art"
    assert downloadService.clean_folder_name("..") == "" and downloadService.clean_folder_name(".hidden") == ""


def test_a_download_into_a_new_folder_and_onto_a_new_board(tmp_path, monkeypatch, qapp):
    from tetia.models import boards, covers
    from tetia.models.searchModel import _Resolver
    _stub(tmp_path, monkeypatch)
    folder = tmp_path / "Art"
    folder.mkdir()
    get_database().add_folder(covers.folder_uri(str(folder)), "photos")   # (a board shows what is in the library)
    service = DownloadService()
    filled = []
    service.boardFilled.connect(lambda b: filled.append(b))
    service.download("https://example.org/posts", str(folder), "", {"subfolder": "Sky pictures", "boardName": "Skies",
                                                                    "tab": "photos", "last": 50})
    assert _wait(service, lambda: service.jobs[0]["state"] == "done")
    assert (folder / "Sky pictures" / "pic0.png").exists()
    db = get_database()
    assert len(filled) == 1
    board = boards.get(db, filled[0])
    assert board["name"] == "Skies" and board["tab"] == "photos"
    assert len(boards.members(db, _Resolver(db), filled[0])) == 2
    service.download("https://example.org/again", str(folder), "", {"subfolder": "Sky pictures", "board": filled[0]})
    assert _wait(service, lambda: service.jobs[-1]["state"] == "done")
    assert len(filled) == 2 and filled[1] == filled[0]                 # the existing board, not a new one


def test_the_tools_configs_are_named_not_read(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    opened = []
    monkeypatch.setattr(downloadService.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    monkeypatch.setattr(downloadService, "gallery_dl_command", lambda: None)
    service = DownloadService()
    assert not service.hasConfig("gallery-dl") and service.gallerySites() == []
    service.openConfig("yt-dlp")
    assert service.hasConfig("yt-dlp") and opened == [str(tmp_path / "config" / "yt-dlp" / "config")]
    gdl = tmp_path / "config" / "gallery-dl" / "config.json"
    gdl.parent.mkdir(parents=True)
    gdl.write_text('{"extractor": {"gelbooru": {"api-key": "secret"}, "pixiv": {}, "base-directory": "~/x"}}')
    assert service.gallerySites() == ["gelbooru", "pixiv"]
    service.maxHeight = 1080
    assert DownloadService().maxHeight == 1080
