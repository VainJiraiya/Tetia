# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tags from the metadata gallery-dl writes beside a download (--write-metadata, or its "metadata" post
processor): <file>.<ext>.json, or <name>.json (no Qt Quick).

What the file holds depends on the site; its "category" field names it. Read here:

    Danbooru            tag_string_artist / _character / _copyright / _general; rating g s q e (s: sensitive)
    other boorus        tags_artist / tags_character / tags_copyright / tags_general (gallery-dl's "tags" option)
    e621 and the like   tags: {"artist": [...], "character": [...], "copyright": [...], "general": [...], ...}
    E-Hentai            tags: ["artist:...", "parody:...", "character:...", "female:...", ...]
    Pixiv               user.name, tags, x_restrict (R-18)
    Twitter / X         author.name, hashtags
    yt-dlp              <name>.info.json: uploader / channel, tags, categories (genre), age_limit (18: mature)
    anything else       tags (a list, or words separated by spaces), artist / author / user / uploader

Artists and circles become creator tags, copyrights and parodies series tags, characters character tags, and the
rest content tags. A booru's rating sets the content rating where the file has none.
"""
import json
import logging
import os

from tetia.models.tagimport import Imported

logger = logging.getLogger(__name__)

MAX_BYTES = 4 * 1024 * 1024

# A booru's rating letter or word, as Tetia's content rating. Danbooru's "s" is "sensitive"; elsewhere it is "safe".
_RATINGS = {"g": 0, "general": 0, "safe": 0, "sensitive": 1, "questionable": 2, "q": 2, "explicit": 3, "e": 3}
_SENSITIVE_S = {"danbooru", "aibooru"}

_BOORU_FIELDS = (("artist", "creator"), ("character", "character"), ("copyright", "series"), ("general", "content"),
                 ("species", "content"))
_EHENTAI = {"artist": "creator", "group": "creator", "parody": "series", "character": "character",
            "female": "content", "male": "content", "mixed": "content", "other": "content", "": "content"}


def sidecars(name: str) -> list:
    """The metadata file names gallery-dl (or yt-dlp) may have written for a file called `name`, the usual one
    first."""
    stem = os.path.splitext(name)[0]
    return [name + ".json", stem + ".json", stem + ".info.json"]


def _words(value) -> list:
    if isinstance(value, str):
        return [w for w in value.split() if w]
    if isinstance(value, (list, tuple)):
        return [str(w) for w in value if isinstance(w, (str, int)) and str(w).strip()]
    return []


def _name(value) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("nick") or value.get("username") or ""
    return value.strip() if isinstance(value, str) else ""


def _rating(data: dict):
    raw = data.get("rating")
    if isinstance(raw, str) and raw.strip():
        word = raw.strip().lower()
        if word == "s":
            return 1 if str(data.get("category", "")).lower() in _SENSITIVE_S else 0
        return _RATINGS.get(word)
    restrict = data.get("x_restrict")                    # Pixiv: 0 all ages, 1 R-18, 2 R-18G
    if isinstance(restrict, int) and restrict > 0:
        return 3
    age = data.get("age_limit")                          # yt-dlp: the site's age restriction
    if isinstance(age, int) and age >= 18:
        return 2
    return None


def parse(data) -> Imported:
    """What one gallery-dl metadata file says, as an Imported (empty when it says nothing usable)."""
    if not isinstance(data, dict):
        return Imported()
    tags = []
    # Danbooru-style strings, then the "tags" option of other boorus
    for prefix in ("tag_string_", "tags_"):
        for field, category in _BOORU_FIELDS:
            tags += [(category, w) for w in _words(data.get(prefix + field))]
    raw = data.get("tags")
    if isinstance(raw, dict):                            # e621: grouped by category
        for field, category in _BOORU_FIELDS:
            tags += [(category, w) for w in _words(raw.get(field))]
    elif not any(data.get(p + "general") for p in ("tag_string_", "tags_")):
        for word in _words(raw) if isinstance(raw, list) else _words(raw):
            space, sep, rest = word.partition(":")       # E-Hentai: "namespace:tag"
            if sep and space in _EHENTAI:
                if rest.strip():
                    tags.append((_EHENTAI[space], rest.strip()))
            elif sep:
                continue                                 # (language:, reclass:... say nothing about the picture)
            else:
                tags.append(("content", word))
    for key in ("hashtags",):
        tags += [("content", w) for w in _words(data.get(key))]
    tags += [("genre", w) for w in (data.get("categories") or []) if isinstance(w, str) and w.strip()]
    for key in ("artist", "artists", "author", "user", "uploader", "channel"):
        value = data.get(key)
        names = [_name(v) for v in value] if isinstance(value, list) else [_name(value)]
        tags += [("creator", n) for n in names if n]
    for key in ("characters",):
        tags += [("character", w) for w in (data.get(key) or []) if isinstance(w, str)]
    unique = []
    for tag in tags:
        if tag not in unique:
            unique.append(tag)
    return Imported(tags=unique, rating=_rating(data))


def read(folder: str, name: str, listed: set) -> Imported:
    """The metadata beside the file `name` in `folder`, if gallery-dl wrote one (`listed`: the folder's file
    names, so nothing is looked up on the disk that is not there)."""
    for sidecar in sidecars(name):
        if sidecar in listed:
            path = os.path.join(folder, sidecar)
            try:
                if os.path.getsize(path) > MAX_BYTES:
                    return Imported()
                with open(path, "rb") as f:
                    return parse(json.loads(f.read()))
            except (OSError, ValueError):
                return Imported()
    return Imported()
