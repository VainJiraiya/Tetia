# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import shutil
import subprocess
import time

import pytest

from tetia.models import mpv, player

pytestmark = [
    pytest.mark.skipif(not mpv.available(), reason="libmpv is not installed"),
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is needed to make a test video"),
]


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """Three seconds of video with two audio tracks (Japanese, English) and a subtitle track."""
    folder = tmp_path_factory.mktemp("clip")
    srt = folder / "subs.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n")
    out = folder / "clip.mkv"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
        "-i", str(srt), "-map", "0", "-map", "1", "-map", "2", "-map", "3",
        "-c:v", "libx264", "-c:a", "aac", "-c:s", "srt",
        "-metadata:s:a:0", "language=jpn", "-metadata:s:a:1", "language=eng", "-metadata:s:s:0", "language=eng",
        str(out)], check=True)
    return str(out)


def wait_for(check, seconds=8):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_the_binding_loads_a_file_and_reads_its_properties(clip):
    engine = mpv.Mpv({"vo": "null", "ao": "null", "terminal": "no", "keep-open": "yes"})
    try:
        assert engine.command("loadfile", clip, "replace")
        assert wait_for(lambda: engine.get_double("duration") is not None)
        assert 2.5 < engine.get_double("duration") < 3.5
        kinds = [t["type"] for t in engine.tracks()]
        assert kinds.count("video") == 1 and kinds.count("audio") == 2 and kinds.count("sub") == 1
        assert engine.set("pause", True) and engine.get_flag("pause") is True
    finally:
        engine.close()
    assert engine.get("duration") is None and engine.command("stop") is False      # closed: nothing crashes


def test_track_labels_use_the_language_then_the_title():
    assert player.track_label({"lang": "jpn", "title": ""}, 1) == "Japanese"
    assert player.track_label({"lang": "eng", "title": "Commentary"}, 2) == "English - Commentary"
    assert player.track_label({"lang": "eng", "title": "English"}, 2) == "English"
    assert player.track_label({"lang": "", "title": ""}, 3) == "Track 3"


@pytest.fixture
def quiet_player(qapp):
    player.Player._extra_options = {"vo": "null", "ao": "null"}
    p = player.Player()
    yield p
    p.shutdown()
    player.Player._extra_options = {}


def test_the_player_follows_playback_and_the_controls(quiet_player, clip):
    p = quiet_player
    assert p.available is True
    p.load(clip, 0)
    assert wait_for(lambda: (p._poll(), p.loaded)[1])
    assert 2.5 < p.duration < 3.5 and p.paused is False
    assert [t["label"] for t in p.audioTracks] == ["Japanese", "English"]
    assert [t["label"] for t in p.subtitleTracks] == ["English"]
    assert [t["selected"] for t in p.audioTracks] == [True, False]
    p.setAudioTrack(p.audioTracks[1]["id"])
    assert wait_for(lambda: (p._poll(), [t["selected"] for t in p.audioTracks])[1] == [False, True])
    p.setPaused(True)
    p.seekTo(1.5)
    assert wait_for(lambda: (p._poll(), abs(p.position - 1.5) < 0.3)[1])
    p.seek(-1.0)
    assert wait_for(lambda: (p._poll(), p.position < 1.0)[1])
    p.setVolume(40)
    p.toggleMute()
    p._poll()
    assert p.volume == 40 and p.muted is True
    p.setSpeed(2)
    p._poll()
    assert p.speed == 2.0


def test_the_player_reports_the_end_and_starts_over(quiet_player, clip):
    p = quiet_player
    ends = []
    p.endReached.connect(lambda: ends.append(1))
    p.load(clip, 0)
    assert wait_for(lambda: (p._poll(), p.ended)[1], seconds=10)
    assert ends == [1]
    p.setPaused(False)                       # play again from the start
    assert wait_for(lambda: (p._poll(), not p.ended)[1])


def test_a_start_past_the_end_starts_over_and_does_not_end(quiet_player, clip):
    p = quiet_player
    ends = []
    p.endReached.connect(lambda: ends.append(1))
    p.load(clip, 600)                      # remembered from a longer file that had this name
    assert wait_for(lambda: (p._poll(), p.loaded and not p._restarting)[1])
    assert p.position < 2.0 and p.ended is False and ends == []


def test_a_file_that_cannot_play_is_an_error(quiet_player, tmp_path):
    bad = tmp_path / "broken.mkv"
    bad.write_bytes(b"not a video")
    quiet_player.load(str(bad), 0)
    assert wait_for(lambda: (quiet_player._poll(), quiet_player.error)[1] != "")
    assert quiet_player.loaded is False


def test_shutting_a_player_down_closes_mpv(qapp, clip):
    """A page that is closed must not leave the video playing (and its sound) in the background."""
    player.Player._extra_options = {"vo": "null", "ao": "null"}
    try:
        before = mpv.live_count()
        p = player.Player()
        p.load(clip, 0)
        assert wait_for(lambda: (p._poll(), p.loaded)[1])
        assert mpv.live_count() == before + 1
        p.shutdown()
        assert mpv.live_count() == before
        p.shutdown()                          # a second call is harmless
    finally:
        player.Player._extra_options = {}


def test_a_skip_lands_where_it_says(quiet_player, clip):
    p = quiet_player
    p.load(clip, 0)
    assert wait_for(lambda: (p._poll(), p.loaded)[1])
    p.setPaused(True)
    p.seekTo(0.5)
    assert wait_for(lambda: (p._poll(), abs(p.position - 0.5) < 0.05)[1])
    p.seek(1.0)
    assert wait_for(lambda: (p._poll(), abs(p.position - 1.5) < 0.05)[1])      # exactly, not at the next keyframe


@pytest.fixture
def folder_with_extras(tmp_path):
    """Movie.mkv (one audio track, no subtitles) with a subtitle file beside it, one in Subs/, and a separate audio file."""
    movie = tmp_path / "Movie.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac",
                    "-metadata:s:a:0", "language=eng", str(movie)], check=True)
    cue = "1\n00:00:00,000 --> 00:00:02,000\nHello\n"
    (tmp_path / "Movie.eng.srt").write_text(cue)
    (tmp_path / "Subs").mkdir()
    (tmp_path / "Subs" / "Movie.fre.srt").write_text(cue)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
                    "-c:a", "libopus", "-metadata:s:a:0", "language=jpn", str(tmp_path / "Movie.jpn.mka")], check=True)
    return str(movie)


def test_separate_subtitle_and_audio_files_beside_a_video_are_found(quiet_player, folder_with_extras):
    p = quiet_player
    p.load(folder_with_extras, 0)
    assert wait_for(lambda: (p._poll(), p.loaded and len(p.subtitleTracks) >= 2 and len(p.audioTracks) >= 2)[1])
    subs = sorted(t["label"] for t in p.subtitleTracks)
    audio = sorted(t["label"] for t in p.audioTracks)
    assert subs == ["English (external)", "French (external)"]       # the one beside it and the one in Subs/
    assert audio == ["English", "Japanese (external)"]                # the video's own track and the separate file
    assert player.track_label({"lang": "eng", "title": "", "external": True}, 1) == "English (external)"
