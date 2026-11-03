# Run by tests/test_scripts.py (pytest), or directly:  TETIA_SRC=src python tests/scripts/search.py
# Uses a throwaway HOME, so it never touches your real data.
import os, sys, tempfile, time
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="home")
os.environ["HOME"] = HOME
sys.path.insert(0, os.environ["TETIA_SRC"])

from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])

from tetia.models.database import get_database
from tetia.models.searchModel import SearchModel
from tetia.models.tagModel import TagModel
from tetia.models.mediaModel import MediaModel

ROOT = Path(tempfile.mkdtemp(prefix="media")).resolve()
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def touch(rel, data=b"x"):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


touch("Movies/Starfall/Prologue/film1.mp4", b"a1")
touch("Movies/Starfall/Finale/film2.mp4", b"a2")
touch("Photos/board/orin/f1.png", b"b1")
touch("Photos/board/mira/f2.png", b"b2")
touch("Manga/Series/ch 2.cbz", b"c2")
touch("Manga/Series/ch 10.cbz", b"c10")
(ROOT / "Photos/loop").mkdir(exist_ok=True)
os.symlink(ROOT / "Photos", ROOT / "Photos/board/loop")   # symlink loop

db = get_database()
for sub, cat in (("Movies", "videos"), ("Photos", "photos"), ("Manga", "manga")):
    db.add_folder((ROOT / sub).as_uri(), cat)

s = SearchModel()
t = TagModel()
m = MediaModel()


def index():
    s.indexLibrary()
    deadline = time.time() + 20
    while s.indexing and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


index()
check("indexer finished", not s.indexing)
rows = db.conn.execute("SELECT name FROM media ORDER BY name").fetchall()
names = [r[0] for r in rows]
check("every file indexed without opening folders", len(names) == 6, str(names))

ids = {r["name"]: r["id"] for r in db.conn.execute("SELECT id, name FROM media")}
t.addTag(ids["film1.mp4"], "iris vale", "character")
t.addTag(ids["f1.png"], "iris vale", "character")
t.addTag(ids["film1.mp4"], "starfall", "series")
t.addTag(ids["film2.mp4"], "starfall", "series")

def found(query, scope=""):
    return sorted(r["name"] for r in db.get_media_rows(s.search(query, scope)).values())

check("top level: tag across categories", found("iris_vale") == ["f1.png", "film1.mp4"], str(found("iris_vale")))
check("space in tag name", found("iris vale".replace(" ", "_")) == ["f1.png", "film1.mp4"])
check("top level: category", found("series:starfall") == ["film1.mp4", "film2.mp4"])
check("folder scope narrows", found("starfall", (ROOT / "Movies/Starfall/Finale").as_uri()) == ["film2.mp4"])
check("folder scope includes subfolders", found("starfall", str(ROOT / "Movies")) == ["film1.mp4", "film2.mp4"])
check("scope excludes other folders", found("iris_vale", str(ROOT / "Movies")) == ["film1.mp4"])
check("filename fallback", found("orin") == [] and found("f1") == ["f1.png"])
check("type", found("type:manga") == ["ch 10.cbz", "ch 2.cbz"])
ordered = [db.get_media_rows([i])[i]["name"] for i in s.search("type:manga", "")]
check("natural order", ordered == ["ch 2.cbz", "ch 10.cbz"], str(ordered))
check("negation", found("type:video -starfall") == [])

# Removing a folder from the library drops its files from library-wide search
db.remove_folder((ROOT / "Manga").as_uri())
check("removed folder leaves search", found("type:manga") == [])

# Rename keeps the id and tags even when the indexer sees the new name first
old_id = ids["film2.mp4"]
os.rename(ROOT / "Movies/Starfall/Finale/film2.mp4", ROOT / "Movies/Starfall/Finale/finale.mp4")
index()
row = db.conn.execute("SELECT id FROM media WHERE name = 'finale.mp4'").fetchone()
check("rename keeps media id", row is not None and row["id"] == old_id)
check("rename keeps tags", "finale.mp4" in found("series:starfall"))

# Suggestions
sug = s.suggest("iri")
check("suggest tag", any(x["insert"] == "iris_vale" for x in sug), str(sug))
check("suggest metatag", any(x["insert"] == "type:" for x in s.suggest("ty")))
check("suggest keeps -", any(x["insert"] == "-iris_vale" for x in s.suggest("-iri")))
check("suggest value", any(x["insert"] == "type:video" for x in s.suggest("type:vi")))

# Showing results in the grid model
m.load_media_ids(s.search("series:starfall", ""))
check("grid shows results", m.rowCount() == 2)
check("no folder open", m.folderPath == "")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
