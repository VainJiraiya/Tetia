# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Search query parser and SQL builder. Pure Python, no Qt, so it can be tested
with plain unittest (see test_phase3_query.py).

Grammar (tokens split on whitespace; double quotes group one token):

    isekai            has this tag (or an alias, or any tag implying it);
                      if no such tag exists, matches the file name instead
    -chibi            does NOT have it
    ~a ~b             OR group: at least one of them
    fant*             wildcard over tag names/aliases
    creator:foo       tag restricted to a category (creator, series, character,
                      genre, content)
    type:video        image, video, comic, ebook (aliases: photo, manga, book)
    is:favorite       favourites only
    rating:explicit   general, suggestive, mature, explicit, unrated; also >=, <=, >, <, =
    name:starfall     case-insensitive substring of the file name; a quoted
                      "starfall" on its own means the same

All terms are ANDed (except the OR group). All user text goes in as bound
parameters, never into the SQL string.
"""
import json
import re
from dataclasses import dataclass

CATEGORIES = ("creator", "series", "character", "genre", "content")
METATAGS = ("creator", "series", "character", "genre", "content", "type", "is", "rating", "name")

KIND_ALIASES = {
    "image": "image", "photo": "image", "picture": "image",
    "video": "video", "movie": "video",
    "comic": "comic", "manga": "comic",
    "ebook": "ebook", "book": "ebook",
}
RATING_VALUES = {"general": 0, "suggestive": 1, "mature": 2, "explicit": 3}

_TOKEN = re.compile(r'(?:[^\s"]|"[^"]*"?)+')
_PARTS = re.compile(r'^(?P<neg>-)?(?P<or>~)?(?:(?P<key>[A-Za-z]+):)?(?P<value>.*)$', re.S)


@dataclass
class Term:
    kind: str          # word, wildcard, category, name, type, favorite, rating, unknown
    value: str = ""
    category: str = ""  # for kind == "category"
    negated: bool = False
    ored: bool = False
    raw: str = ""


def split_tokens(text: str) -> list[str]:
    """The raw tokens of a query, quotes kept ('name:"a b" c' -> 2 tokens)."""
    return _TOKEN.findall(text or "")


def _unquote(value: str) -> tuple[str, bool]:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1], True
    if value.startswith('"'):
        return value[1:], True
    return value, False


def parse(text: str) -> list[Term]:
    terms = []
    for raw in split_tokens(text):
        m = _PARTS.match(raw)
        key = (m.group("key") or "").lower()
        value, quoted = _unquote(m.group("value"))
        # A quoted token never carries a key: "a:b" is just a name
        if raw.lstrip("-~").startswith('"'):
            key = ""
        common = dict(negated=bool(m.group("neg")), ored=bool(m.group("or")), raw=raw)
        if not value.strip():
            continue
        if key in CATEGORIES:
            terms.append(Term("category", value.strip().lower(), category=key, **common))
        elif key == "name":
            terms.append(Term("name", value, **common))
        elif key == "type":
            terms.append(Term("type", value.strip().lower(), **common))
        elif key == "is":
            terms.append(Term("favorite" if value.strip().lower() in ("favorite", "favourite", "fav")
                              else "unknown", value.strip().lower(), **common))
        elif key == "rating":
            terms.append(Term("rating", value.strip().lower(), **common))
        elif key:
            terms.append(Term("unknown", raw, **common))
        elif quoted:
            terms.append(Term("name", value, **common))
        elif "*" in value:
            terms.append(Term("wildcard", value.strip().lower(), **common))
        else:
            terms.append(Term("word", value.strip().lower(), **common))
    return terms


def like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_rating(value: str):
    """'>=mature' -> (">=", 2); 'unrated' -> ("unrated", None); None if invalid."""
    m = re.match(r"^(>=|<=|>|<|=)?\s*([a-z]+|\d)$", value)
    if not m:
        return None
    op, word = m.group(1) or "=", m.group(2)
    if word == "unrated":
        return ("unrated", None) if op == "=" else None
    if word in RATING_VALUES:
        return (op, RATING_VALUES[word])
    if word.isdigit() and 0 <= int(word) <= 3:
        return (op, int(word))
    return None


def _clause(term: Term, resolver):
    """(sql, params) for one term, or None if it can't be understood (ignored).
    Not yet negated or OR-ed."""
    if term.kind in ("word", "wildcard", "category"):
        if term.kind == "word":
            ids = resolver.tag_ids(term.value, None)
            if not ids:   # not a tag: fall back to the file name
                return ("m.name LIKE ? ESCAPE '\\'", [f"%{like_escape(term.value)}%"])
        elif term.kind == "wildcard":
            ids = resolver.wildcard_ids(term.value, None)
        else:
            ids = resolver.tag_ids(term.value, term.category)
        # a file has a tag itself, or lies in a folder that carries it (a series' tags, for instance)
        encoded = json.dumps(sorted(ids))
        return ("(EXISTS (SELECT 1 FROM media_tag mt WHERE mt.media_id = m.id "
                "AND mt.tag_id IN (SELECT value FROM json_each(?))) "
                "OR EXISTS (SELECT 1 FROM folder_tag ft WHERE ft.tag_id IN (SELECT value FROM json_each(?)) "
                "AND substr(m.path, 1, length(ft.folder) + 1) = ft.folder || '/'))",
                [encoded, encoded])
    if term.kind == "name":
        return ("m.name LIKE ? ESCAPE '\\'", [f"%{like_escape(term.value)}%"])
    if term.kind == "type":
        kind = KIND_ALIASES.get(term.value)
        return ("m.kind = ?", [kind]) if kind else None
    if term.kind == "favorite":
        return ("m.favorite = 1", [])
    if term.kind == "rating":
        parsed = parse_rating(term.value)
        if parsed is None:
            return None
        op, level = parsed
        if op == "unrated":
            return ("m.rating IS NULL", [])
        return (f"m.rating {op} ?", [level])
    return None


def build_sql(terms: list[Term], resolver, ranges) -> tuple[str, list]:
    """SQL returning (id, path) of the matches.

    `resolver` provides tag_ids(name, category) and wildcard_ids(pattern,
    category) -> set of tag ids (aliases and implications already expanded).
    `ranges` is the scope: a list of (low, high) path bounds, a file is in
    scope if low <= path < high for any of them. An empty list matches nothing.
    """
    where = ["m.missing = 0"]
    params: list = []

    if ranges:
        where.append("(" + " OR ".join("(m.path >= ? AND m.path < ?)" for _ in ranges) + ")")
        for low, high in ranges:
            params += [low, high]
    else:
        where.append("0")

    or_parts = []
    for term in terms:
        built = _clause(term, resolver)
        if built is None:
            continue
        sql, p = built
        if term.ored and not term.negated:
            or_parts.append((sql, p))
            continue
        if term.negated:
            if term.kind == "rating":
                # NULL-safe: unrated items are not "not explicit"
                sql = f"(m.rating IS NULL OR NOT ({sql}))" if "IS NULL" not in sql else "m.rating IS NOT NULL"
            else:
                sql = f"NOT ({sql})"
        where.append(sql)
        params += p
    if or_parts:
        where.append("(" + " OR ".join(s for s, _ in or_parts) + ")")
        for _, p in or_parts:
            params += p

    return "SELECT m.id, m.path FROM media m WHERE " + " AND ".join(where), params


def scope_range(directory: str) -> tuple[str, str]:
    """Path bounds covering everything below `directory` (no trailing slash needed)."""
    prefix = directory.rstrip("/") + "/"
    return prefix, prefix[:-1] + chr(ord("/") + 1)
