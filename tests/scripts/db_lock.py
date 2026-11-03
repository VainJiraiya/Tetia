# Run by tests/test_scripts.py (pytest), or directly:  TETIA_SRC=src python tests/scripts/db_lock.py
# Uses a throwaway HOME, so it never touches your real data.
# Tests that TagModel and MediaModel can interleave DB writes without
# "database is locked" errors (the bug fixed in Problem 2 step a).
import os, sys, tempfile, shutil, sqlite3
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="home")
os.environ["HOME"] = HOME
sys.path.insert(0, os.environ["TETIA_SRC"])

from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])

from tetia.models.mediaModel import MediaModel
from tetia.models.tagModel import TagModel
from tetia.models.database import Database

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
    m = MediaModel()
    tm = TagModel()
    return m, tm


def visible(model):
    return {i["file_name"]: i for i in model._visible_items}


def mk(folder, name, content):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_bytes(content)
    return f


# 1. addTag then setRating on the same media_id — the original crash path
m, tm = fresh_pair()
a = ROOT / "t1"
mk(a, "p1.jpg", b"1" * 100)
m.load_from_qurl(str(a))
media_id = visible(m)["p1.jpg"]["media_id"]

try:
    tm.addTag(media_id, "test_tag", "content")
    m.setRating(media_id, 2)
    check("addTag + setRating no lock", True)
except sqlite3.OperationalError as e:
    check("addTag + setRating no lock", False, str(e))

# 2. setRating then addTag — reverse order
m, tm = fresh_pair()
b = ROOT / "t2"
mk(b, "p2.jpg", b"2" * 100)
m.load_from_qurl(str(b))
media_id2 = visible(m)["p2.jpg"]["media_id"]

try:
    m.setRating(media_id2, 1)
    tm.addTag(media_id2, "test_tag2", "genre")
    check("setRating + addTag no lock", True)
except sqlite3.OperationalError as e:
    check("setRating + addTag no lock", False, str(e))

# 3. setFavorite then removeTag
m, tm = fresh_pair()
c = ROOT / "t3"
mk(c, "p3.jpg", b"3" * 100)
m.load_from_qurl(str(c))
media_id3 = visible(m)["p3.jpg"]["media_id"]

tm.addTag(media_id3, "to_remove", "creator")
tag_id = tm.tagsFor(media_id3)[0]["id"]

try:
    m.setFavorite(media_id3, True)
    tm.removeTag(media_id3, tag_id)
    check("setFavorite + removeTag no lock", True)
except sqlite3.OperationalError as e:
    check("setFavorite + removeTag no lock", False, str(e))

# 4. Interleaved: addTag → setRating → addTag → setRating (stress the pattern)
m, tm = fresh_pair()
d = ROOT / "t4"
mk(d, "p4.jpg", b"4" * 100)
m.load_from_qurl(str(d))
media_id4 = visible(m)["p4.jpg"]["media_id"]

try:
    for i in range(5):
        tm.addTag(media_id4, f"stag_{i}", "content")
        m.setRating(media_id4, i % 4)      # ratings are 0-3
        m.setFavorite(media_id4, i % 2 == 0)
        tm.removeTag(media_id4, tm.tagsFor(media_id4)[0]["id"])
    check("interleaved 5 rounds no lock", True)
except sqlite3.OperationalError as e:
    check("interleaved 5 rounds no lock", False, str(e))

# 5. Two separate models reading after writes from each other
m, tm = fresh_pair()
e = ROOT / "t5"
mk(e, "p5.jpg", b"5" * 100)
m.load_from_qurl(str(e))
media_id5 = visible(m)["p5.jpg"]["media_id"]

tm.addTag(media_id5, "shared", "genre")
m.setRating(media_id5, 3)
m.setFavorite(media_id5, True)

# Both models should see consistent state
rating = m.getFavorite(media_id5)  # reads from DB
tags = tm.tagsFor(media_id5)
check("cross-model reads consistent", len(tags) == 1 and isinstance(rating, bool),
      f"tags={len(tags)} favorite={rating}")

print(f"\n{sum(results)}/{len(results)} passed")
shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)
sys.exit(0 if all(results) else 1)
