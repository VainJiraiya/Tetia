# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

# Run by tests/test_scripts.py (pytest), or directly:  TETIA_SRC=src python tests/scripts/model_basics.py
# Uses a throwaway HOME, so it never touches your real data.
import os, sys, tempfile, shutil, sqlite3
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="home")
os.environ["HOME"] = HOME           # Database() writes under ~/.local/share, so this is isolated
sys.path.insert(0, os.environ["TETIA_SRC"])   # e.g. TETIA_SRC=~/Projects/Tetia/src

from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])

from tetia.models.mediaModel import MediaModel
from tetia.models.database import Database, get_database, reset_singleton

ROOT = Path(tempfile.mkdtemp(prefix="media")).resolve()
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def fresh():
    """New model + fresh database file for each test."""
    dbfile = Path(HOME) / ".local" / "share" / "tetia" / "gallery.db"
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            Path(str(dbfile) + suffix).unlink()
        except FileNotFoundError:
            pass
    reset_singleton()
    return MediaModel()


def rows(model):
    return {r["path"]: dict(r) for r in model._db.conn.execute("SELECT * FROM media")}


def visible(model):
    return {i["file_name"]: i for i in model._visible_items}


def mk(folder, name, content):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_bytes(content)
    return f


# 1. rescan keeps ids, no duplicates
m = fresh()
a = ROOT / "t1"
mk(a, "p1.jpg", b"1" * 100); mk(a, "p2.jpg", b"2" * 100)
m.load_from_qurl(str(a))
ids1 = {n: i["media_id"] for n, i in visible(m).items()}
m.load_from_qurl(str(a))
ids2 = {n: i["media_id"] for n, i in visible(m).items()}
check("rescan keeps ids", ids1 == ids2 and len(rows(m)) == 2, f"{ids1} vs {ids2}, rows={len(rows(m))}")

# 2. unchanged files are not rehashed
calls = []
orig = m._compute_content_hash
m._compute_content_hash = lambda p: (calls.append(p), orig(p))[1]
m.load_from_qurl(str(a))
check("unchanged files not rehashed", calls == [], str(calls))
m._compute_content_hash = orig

# 3. rename keeps id/favorite/rating (and the grid shows it)
pid = visible(m)["p1.jpg"]["media_id"]
m.setFavorite(pid, True); m.setRating(pid, 2)
(a / "p1.jpg").rename(a / "p1_renamed.jpg")
m.load_from_qurl(str(a))
v = visible(m)
r = rows(m)
check("rename keeps id/favorite/rating",
      "p1_renamed.jpg" in v and v["p1_renamed.jpg"]["media_id"] == pid
      and v["p1_renamed.jpg"]["is_favorite"] == 1 and v["p1_renamed.jpg"]["rating"] == 2,
      str(v))
check("rename leaves no duplicate or stale row", len(r) == 2 and all(x["missing"] == 0 for x in r.values()), str(r))

# 4. second rescan after rename is stable (no flip-flopping)
m.load_from_qurl(str(a))
v = visible(m)
check("rescan after rename is stable", v["p1_renamed.jpg"]["media_id"] == pid and v["p1_renamed.jpg"]["is_favorite"] == 1)

# 5. identical copy in another folder is not hijacked (original still exists)
m = fresh()
a, b = ROOT / "t5a", ROOT / "t5b"
mk(a, "orig.jpg", b"X" * 500)
m.load_from_qurl(str(a)); oid = visible(m)["orig.jpg"]["media_id"]
m.setFavorite(oid, True)
mk(b, "copy.jpg", b"X" * 500)
m.load_from_qurl(str(b)); cid = visible(m)["copy.jpg"]["media_id"]
r = rows(m)
check("identical copy gets its own row",
      cid != oid and r[str(a / "orig.jpg")]["id"] == oid and r[str(a / "orig.jpg")]["favorite"] == 1
      and r[str(b / "copy.jpg")]["favorite"] == 0, str(r))

# 6. original deleted, copy elsewhere: still a new row (cross-folder moves are not tracked)
(a / "orig.jpg").unlink()
m.load_from_qurl(str(a))
m.load_from_qurl(str(b))
r = rows(m)
check("deleted original keeps its row, flagged missing",
      r[str(a / "orig.jpg")]["id"] == oid and r[str(a / "orig.jpg")]["missing"] == 1, str(r))

# 7. scanning B doesn't change A's rows
m = fresh()
a, b = ROOT / "t7a", ROOT / "t7b"
mk(a, "a1.jpg", b"a" * 50); mk(b, "b1.jpg", b"b" * 50)
m.load_from_qurl(str(a)); m.load_from_qurl(str(b))
before = {p: x["missing"] for p, x in rows(m).items() if "/t7a/" in p}
m.load_from_qurl(str(b))
after = {p: x["missing"] for p, x in rows(m).items() if "/t7a/" in p}
check("scanning B leaves A untouched", before == after == {str(a / "a1.jpg"): 0}, f"{before} {after}")

# 8. subfolder rows aren't touched by parent scan
sub = a / "sub"
mk(sub, "deep.jpg", b"d" * 50)
m.load_from_qurl(str(sub)); m.load_from_qurl(str(a))
check("parent scan doesn't flag subfolder files", rows(m)[str(sub / "deep.jpg")]["missing"] == 0)

# 9. empty folder marks rows missing
m = fresh()
a = ROOT / "t9"
f = mk(a, "x.jpg", b"x" * 50)
m.load_from_qurl(str(a)); f.unlink(); m.load_from_qurl(str(a))
check("empty folder marks rows missing", rows(m)[str(f)]["missing"] == 1)

# 10. underscore / percent / space in folder names
for name in ["My_Photos", "100%done", "has space", "ünï"]:
    m = fresh()
    a = ROOT / "t10" / name
    f = mk(a, "x.jpg", b"x" * 50)
    m.load_from_qurl(str(a)); f.unlink(); m.load_from_qurl(str(a))
    check(f"mark_missing works for folder {name!r}", rows(m)[str(f)]["missing"] == 1)

# 11. symlinked folder
m = fresh()
real = ROOT / "t11_real"
link = ROOT / "t11_link"
if not link.exists():
    link.symlink_to(real, target_is_directory=True)
f = mk(real, "s1.jpg", b"s" * 50)
m.load_from_qurl(str(link))
sid = visible(m)["s1.jpg"]["media_id"]
m.setFavorite(sid, True)
f.rename(real / "s1_new.jpg")
m.load_from_qurl(str(link))
v = visible(m)
check("symlinked folder: rename keeps id/favorite",
      v.get("s1_new.jpg", {}).get("media_id") == sid and v["s1_new.jpg"]["is_favorite"] == 1, str(v))
(real / "s1_new.jpg").unlink()
m.load_from_qurl(str(link))
check("symlinked folder: delete marks missing", all(x["missing"] == 1 for x in rows(m).values()), str(rows(m)))
check("folderPath stays as chosen (unresolved)", m.folderPath == str(link), m.folderPath)

# 12. two renamed identical files each keep their own row
m = fresh()
a = ROOT / "t12"
mk(a, "d1.jpg", b"D" * 80); mk(a, "d2.jpg", b"D" * 80)
m.load_from_qurl(str(a))
v = visible(m); i1, i2 = v["d1.jpg"]["media_id"], v["d2.jpg"]["media_id"]
m.setFavorite(i1, True)
(a / "d1.jpg").rename(a / "e1.jpg"); (a / "d2.jpg").rename(a / "e2.jpg")
m.load_from_qurl(str(a))
v = visible(m)
check("two identical renamed files claim distinct rows",
      {v["e1.jpg"]["media_id"], v["e2.jpg"]["media_id"]} == {i1, i2} and len(rows(m)) == 2, str(v))

# 13. add_folder persists across connections, and a scan doesn't leave a lock
dbfile = Path(HOME) / ".local" / "share" / "tetia" / "gallery.db"
c1 = get_database()
c2 = Database()
c1.add_folder("/some/folder", "photos")
check("add_folder visible from another connection", c2.get_folders_by_category("photos") == [{"path": "/some/folder", "category": "photos"}])
c2.conn.execute("PRAGMA busy_timeout = 300")
try:
    c2.conn.execute("BEGIN"); c2.upsert_media("/q/z.jpg", "z.jpg", "image", 1, 1, "hz"); c2.conn.commit(); ok = True
except sqlite3.OperationalError as e:
    ok = False
check("other connection can write after folder add + scan", ok)

# 14. migration version
check("schema is at the latest version (9)", get_database().conn.execute("PRAGMA user_version").fetchone()[0] == 9)

print(f"\n{sum(results)}/{len(results)} passed")
shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)
sys.exit(0 if all(results) else 1)
