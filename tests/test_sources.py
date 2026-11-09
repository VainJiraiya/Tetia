# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tab's top level: what is in all its library folders together, each folder's loose files under its name; a
library folder that is a collection in itself (a series) is a tile of its own."""
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from tetia.models import covers, tileLayout
from tetia.models.folderModel import FolderModel
from tetia.models.gridModel import GridModel
from tetia.models.mediaModel import MediaModel
from tetia.models.subfolderModel import SubfolderModel


def _images(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        image = QImage(6, 4, QImage.Format_RGB32)
        image.fill(QColor("navy"))
        image.save(str(folder / name))


def _wait(condition, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def _names(model):
    return [model.data(model.index(r), MediaModel.Roles.FileNameRole) for r in range(model.rowCount())]


def test_several_library_folders_show_together_grouped_by_folder(tmp_path, qapp):
    _images(tmp_path / "Art", ["b.png", "a.png"])
    _images(tmp_path / "Art" / "Raphtalia", ["r.png"])
    _images(tmp_path / "Camera", ["c.png"])
    _images(tmp_path / "Camera" / "Trip", ["t.png"])
    media = MediaModel()
    media.filterMode = MediaModel.FilterMode.ImagesOnly
    media.openSources([covers.folder_uri(str(tmp_path / "Art")), covers.folder_uri(str(tmp_path / "Camera"))])
    assert media.folderPath == "" and len(media.sources) == 2
    assert _wait(lambda: not media.scanning)
    assert _names(media) == ["a.png", "b.png", "c.png"]                 # each folder's files stay together
    assert media.sourceGroups() == [(0, "Art", 2), (2, "Camera", 1)]

    subs = SubfolderModel()
    subs.filterMode = int(MediaModel.FilterMode.ImagesOnly)
    subs.loadSources([str(tmp_path / "Art"), str(tmp_path / "Camera")], [])
    assert [subs.data(subs.index(r), subs.Roles.NameRole) for r in range(subs.rowCount())] == ["Raphtalia", "Trip"]

    grid = GridModel()
    grid.subfolders = subs
    grid.media = media
    assert grid.sections() == {2: "Loose in Art · 2", 4: "Loose in Camera · 1"}

    media.openSources([covers.folder_uri(str(tmp_path / "Art"))])
    assert grid.sections() == {}                                        # one folder: no titles needed


def test_opening_a_folder_leaves_the_top_level(tmp_path, qapp):
    _images(tmp_path / "Art", ["a.png"])
    media = MediaModel()
    media.openSources([str(tmp_path / "Art")])
    media.load_from_qurl(str(tmp_path / "Art"))
    assert media.sources == [] and media.folderPath == str(tmp_path / "Art")


def test_a_series_added_to_the_library_stays_one_tile(tmp_path, qapp):
    (tmp_path / "Frieren").mkdir()
    for n in (1, 2):
        (tmp_path / "Frieren" / ("Ch.%d.cbz" % n)).write_bytes(b"x")
    (tmp_path / "Manga" / "Dragon").mkdir(parents=True)
    (tmp_path / "Manga" / "Dragon" / "Ch.1.cbz").write_bytes(b"x")
    folders = FolderModel()
    folders.currentCategory = "manga"
    folders.addFolder(covers.folder_uri(str(tmp_path / "Frieren")), "manga")
    folders.addFolder(covers.folder_uri(str(tmp_path / "Manga")), "manga")
    folders.setSeries(covers.folder_uri(str(tmp_path / "Frieren")), True)
    groups = folders.sourceGroups()
    assert [s["name"] for s in groups["all"]] == ["Frieren", "Manga"]
    assert groups["tiles"] == [covers.folder_uri(str(tmp_path / "Frieren"))]
    assert groups["expand"] == [covers.folder_uri(str(tmp_path / "Manga"))]

    subs = SubfolderModel()
    subs.filterMode = int(MediaModel.FilterMode.MangaOnly)
    subs.loadSources(groups["expand"], groups["tiles"])
    names = [subs.data(subs.index(r), subs.Roles.NameRole) for r in range(subs.rowCount())]
    assert names == ["Dragon", "Frieren"]
    frieren = subs.index(names.index("Frieren"))
    assert subs.data(frieren, subs.Roles.IsSeriesRole) is True


def test_a_group_title_starts_its_own_rows():
    shapes = [(tileLayout.PICTURE, 1.0)] * 4
    rows, _ = tileLayout.build(shapes, 1000, 200, 150, 40, {0: "Loose in Art", 2: "Loose in Camera"})
    kinds = [(r.kind, r.start, r.count, r.title) for r in rows]
    assert kinds == [("header", 0, 0, "Loose in Art"), ("picture", 0, 2, ""),
                     ("header", 2, 0, "Loose in Camera"), ("picture", 2, 2, "")]
    assert tileLayout.hit(rows, 0, rows[0].y, 1000, rows[0].bottom) == []      # a title is not a tile


def test_a_batch_makes_one_reset_of_both_models(tmp_path, qapp):
    """A tab switch reloads the files and the folder tiles: the grid is reset (and laid out) once."""
    (tmp_path / "Art" / "Sketches").mkdir(parents=True)
    for folder, name in ((tmp_path / "Art", "a.png"), (tmp_path / "Art" / "Sketches", "b.png")):
        image = QImage(4, 3, QImage.Format_RGB32)
        image.fill(QColor("red"))
        image.save(str(folder / name))
    media, subs, grid = MediaModel(), SubfolderModel(), GridModel()
    grid.media, grid.subfolders = media, subs
    resets = []
    grid.modelReset.connect(lambda: resets.append(1))
    grid.beginBatch()
    media.load_from_qurl(str(tmp_path / "Art"))
    subs.load(str(tmp_path / "Art"))
    media.filterMode = MediaModel.FilterMode.ImagesOnly
    assert resets == []                                   # held while the batch lasts
    grid.endBatch()
    assert resets == [1] and grid.rowCount() == 2 and grid.folderCount == 1
    media.filterMode = MediaModel.FilterMode.All          # outside a batch, as before
    assert resets == [1, 1]


def test_get_gives_what_each_role_gives(tmp_path, qapp):
    (tmp_path / "Art" / "Sketches").mkdir(parents=True)
    for folder, name in ((tmp_path / "Art", "a.png"), (tmp_path / "Art" / "Sketches", "b.png")):
        image = QImage(4, 3, QImage.Format_RGB32)
        image.fill(QColor("red"))
        image.save(str(folder / name))
    media, subs, grid = MediaModel(), SubfolderModel(), GridModel()
    grid.media, grid.subfolders = media, subs
    media.load_from_qurl(str(tmp_path / "Art"))
    subs.load(str(tmp_path / "Art"))
    assert grid.rowCount() == 2
    for row in range(grid.rowCount()):
        index = grid.index(row)
        expected = {name.decode(): grid.data(index, role) for role, name in grid.roleNames().items()}
        assert grid.get(row) == expected
