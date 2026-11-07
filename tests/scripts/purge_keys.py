# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

# Run by tests/test_scripts.py (pytest), or directly:  TETIA_SRC=src python tests/scripts/purge_keys.py
# Purge mode's keys must keep working after a button was clicked or Tab-focused (a clicked button used to take the
# keyboard focus, and the arrow keys then went to the button and did nothing). Needs Kirigami; skips without it.
import importlib.resources, os, sys, tempfile
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="home")
os.environ["HOME"] = HOME
for _name in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(_name, None)      # Tetia keeps its data there before ~/.local/share: never in the real folders
sys.path.insert(0, os.environ["TETIA_SRC"])

from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

# every model registers its QML type when imported (as tetia.__main__ does)
from tetia.models import (  # noqa: F401
    coverPicker, favoritesModel, file_picker, folderModel, gridModel, mediaActions, mediaModel, metadataModel, player,
    playbackStore, profileModel, purgeSession, readerSession, searchModel, showModel, subfolderModel, tagModel,
    uiSettings, virtualFolderService, wheelZoom,
)
from tetia.models import covers
from tetia.models.database import get_database
from tetia.models.mediaModel import MediaModel
from tetia.models.thumbModel import ThumbnailProvider

results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


folder = Path(tempfile.mkdtemp(prefix="pics"))
for n in range(12):
    image = QImage(64, 48, QImage.Format_RGB32)
    image.fill(0xFF000000 + n * 1000)
    image.save(str(folder / ("p%02d.png" % n)))
get_database().add_folder(covers.folder_uri(str(folder)), "photos")
media = MediaModel()
media.load_from_qurl(str(folder))
ids = media.visibleIds()

views = importlib.resources.files("tetia") / "qml" / "views"
qml = folder / "t.qml"
qml.write_text('import QtQuick\nimport "%s"\nItem { PurgeView { objectName: "pv"; anchors.fill: parent; mediaIds: %s; folderName: "t" } }'
               % (QUrl.fromLocalFile(str(views)).toString(), ids))
view = QQuickView()
view.engine().addImageProvider("thumbnail", ThumbnailProvider())
view.setResizeMode(QQuickView.SizeRootObjectToView)
view.setSource(QUrl.fromLocalFile(str(qml)))
if view.errors():
    print("SKIP the interface libraries (Kirigami) are not available here: " + " | ".join(e.toString()[-90:] for e in view.errors()[:3]))
    sys.exit(0)
view.resize(900, 600)
view.show()
view.requestActivate()
QTest.qWait(500)


def pending():
    return view.rootObject().findChild(QObject, "purgeSession").property("pending")


def click(text):
    for item in view.rootObject().findChildren(QQuickItem):
        if item.property("text") == text and "Button" in item.metaObject().className():
            centre = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, centre)
            return
    raise AssertionError("no button called " + text)


def press(key):
    QTest.keyClick(view, key)
    QTest.qWait(450)                  # the card flies off before the decision counts


start = pending()
check("12 images are waiting", start == 12, str(start))
press(Qt.Key_Right)
check("the Right key keeps one", pending() == start - 1, str(pending()))
click("Trash")
QTest.qWait(450)
check("the Trash button marks one", pending() == start - 2, str(pending()))
press(Qt.Key_Right)
check("the Right key still works after a click on Trash", pending() == start - 3, str(pending()))
click("Undo")
QTest.qWait(200)
check("the Undo button brings one back", pending() == start - 2, str(pending()))
press(Qt.Key_Left)
check("the Left key still works after a click on Undo", pending() == start - 3, str(pending()))
click("Keep")
QTest.qWait(450)
press(Qt.Key_Left)
check("the Left key still works after a click on Keep", pending() == start - 5, str(pending()))

# a button the keyboard moved the focus to (Tab) does not swallow the arrows either
before = pending()
QTest.keyClick(view, Qt.Key_Tab)
QTest.qWait(100)
press(Qt.Key_Right)
check("the Right key works with a button focused by Tab", pending() == before - 1, str(pending()))
QTest.keyClick(view, Qt.Key_Backspace)
QTest.qWait(200)
check("Backspace undoes with a button focused", pending() == before, str(pending()))

view.close()
print("%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
