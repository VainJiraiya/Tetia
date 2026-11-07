# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

# Run by tests/test_scripts.py (pytest), or directly:  TETIA_SRC=src python tests/scripts/thumb_ids.py
# Loads real pictures through Qt's image://thumbnail provider from folders with awkward names, the
# way the folder grids do, to make sure the provider is asked for the file that really exists.
import os, sys, tempfile, shutil
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="home")
os.environ["HOME"] = HOME
for _name in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(_name, None)      # Tetia keeps its data there before ~/.local/share: never in the real folders
os.environ["QT_QPA_PLATFORM"] = "offscreen"
SRC = os.environ["TETIA_SRC"]
sys.path.insert(0, SRC)

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication([])
from tetia.models.thumbModel import ThumbnailProvider

ROOT = Path(tempfile.mkdtemp(prefix="media")).resolve()
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


engine = QQmlEngine()
engine.addImageProvider("thumbnail", ThumbnailProvider())
helper = (Path(SRC).resolve() / "tetia" / "qml" / "views" / "thumbUri.js").as_uri()

NAMES = [
    "plain folder",
    "[Hibon (Itami)] Wotasa no Gyaru VS Jirai Otoko [English] {2d-market.com} [Decensored] [Digital]",
    "braces {a} and {b}",
    "literal %7B percent %20 and 100%",
    "hash # tag",
    "question ? mark",
    "quote ' and \" double",
    "ünïcödé フォルダ",
    "pipe | caret ^ backtick ` tilde ~",
    "plus + equals = amp & semi ;",
]


def loads(source: str) -> bool:
    comp = QQmlComponent(engine)
    comp.setData(f'import QtQuick\nimport "{helper}" as ThumbUri\nImage {{ id: img; property bool ready: img.status === Image.Ready; asynchronous: false; source: {source} }}'.encode(), QUrl())
    obj = comp.create()
    if obj is None:
        return False
    ok = bool(obj.property("ready"))
    obj.deleteLater()
    return ok


def js_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


for i, name in enumerate(NAMES):
    folder = ROOT / name
    folder.mkdir()
    pic = folder / f"pic{i}.png"
    image = QImage(40, 30, QImage.Format_RGB32)
    image.fill(QColor(30 + i * 20, 80, 160))
    image.save(str(pic))
    # as the folder grids now build the source: a fully encoded file address
    check(f"encoded address loads: {name[:34]}", loads(f'"image://thumbnail/" + ThumbUri.fromPath({js_string(str(pic))})'))

# the helper itself: one decoding, no ambiguity
from PySide6.QtCore import QUrl as U
for name in NAMES:
    path = f"/home/u/{name}/a.cbz"
    encoded = "file://" + "/".join(__import__("urllib.parse", fromlist=["quote"]).quote(p, safe="") for p in path.split("/"))
    check(f"round trip: {name[:34]}", U(encoded).toLocalFile() == path)

print(f"\n{sum(results)}/{len(results)} passed")
shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)
sys.exit(0 if all(results) else 1)
