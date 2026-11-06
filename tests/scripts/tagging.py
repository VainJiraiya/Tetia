# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

# Run by tests/test_scripts.py (pytest), or directly:  TETIA_SRC=src python tests/scripts/tagging.py
# Uses a throwaway HOME, so it never touches your real data.
import os, sys, tempfile, shutil, sqlite3
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="home")
os.environ["HOME"] = HOME           # Database() writes under ~/.local/share, so this is isolated
sys.path.insert(0, os.environ["TETIA_SRC"])   # e.g. TETIA_SRC=~/Projects/Tetia/src

from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])

from tetia.models.mediaModel import MediaModel
from tetia.models.tagModel import TagModel, normalize_tag
from tetia.models.database import Database, get_database, reset_singleton

ROOT = Path(tempfile.mkdtemp(prefix="media")).resolve()
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def fresh_pair():
    """Create a fresh MediaModel + TagModel pair with a brand new database."""
    global HOME
    HOME = tempfile.mkdtemp(prefix="home")
    os.environ["HOME"] = HOME
    reset_singleton()

    m = MediaModel()
    tm = TagModel()
    return m, tm


def rows(model):
    return {r["path"]: dict(r) for r in model._db.conn.execute("SELECT * FROM media")}


def visible(model):
    return {i["file_name"]: i for i in model._visible_items}


def mk(folder, name, content):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_bytes(content)
    return f


# --- Normalization tests ---

# 1. Basic normalization: strip, lowercase, collapse whitespace
check("normalize_tag strips and lowercases", normalize_tag("  Sea Horse  ") == "sea_horse")
check("normalize_tag collapses multiple spaces", normalize_tag("some   weird   name") == "some_weird_name")
check("normalize_tag mixed case", normalize_tag("iSeKai") == "isekai")

# 2. Invalid: comma
try:
    normalize_tag("tag,with,commas")
    check("normalize_tag rejects comma", False, "no exception raised")
except ValueError:
    check("normalize_tag rejects comma", True)

# 3. Invalid: colon
try:
    normalize_tag("tag:with:colons")
    check("normalize_tag rejects colon", False, "no exception raised")
except ValueError:
    check("normalize_tag rejects colon", True)

# 4. Invalid: asterisk
try:
    normalize_tag("tag*with*stars")
    check("normalize_tag rejects asterisk", False, "no exception raised")
except ValueError:
    check("normalize_tag rejects asterisk", True)

# 5. Invalid: tilde
try:
    normalize_tag("tag~with~tildes")
    check("normalize_tag rejects tilde", False, "no exception raised")
except ValueError:
    check("normalize_tag rejects tilde", True)

# 6. Invalid: leading dash
try:
    normalize_tag("-badtag")
    check("normalize_tag rejects leading dash", False, "no exception raised")
except ValueError:
    check("normalize_tag rejects leading dash", True)

# 7. Invalid: empty after strip
try:
    normalize_tag("   ")
    check("normalize_tag rejects empty after strip", False, "no exception raised")
except ValueError:
    check("normalize_tag rejects empty after strip", True)

# 8. Valid: simple tag
check("normalize_tag simple tag", normalize_tag("isekai") == "isekai")
check("normalize_tag with underscores", normalize_tag("sea_horse") == "sea_horse")


# --- Tag operations tests ---

# 9. Add a tag creates the tag and links it to media
m, tm = fresh_pair()
a = ROOT / "t9"
mk(a, "p1.jpg", b"1" * 100)
m.load_from_qurl(str(a))
media_id = visible(m)["p1.jpg"]["media_id"]

result = tm.addTag(media_id, "Sea Horse", "content")
check("addTag returns True", result)

tags = tm.tagsFor(media_id)
check("addTag creates tag link", len(tags) == 1 and tags[0]["name"] == "sea_horse", str(tags))

# 10. Adding the same tag twice is a no-op
tm.addTag(media_id, "sea_horse", "content")
tags2 = tm.tagsFor(media_id)
check("addTag same tag twice is no-op", len(tags2) == 1, f"expected 1 tag, got {len(tags2)}")

# 11. Adding a tag with different category uses the provided category
tm.addTag(media_id, "isekai", "genre")
tags3 = tm.tagsFor(media_id)
tag_names = {t["name"] for t in tags3}
check("addTag different category works", "isekai" in tag_names, str(tags3))
isekai_tag = [t for t in tags3 if t["name"] == "isekai"][0]
check("isekai has correct category", isekai_tag["category"] == "genre", isekai_tag["category"])

# 12. Bulk add across multiple media_ids
m, tm = fresh_pair()
b = ROOT / "t12"
mk(b, "a.jpg", b"a" * 50)
mk(b, "b.jpg", b"b" * 50)
m.load_from_qurl(str(b))
ids = [visible(m)["a.jpg"]["media_id"], visible(m)["b.jpg"]["media_id"]]

tm.addTagsToMedia(ids, "chibi", "content")
for mid in ids:
    tags = tm.tagsFor(mid)
    check(f"bulk add to media {mid}", len(tags) == 1 and tags[0]["name"] == "chibi", str(tags))

# 13. Removing a tag removes the link but keeps the tag in the DB
m, tm = fresh_pair()
c = ROOT / "t13"
mk(c, "x.jpg", b"x" * 50)
m.load_from_qurl(str(c))
media_id3 = visible(m)["x.jpg"]["media_id"]

tm.addTag(media_id3, "supernatural", "content")
check("tag exists before remove", len(tm.tagsFor(media_id3)) == 1)

tm.removeTag(media_id3, tm.tagsFor(media_id3)[0]["id"])
check("removeTag removes link", len(tm.tagsFor(media_id3)) == 0)

# A tag that nothing uses any more is removed with its last link (a misspelling must not stay as a suggestion)
check("removeTag drops a tag nothing uses", tm._db.get_tag_id("supernatural") is None)

# 14. Suggest returns the right tags
m, tm = fresh_pair()
d = ROOT / "t14"
mk(d, "y.jpg", b"y" * 50)
m.load_from_qurl(str(d))
media_id4 = visible(m)["y.jpg"]["media_id"]

tm.addTag(media_id4, "isekai", "genre")
tm.addTag(media_id4, "isekai_world", "genre")
tm.addTag(media_id4, "fantasy", "genre")

suggestions = tm.suggest("isek")
suggestion_names = [s["name"] for s in suggestions]
check("suggest matches prefix", "isekai" in suggestion_names and "isekai_world" in suggestion_names, str(suggestion_names))
check("suggest does not match unrelated", "fantasy" not in suggestion_names)

# 15. Suggest has limit of 10
m, tm = fresh_pair()
e = ROOT / "t15"
mk(e, "z.jpg", b"z" * 50)
m.load_from_qurl(str(e))
media_id5 = visible(m)["z.jpg"]["media_id"]

for i in range(15):
    tm.addTag(media_id5, f"tag_{i:03d}", "content")

suggestions5 = tm.suggest("tag_")
check("suggest limited to 10", len(suggestions5) <= 10, f"got {len(suggestions5)} suggestions")

# 16. addTag with invalid name returns False
m, tm = fresh_pair()
f = ROOT / "t16"
mk(f, "w.jpg", b"w" * 50)
m.load_from_qurl(str(f))
media_id6 = visible(m)["w.jpg"]["media_id"]

check("addTag with comma returns False", not tm.addTag(media_id6, "bad,tag", "content"))
check("addTag with leading dash returns False", not tm.addTag(media_id6, "-bad", "content"))

# 17. addTag with unknown category returns False
check("addTag with unknown category returns False", not tm.addTag(media_id6, "good_tag", "unknown_category"))

# 18. Bulk remove
m, tm = fresh_pair()
g = ROOT / "t18"
mk(g, "a.jpg", b"a" * 50)
mk(g, "b.jpg", b"b" * 50)
m.load_from_qurl(str(g))
ids7 = [visible(m)["a.jpg"]["media_id"], visible(m)["b.jpg"]["media_id"]]

tm.addTagsToMedia(ids7, "shared_tag", "content")
tag_id_7 = tm.tagsFor(ids7[0])[0]["id"]

tm.removeTagsFromMedia(ids7, tag_id_7)
check("bulk remove from first media", len(tm.tagsFor(ids7[0])) == 0)
check("bulk remove from second media", len(tm.tagsFor(ids7[1])) == 0)

# 19. MediaModel and TagModel can coexist without DB locking issues
m, tm = fresh_pair()
h = ROOT / "t19"
mk(h, "c.jpg", b"c" * 50)
m.load_from_qurl(str(h))
media_id8 = visible(m)["c.jpg"]["media_id"]

m.setFavorite(media_id8, True)
tm.addTag(media_id8, "coexist_test", "content")
tags8 = tm.tagsFor(media_id8)
check("MediaModel and TagModel coexist", len(tags8) == 1 and visible(m)["c.jpg"]["is_favorite"] == 1)

# 20. Migration version
check("schema is at the latest version (12)", get_database().conn.execute("PRAGMA user_version").fetchone()[0] == 12)

print(f"\n{sum(results)}/{len(results)} passed")
shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)
sys.exit(0 if all(results) else 1)
