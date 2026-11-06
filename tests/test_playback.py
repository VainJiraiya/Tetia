# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import subprocess
import time

import pytest

from tetia.models import covers, mpv, playbackStore as pb
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel

LONG = 45 * 60


def test_only_videos_of_15_minutes_or_more_are_tracked():
    assert not pb.tracked(14 * 60 + 59) and pb.tracked(15 * 60)


def test_where_a_video_resumes():
    assert pb.resume_position(600, 10 * 60, False) == 0                  # a clip always starts over
    assert pb.resume_position(20, LONG, False) == 0                       # stopped at the very start
    assert pb.resume_position(1200, LONG, False) == 1197                  # a few seconds early
    assert pb.resume_position(LONG * 0.96, LONG, False) == 0              # nearly at the end: start over
    assert pb.resume_position(1200, LONG, True) == 0                      # watched: start over
    assert pb.is_finished(LONG * 0.95, LONG) and not pb.is_finished(LONG * 0.9, LONG)
    assert not pb.is_finished(500, 500)                                   # a clip is never "watched"


@pytest.fixture
def library(tmp_path, qapp):
    """A folder of three video files the library knows (the files are fake: only their rows matter here)."""
    folder = tmp_path / "Show"
    folder.mkdir()
    for n in (1, 2, 3):
        (folder / ("Show S01E0%d.mkv" % n)).write_bytes(b"x" * 20)
    get_database().add_folder(covers.folder_uri(str(folder)), "videos")
    MediaModel().load_from_qurl(str(folder))
    uris = [covers.folder_uri(str(folder / ("Show S01E0%d.mkv" % n))) for n in (1, 2, 3)]
    return {"folder": folder, "uris": uris, "store": pb.PlaybackStore()}


def test_a_long_video_is_remembered_and_resumed(library):
    store, (one, two, _) = library["store"], library["uris"]
    assert store.resumeFor(one) == 0
    store.save(one, 1200, LONG)
    assert store.resumeFor(one) == 1197
    store.save(one, 5, 600)                                               # a clip is not remembered: nothing changes
    assert store.resumeFor(one) == 1197
    store.save(one, 0, 0)
    store.save(two, 10, LONG)
    assert store.resumeFor(two) == 0                                      # too early to matter


def test_watching_to_the_end_marks_it_watched_for_good(library):
    store, (one, _, _) = library["store"], library["uris"]
    store.save(one, LONG * 0.97, LONG)                                    # stopped in the credits
    assert store.episodes([one])[0]["finished"] is True
    store.save(one, 900, LONG)                                            # watched a bit again: still watched
    row = store.episodes([one])[0]
    assert row["finished"] is True and row["fraction"] == 1.0 and store.resumeFor(one) == 0
    store.forget(one)
    row = store.episodes([one])[0]
    assert row["finished"] is False and row["duration"] == 0


def test_the_show_page_gets_progress_for_every_episode(library):
    store, (one, two, three) = library["store"], library["uris"]
    store.markFinished(one, LONG)
    store.save(two, 1350, LONG)
    rows = {r["uri"]: r for r in store.episodes([one, two, three])}
    assert rows[one]["finished"] and rows[one]["fraction"] == 1.0
    assert not rows[two]["finished"] and abs(rows[two]["fraction"] - 0.5) < 0.001 and rows[two]["duration"] == LONG
    assert rows[three] == {"uri": three, "position": 0.0, "duration": 0.0, "finished": False, "fraction": 0.0}


def test_a_file_the_library_does_not_know_is_ignored(library, tmp_path):
    stranger = covers.folder_uri(str(tmp_path / "Elsewhere.mkv"))
    library["store"].save(stranger, 1200, LONG)
    assert library["store"].resumeFor(stranger) == 0
    library["store"].markFinished(stranger, LONG)


def test_playback_records_go_with_the_file(library):
    (one, _, _), store = library["uris"], library["store"]
    store.save(one, 1200, LONG)
    db = get_database()
    media_id = db.get_media_by_path(os.path.realpath(str(library["folder"] / "Show S01E01.mkv")))[0]
    assert db.get_playback(media_id)["position"] == 1200
    db.conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    db.conn.commit()
    assert db.get_playback(media_id) is None                              # cascades


def test_a_length_learned_without_playing_leaves_the_position_alone(library):
    store, (one, _, _) = library["store"], library["uris"]
    store.save(one, 1200, LONG)
    media_id = get_database().get_media_by_path(os.path.realpath(str(library["folder"] / "Show S01E01.mkv")))[0]
    get_database().set_duration(media_id, LONG + 60)
    row = get_database().get_playback(media_id)
    assert row["position"] == 1200 and row["duration"] == LONG + 60


@pytest.mark.skipif(not mpv.available() or shutil.which("ffmpeg") is None, reason="needs libmpv and ffmpeg")
def test_the_background_probe_learns_how_long_videos_are(tmp_path, qapp):
    folder = tmp_path / "Clips"
    folder.mkdir()
    for n in (1, 2):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=%d" % (n + 1),
                        "-c:v", "libx264", str(folder / ("c%d.mkv" % n))], check=True)
    get_database().add_folder(covers.folder_uri(str(folder)), "videos")
    MediaModel().load_from_qurl(str(folder))
    uris = [covers.folder_uri(str(folder / ("c%d.mkv" % n))) for n in (1, 2)]
    store = pb.PlaybackStore()
    store.probe(uris)
    end = time.time() + 15
    rows = []
    while time.time() < end:
        rows = store.episodes(uris)
        if all(r["duration"] > 0 for r in rows):
            break
        time.sleep(0.1)
    assert [round(r["duration"]) for r in rows] == [2, 3]
    store.probe(uris)                                                     # known now: nothing more to do
    store.stop_probe()


def test_video_tiles_know_how_far_they_were_watched(library):
    store, (one, two, three) = library["store"], library["uris"]
    store.markFinished(one, LONG)
    store.save(two, 1350, LONG)
    media = MediaModel()
    media.load_from_qurl(str(library["folder"]))
    by_name = {i["file_name"]: i for i in media._visible_items}
    first, second, third = (by_name["Show S01E0%d.mkv" % n] for n in (1, 2, 3))
    assert first["watched"] is True and first["watch_fraction"] == 1.0
    assert second["watched"] is False and abs(second["watch_fraction"] - 0.5) < 0.001
    assert third["watched"] is False and third["watch_fraction"] == 0.0
    # the roles QML reads
    rows = {media.data(media.index(r), MediaModel.Roles.FileNameRole): r for r in range(media.rowCount())}
    r2 = media.index(rows["Show S01E02.mkv"])
    assert abs(media.data(r2, MediaModel.Roles.WatchFractionRole) - 0.5) < 0.001
    assert media.data(media.index(rows["Show S01E01.mkv"]), MediaModel.Roles.IsWatchedRole) is True
    # after watching more, a refresh updates the page without reloading it
    changed = []
    media.dataChanged.connect(lambda *a: changed.append(1))
    store.save(two, 2000, LONG)
    media.refreshPlayback()
    assert changed and media.data(r2, MediaModel.Roles.WatchFractionRole) > 0.7


def test_play_from_beginning_forgets_the_position_but_keeps_the_length(library):
    store, (one, two, _) = library["store"], library["uris"]
    store.save(one, 1350, LONG)
    assert store.resumeFor(one) > 0
    store.restart(one)
    row = store.episodes([one])[0]
    assert store.resumeFor(one) == 0 and row["position"] == 0 and row["duration"] == LONG and not row["finished"]
    store.markFinished(two, LONG)
    store.save(two, 900, LONG)
    store.restart(two)                                                    # watching again does not unwatch it
    assert store.episodes([two])[0]["finished"] is True
