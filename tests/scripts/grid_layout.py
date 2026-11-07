# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

# Run by tests/test_scripts.py (pytest), or directly:  TETIA_SRC=src python tests/scripts/grid_layout.py
# The media page (MediaGridView): folders as covers then pictures in rows; only the rows near the window exist,
# however big the folder; a click and a rubber band select what they touch. Needs Kirigami; skips without it.
import importlib.resources, os, sys, tempfile
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="home")
os.environ["HOME"] = HOME
for _name in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(_name, None)      # Tetia keeps its data there before ~/.local/share: never in the real folders
sys.path.insert(0, os.environ["TETIA_SRC"])

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from tetia.models import (  # noqa: F401
    coverPicker, favoritesModel, file_picker, folderModel, gridModel, mediaActions, mediaModel, metadataModel, player,
    playbackStore, profileModel, purgeSession, readerSession, searchModel, showModel, subfolderModel, tagModel,
    tileRows, uiSettings, virtualFolderService, wheelZoom,
)
from tetia.models import covers
from tetia.models.database import get_database
from tetia.models.gridModel import GridModel
from tetia.models.mediaModel import MediaModel
from tetia.models.subfolderModel import SubfolderModel
from tetia.models.thumbModel import ThumbnailProvider

results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


folder = Path(tempfile.mkdtemp(prefix="pics"))
for sub in ("Album A", "Album B"):
    (folder / sub).mkdir()
    QImage(30, 40, QImage.Format_RGB32).save(str(folder / sub / "inside.png"))
for n in range(300):
    image = QImage(60 if n % 3 else 30, 40, QImage.Format_RGB32)       # wide and tall pictures
    image.fill(QColor.fromHsv((n * 7) % 360, 160, 200))
    image.save(str(folder / ("p%03d.png" % n)))
get_database().add_folder(covers.folder_uri(str(folder)), "photos")

media = MediaModel()
subs = SubfolderModel()
media.filterMode = MediaModel.FilterMode.ImagesOnly
media.load_from_qurl(str(folder))
subs.load(covers.folder_uri(str(folder)))
grid_model = GridModel()
grid_model.subfolders = subs
grid_model.media = media

views = importlib.resources.files("tetia") / "qml" / "views"
qml = folder / "t.qml"
qml.write_text('import QtQuick\nimport "%s"\nItem { property alias grid: g\n MediaGridView { id: g; objectName: "grid"; anchors.fill: parent } }'
               % QUrl.fromLocalFile(str(views)).toString())
view = QQuickView()
view.engine().addImageProvider("thumbnail", ThumbnailProvider())
view.setResizeMode(QQuickView.SizeRootObjectToView)
view.setSource(QUrl.fromLocalFile(str(qml)))
if view.errors():
    print("SKIP the interface libraries (Kirigami) are not available here: " + " | ".join(e.toString()[-90:] for e in view.errors()[:3]))
    sys.exit(0)
grid = view.rootObject().findChild(QObject, "grid")
grid.setProperty("model", grid_model)
view.resize(1000, 700)
view.show()
QTest.qWait(400)


def tiles():
    """The tile items that exist now (those of the rows near the window), found through the visual tree."""
    found, todo = [], [grid.property("contentItem")]
    while todo:
        item = todo.pop()
        if item.property("itemIndex") is not None and item.property("d") is not None:
            found.append(item)
        todo.extend(item.childItems())
    return found


count = grid.property("count")
folders = grid_model.property("folderCount")
check("the page counts every tile", count == folders + 300, f"{count} vs {folders}+300")
made = len(tiles())
check("only the tiles near the window exist", 0 < made < 150, str(made))

first = sorted(tiles(), key=lambda t: t.property("itemIndex"))
check("the folders come first, as covers", folders == 0 or first[0].property("d")["isFolder"] is True)

# the pictures keep their shape: a tall one is narrower than a wide one in the same row
pictures = [t for t in tiles() if not t.property("d")["isFolder"]]
by_y = {}
for t in pictures:
    by_y.setdefault(round(t.parentItem().property("y")), []).append(t)
row = max(by_y.values(), key=len)
shapes = {round(t.width() / t.height(), 2) for t in row}
check("pictures in a row keep their own shapes", len(shapes) >= 2, str(shapes))

# scrolling far down makes the rows there and drops the ones at the top
grid.setProperty("contentY", grid.property("contentHeight") - 700)
QTest.qWait(200)
indices = [t.property("itemIndex") for t in tiles()]
check("scrolling to the end makes the last rows", max(indices) == count - 1, str(max(indices)))
check("...and drops the first ones", min(indices) > 0, str(min(indices)))
check("still only a few tiles exist", len(indices) < 150, str(len(indices)))
grid.setProperty("contentY", 0)
QTest.qWait(200)

# select mode: a click selects a tile, a rubber band adds what it touches
grid.setProperty("selectMode", True)
QTest.qWait(100)
pictures = [t for t in tiles() if not t.property("d")["isFolder"]]      # made again after the scroll back
target = sorted(pictures, key=lambda t: t.property("itemIndex"))[0]
centre = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, centre)
QTest.qWait(100)
def selected_ids():
    value = grid.property("selectedIds")
    return list(value.toVariant() if hasattr(value, "toVariant") else value)


selected = selected_ids()
check("a click selects the picture", selected == [target.property("d")["mediaId"]], str(selected))

start = target.mapToScene(QPointF(2, 2)).toPoint()
end = QPoint(start.x() + 600, start.y() + 250)
QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
for step in range(1, 11):
    QTest.mouseMove(view, QPoint(start.x() + 60 * step, start.y() + 25 * step))
    QTest.qWait(20)
QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, end)
QTest.qWait(150)
banded = selected_ids()
check("a rubber band selects the pictures it touches", len(banded) >= 4, str(len(banded)))

view.close()
print("%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
