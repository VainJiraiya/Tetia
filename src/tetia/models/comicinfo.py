# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tags from a comic's ComicInfo.xml (the ComicRack format most taggers write: Mylar, Komga, Kavita, ComicTagger),
read from the archive in memory (no Qt Quick).

    Writer, Penciller, Inker, Colorist, Letterer, CoverArtist   creator tags
    Series                                                       a series tag
    Characters                                                   character tags
    Genre                                                        genre tags
    Tags                                                         content tags
    AgeRating                                                    the content rating (see AGE_RATINGS)
    Summary                                                      the description
    Manga = YesAndRightToLeft                                     the format "manga" (read right to left)

Lists are comma-separated. A file that has no ComicInfo.xml, or one that can't be read, gives nothing.
"""
import logging
import posixpath
import xml.etree.ElementTree as ElementTree

from tetia.models import archive
from tetia.models.tagimport import Imported

logger = logging.getLogger(__name__)

MAX_BYTES = 1024 * 1024        # a ComicInfo.xml is a few KB; anything bigger is not one

CREATOR_FIELDS = ("Writer", "Penciller", "Inker", "Colorist", "Letterer", "CoverArtist")
LIST_FIELDS = (("Characters", "character"), ("Genre", "genre"), ("Tags", "content"))

# ComicInfo's age ratings, as Tetia's content ratings (0 general, 2 mature, 3 explicit). An age rating says who may
# read it, not how suggestive it is, so nothing maps to 1; "Rating Pending" and "Unknown" set nothing.
AGE_RATINGS = {
    "everyone": 0, "g": 0, "early childhood": 0, "everyone 10+": 0, "pg": 0, "kids to adults": 0, "teen": 0,
    "mature 17+": 2, "m": 2, "ma15+": 2,
    "adults only 18+": 3, "r18+": 3, "x18+": 3,
}


def _split(text: str) -> list:
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def parse(data: bytes) -> Imported:
    """What a ComicInfo.xml says, as an Imported (empty if it is not one)."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return Imported()
    if root.tag.split("}")[-1] != "ComicInfo":
        return Imported()
    fields = {child.tag.split("}")[-1]: (child.text or "").strip() for child in root}
    tags = []
    for name in CREATOR_FIELDS:
        tags += [("creator", person) for person in _split(fields.get(name, ""))]
    if fields.get("Series"):
        tags.append(("series", fields["Series"]))
    for name, category in LIST_FIELDS:
        tags += [(category, value) for value in _split(fields.get(name, ""))]
    unique = []
    for tag in tags:
        if tag not in unique:
            unique.append(tag)
    return Imported(tags=unique,
                    rating=AGE_RATINGS.get(fields.get("AgeRating", "").strip().lower()),
                    description=fields.get("Summary", ""),
                    format="manga" if fields.get("Manga", "").strip().lower() == "yesandrighttoleft" else "")


def read(path: str) -> Imported:
    """The ComicInfo.xml of the comic at `path` (in the archive's top folder, or the only one in it)."""
    try:
        with archive.open_archive(path) as comic:
            names = [n for n in comic.names() if posixpath.basename(n).lower() == "comicinfo.xml"]
            if not names:
                return Imported()
            names.sort(key=lambda n: n.count("/"))         # the top one first
            return parse(comic.read(names[0], MAX_BYTES))
    except archive.ArchiveError:
        return Imported()
    except Exception:
        logger.warning("A ComicInfo.xml could not be read")
        return Imported()
