# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The episodes of a show: a folder (the show) holding season folders that hold the episode files.

Plain functions with no Qt. Episode and season numbers come from the names, as chapters' do in series.py:
S01E02, S1E2, "Season 1 Episode 2", 1x02, "Ep 12", and a bare number as in "Dragon Ball 001" (read as a number,
so 001 comes before 100). A season folder is "Season 2", "S02", "Specials" (season 0), or any other name (then its
place comes from the numbers of its episodes, else from its name).
"""
import os
import re
from pathlib import Path

from tetia.models import covers
from tetia.models.scanner import VIDEO_EXTENSIONS

# An episode number is whole, or ends in .5 (9.5 is a recap or special between episodes 9 and 10). Only .5: other
# decimals in a name are things like the 5.1 of an audio track.
_NUM = r"\d{1,4}(?:\.5)?"
_SXXEXX = re.compile(r"(?<![a-z0-9])s(\d{1,3})\s*[ ._-]?\s*e(%s)(?![\d])" % _NUM, re.IGNORECASE)
_LONG = re.compile(r"season\s*(\d{1,3})\W{0,4}(?:episode|ep)\.?\s*(%s)" % _NUM, re.IGNORECASE)
_NXNN = re.compile(r"(?<![\dxX])(\d{1,2})x(\d{2,3})(?!\d)")
_EPISODE = re.compile(r"(?<![a-z])e(?:p(?:isode)?)?\.?\s*(%s)(?!\d)" % _NUM, re.IGNORECASE)
_SEASON_FOLDER = re.compile(r"^(?:season|series|staffel|saison)[\s._-]*(\d{1,3})\b|^s[\s._-]*(\d{1,3})$", re.IGNORECASE)
# what is not a number of the episode: [groups], (years), resolutions, codecs
_NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\b\d{3,4}p\b|\b[xh]\.?26[45]\b|\b\d{1,2}[- ]?bit\b|\b(?:hevc|flac|aac|ac3|dts|web|bd|dvd)\w*\b",
                    re.IGNORECASE)
# a release name's own words (where it came from, how it was encoded); only taken out of names that look like releases
_TECH = re.compile(r"\b(?:\d{3,4}p|[xh]\.?26[45]|hevc|web[-. ]?(?:dl|rip)|blu[-. ]?ray|bd[-. ]?rip|hdtv|dvd[-. ]?rip)\b", re.IGNORECASE)
_RELEASE = re.compile(r"\b(?:web[-. ]?dl|web[-. ]?rip|blu[-. ]?ray|bd[-. ]?rip|dvd[-. ]?rip|hdtv|hdrip|amzn|amazon|netflix|nf|hulu|"
                      r"dsnp|disney|hmax|atvp|pcok|repack|proper|remux|dual[-. ]?audio|multi|ddp?[0-9][. ]?[0-9]|aac[0-9. ]*|opus)\b",
                      re.IGNORECASE)
_SEASON_IN_NAME = re.compile(r"[\s._-]*\b(?:season|series|s)[\s._-]*\d+\b.*$", re.IGNORECASE)
_STANDALONE = re.compile(r"(?<![\w.])(%s)(?![\w])" % _NUM)
_SPECIALS = {"specials", "special", "extras", "ova", "ovas"}


def _number(text: str):
    """"9" -> 9, "9.5" -> 9.5"""
    return float(text) if "." in text else int(text)


def number_text(number) -> str:
    """9 -> "9", 9.5 -> "9.5" """
    return "%g" % number


def parse_episode(name: str) -> tuple:
    """(season, episode) of a file name; either is None when the name does not say. The episode is a whole number,
    or one and a half (9.5) for a recap or special between two episodes."""
    stem = Path(name).stem
    for pattern in (_SXXEXX, _LONG, _NXNN):
        found = pattern.search(stem)
        if found:
            return int(found.group(1)), _number(found.group(2))
    found = _EPISODE.search(_NOISE.sub(" ", stem))
    if found:
        return None, _number(found.group(1))
    numbers = _STANDALONE.findall(_NOISE.sub(" ", stem))
    return (None, _number(numbers[-1])) if numbers else (None, None)


def parse_season_folder(name: str):
    """The season number a folder's name gives (Specials: 0), or None."""
    if name.strip().casefold() in _SPECIALS:
        return 0
    found = _SEASON_FOLDER.match(name.strip())
    if found:
        return int(found.group(1) or found.group(2))
    return None


def show_name(folder_name: str) -> str:
    """A show folder's name without the tags, year and season that downloads add:
    "Rick and Morty - Season 3 (2017) [1080p]" -> "Rick and Morty"."""
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", folder_name)
    name = _SEASON_IN_NAME.sub("", name)
    return re.sub(r"\s+", " ", name.replace(".", " ").replace("_", " ")).strip(" -") or folder_name


def episode_title(name: str, number, show: str = "") -> str:
    """What is left of a file name once the extension, tags, resolution, the show's name and the episode number are
    taken out ("Episode 3" if nothing is)."""
    stem = Path(name).stem
    if _TECH.search(stem):
        stem = re.sub(r"-[A-Za-z0-9]+$", "", stem)          # the release group: "...x264-Group"
        stem = _RELEASE.sub(" ", stem)
    stem = _NOISE.sub(" ", stem)
    for pattern in (_SXXEXX, _LONG, _NXNN, _EPISODE):
        stem = pattern.sub(" ", stem)
    if number is not None:       # before the dots become spaces: "9.5" is one number
        stem = re.sub(r"(?<![\w.])0*%s(?![\w])" % re.escape(number_text(number)), " ", stem, count=1)
    stem = re.sub(r"[._]+", " ", stem)
    wanted = re.sub(r"[\W_]+", " ", show).strip().casefold()
    if wanted and re.sub(r"[\W_]+", " ", stem).strip().casefold().startswith(wanted):
        stem = re.sub(r"^\W*" + r"[\W_]+".join(re.escape(w) for w in wanted.split()), "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s+", " ", stem)
    stem = re.sub(r"^[\s\-–:]+|[\s\-–:]+$", "", stem)
    return stem.strip() or ("Episode %s" % number_text(number) if number is not None else Path(name).stem)


def _videos(folder: str) -> list[str]:
    try:
        return [e for e in os.listdir(folder)
                if not e.startswith(".") and Path(e).suffix.lower() in VIDEO_EXTENSIONS
                and os.path.isfile(os.path.join(folder, e))]
    except OSError:
        return []


def _subfolders(folder: str) -> list[str]:
    try:
        return [e for e in os.listdir(folder) if not e.startswith(".") and os.path.isdir(os.path.join(folder, e))]
    except OSError:
        return []


def _episodes(folder: str, names: list, season_hint, show: str = "") -> list[dict]:
    """The episodes among `names` (files of `folder`) in order: by number where they have one, else by name."""
    found = []
    for name in names:
        season, number = parse_episode(name)
        found.append({"path": os.path.join(folder, name), "file": name, "season": season if season is not None else season_hint,
                      "number": number})
    found.sort(key=lambda e: (e["number"] is None, e["number"] if e["number"] is not None else 0, covers.natural_key(e["file"])))
    for position, episode in enumerate(found, 1):
        if episode["number"] is None:
            episode["number"] = position
        episode["title"] = episode_title(episode["file"], episode["number"], show)
    return found


def seasons(show: str, depth: int = 2) -> list[dict]:
    """[{name, number, episodes: [{path, file, title, number, season}]}] in order. Season folders make the seasons
    (any folder below the show that holds videos); loose files make seasons by their S01E.. names, or one
    unnamed group ("Episodes") when they say none."""
    groups = []

    def walk(folder: str, level: int):
        names = _videos(folder)
        if names:
            hint = parse_season_folder(os.path.basename(folder)) if folder != show else None
            episodes = _episodes(folder, names, hint, show_name(os.path.basename(show.rstrip(os.sep))))
            if folder == show:
                by_season = {}
                for episode in episodes:
                    by_season.setdefault(episode["season"], []).append(episode)
                for number, items in by_season.items():
                    groups.append({"name": "Season %d" % number if number is not None else "Episodes",
                                   "number": number, "episodes": items})
            else:
                numbers = {e["season"] for e in episodes if e["season"] is not None}
                number = hint if hint is not None else (numbers.pop() if len(numbers) == 1 else None)
                groups.append({"name": os.path.basename(folder), "number": number, "episodes": episodes})
        if level < depth:
            for sub in _subfolders(folder):
                walk(os.path.join(folder, sub), level + 1)

    walk(show, 0)
    groups.sort(key=lambda g: (g["number"] is None, g["number"] if g["number"] is not None else 0,
                               covers.natural_key(g["name"])))
    return groups


def episode_paths(show: str) -> list[str]:
    """Every episode file of the show, in watching order."""
    return [e["path"] for group in seasons(show) for e in group["episodes"]]
