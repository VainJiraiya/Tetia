# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""One list for the media grid: subfolder tiles first, then the files.

It only stitches a SubfolderModel and a MediaModel together so a single
GridView can lay both out in the same flow. The image viewer and the rest of
the app keep using MediaModel directly, whose row numbers are the file
numbers; `folderCount` is the offset between the two.
"""
from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, Signal, Slot, Property
from PySide6.QtQml import QmlElement

from tetia.models import tileLayout
from tetia.models.mediaModel import MediaModel

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

_SUB_ROLES = {
    Qt.UserRole + 100: (b"isFolder", None),
    Qt.UserRole + 101: (b"subfolderPath", Qt.UserRole + 1),
    Qt.UserRole + 102: (b"subfolderName", Qt.UserRole + 2),
    Qt.UserRole + 103: (b"subfolderHero", Qt.UserRole + 3),
    Qt.UserRole + 104: (b"subfolderCount", Qt.UserRole + 4),
    Qt.UserRole + 105: (b"subfolderFavorite", Qt.UserRole + 5),
    Qt.UserRole + 106: (b"subfolderIsSeries", Qt.UserRole + 7),
    Qt.UserRole + 107: (b"subfolderSingleFile", Qt.UserRole + 8),
    Qt.UserRole + 108: (b"subfolderIsVirtual", Qt.UserRole + 9),
    Qt.UserRole + 109: (b"subfolderVirtualId", Qt.UserRole + 10),
    Qt.UserRole + 110: (b"subfolderSingleFileId", Qt.UserRole + 11),
    Qt.UserRole + 111: (b"subfolderIsShow", Qt.UserRole + 12),
    Qt.UserRole + 112: (b"subfolderFolders", Qt.UserRole + 13),
    Qt.UserRole + 113: (b"subfolderLeft", Qt.UserRole + 14),
    Qt.UserRole + 114: (b"subfolderProgress", Qt.UserRole + 15),
    Qt.UserRole + 115: (b"subfolderFinished", Qt.UserRole + 16),
}
_IS_FOLDER = Qt.UserRole + 100


@QmlElement
class GridModel(QAbstractListModel):
    mediaChanged = Signal()
    subfoldersChanged = Signal()
    folderCountChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._media = None
        self._subs = None
        self._folder_count = 0

    # ---- sources ----------------------------------------------------------

    def _connect(self, source):
        source.modelAboutToBeReset.connect(self.beginResetModel)
        source.modelReset.connect(self._after_reset)
        source.dataChanged.connect(self._on_data_changed)

    def _disconnect(self, source):
        try:
            source.modelAboutToBeReset.disconnect(self.beginResetModel)
            source.modelReset.disconnect(self._after_reset)
            source.dataChanged.disconnect(self._on_data_changed)
        except RuntimeError:
            pass   # the source is already gone (app shutting down)

    def _after_reset(self):
        self._sync_folder_count()
        self.endResetModel()

    def _sync_folder_count(self):
        count = self._subs.rowCount() if self._subs is not None else 0
        if count != self._folder_count:
            self._folder_count = count
            self.folderCountChanged.emit()

    def _on_data_changed(self, top_left, bottom_right, roles=None):
        offset = 0 if top_left.model() is self._subs else self._folder_count
        self.dataChanged.emit(self.index(top_left.row() + offset),
                              self.index(bottom_right.row() + offset))

    @Property(QObject, notify=mediaChanged)
    def media(self):
        return self._media

    @media.setter
    def media(self, model):
        if model is self._media:
            return
        self.beginResetModel()
        if self._media is not None:
            self._disconnect(self._media)
        self._media = model
        if model is not None:
            self._connect(model)
        self.endResetModel()
        self.mediaChanged.emit()

    @Property(QObject, notify=subfoldersChanged)
    def subfolders(self):
        return self._subs

    @subfolders.setter
    def subfolders(self, model):
        if model is self._subs:
            return
        self.beginResetModel()
        if self._subs is not None:
            self._disconnect(self._subs)
        self._subs = model
        if model is not None:
            self._connect(model)
        self._sync_folder_count()
        self.endResetModel()
        self.subfoldersChanged.emit()

    @Property(int, notify=folderCountChanged)
    def folderCount(self):
        return self._folder_count

    # ---- model ------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        files = self._media.rowCount() if self._media is not None else 0
        return self._folder_count + files

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < self.rowCount()):
            return None
        row = index.row()
        is_folder = row < self._folder_count
        if role == _IS_FOLDER:
            return is_folder
        if role in _SUB_ROLES:
            if not is_folder or self._subs is None:
                return None
            return self._subs.data(self._subs.index(row), _SUB_ROLES[role][1])
        if is_folder or self._media is None:
            return None   # a file role asked of a folder row (e.g. mediaId)
        return self._media.data(self._media.index(row - self._folder_count), role)

    def roleNames(self):
        # Static (not read from the sources) so it is right whenever QML asks
        R = MediaModel.Roles
        names = {
            R.MediaIdRole: b"mediaId",
            R.UniformResourceIdentifierRole: b"fileUri",
            R.FileNameRole: b"fileName",
            R.IsVideoRole: b"isVideo",
            R.IsComicRole: b"isComic",
            R.IsBookRole: b"isBook",
            R.IsFavoriteRole: b"isFavorite",
            R.RatingRole: b"rating",
            R.WatchFractionRole: b"watchFraction",
            R.IsWatchedRole: b"isWatched",
            R.AspectRole: b"aspect",
            R.DurationRole: b"duration",
        }
        for role, (name, _) in _SUB_ROLES.items():
            names[role] = name
        return names

    # ---- for the page's layout (TileRows) and its tiles -------------------------------------------

    def shapes(self):
        """(kind, aspect) of every row, for tileLayout: folder tiles, comics and books are covers; images and
        videos are pictures in their own shape (a shape not known yet is guessed: square, a video 16:9)."""
        found = [(tileLayout.COVER, tileLayout.COVER_ASPECT)] * self._folder_count
        items = self._media._visible_items if self._media is not None else []
        for item in items:
            if item.get("is_comic") or item.get("is_book"):
                found.append((tileLayout.COVER, tileLayout.COVER_ASPECT))
                continue
            width, height = item.get("width") or 0, item.get("height") or 0
            if width > 0 and height > 0:
                aspect = width / height
            else:
                aspect = 16 / 9 if item.get("is_video") else 1.0
            found.append((tileLayout.PICTURE, aspect))
        return found

    def sections(self):
        """{row: title} where a group of files starts under its own title: on a tab's top level, each library
        folder's loose files ("Loose in Anime art · 1,204"). Nothing when only one folder's files are shown."""
        if self._media is None or not hasattr(self._media, "sourceGroups") or len(self._media.sources) < 2:
            return {}
        titles = {}
        for row, name, count in self._media.sourceGroups():
            titles[self._folder_count + row] = "Loose in %s \u00B7 %s" % (name, f"{count:,}")
        return titles

    @Slot(int, result="QVariantMap")
    def get(self, row: int):
        """Every role of one row by name, in one call (a tile reads its data with this)."""
        if not 0 <= row < self.rowCount():
            return {}
        index = self.index(row)
        return {name.decode(): self.data(index, role) for role, name in self.roleNames().items()}

