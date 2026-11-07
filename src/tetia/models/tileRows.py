# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rows of a media page, for QML: tileLayout's rows, but only those near the window.

A page can hold thousands of files. The view is a Flickable whose content height is exact (worked out here for
every row), and this model holds only the rows within a screen or two of what is shown, adding and dropping rows
at the ends as the page scrolls, so QML only ever creates a few dozen tiles. The view tells it the width, the
tile sizes and where the window is; it tells the view each row's place and its tiles' widths, and finds the
tiles a rubber band touches.
"""
from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, Property, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import tileLayout

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

MARGIN = 1.0      # screens of rows kept above and below the window


@QmlElement
class TileRows(QAbstractListModel):
    KindRole = Qt.UserRole + 1
    StartRole = Qt.UserRole + 2
    YRole = Qt.UserRole + 3
    HeightRole = Qt.UserRole + 4
    LabelRole = Qt.UserRole + 5
    WidthsRole = Qt.UserRole + 6
    XsRole = Qt.UserRole + 7
    TilesRole = Qt.UserRole + 8

    sourceChanged = Signal()
    geometryChanged = Signal()
    layoutUpdated = Signal()       # contentHeight and itemCount
    revisionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._width = 0.0
        self._picture_height = 180.0
        self._cover_width = 150.0
        self._cover_label = 40.0
        self._top = 0.0
        self._viewport = 0.0
        self._rows: list = []
        self._shapes: list = []
        self._content_height = 0.0
        self._first = self._last = 0     # the window: rows[first:last]
        self._revision = 0

    # ---- inputs -------------------------------------------------------------------------------

    @Property(QObject, notify=sourceChanged)
    def source(self):
        return self._source

    @source.setter
    def source(self, model):
        if model is self._source:
            return
        if self._source is not None:
            for signal in (self._source.modelReset, self._source.rowsInserted, self._source.rowsRemoved,
                           self._source.layoutChanged):
                try:
                    signal.disconnect(self._relayout)
                except (RuntimeError, TypeError):
                    pass
            try:
                self._source.dataChanged.disconnect(self._on_data_changed)
            except (RuntimeError, TypeError):
                pass
        self._source = model
        if model is not None:
            for signal in (model.modelReset, model.rowsInserted, model.rowsRemoved, model.layoutChanged):
                signal.connect(self._relayout)
            model.dataChanged.connect(self._on_data_changed)
        self.sourceChanged.emit()
        self._relayout()

    def _number(name, notify):
        attribute = "_" + name

        def getter(self):
            return getattr(self, attribute)

        def setter(self, value):
            value = float(value)
            if value != getattr(self, attribute):
                setattr(self, attribute, value)
                self.geometryChanged.emit()
                self._relayout()
        return Property(float, getter, setter, notify=notify)

    width = _number("width", geometryChanged)
    pictureHeight = _number("picture_height", geometryChanged)
    coverWidth = _number("cover_width", geometryChanged)
    coverLabel = _number("cover_label", geometryChanged)
    del _number

    @Slot(float, float)
    def setViewport(self, top: float, height: float):
        """Where the window is (content coordinates): the rows near it are kept, the rest dropped."""
        self._top, self._viewport = float(top), float(height)
        self._move_window()

    # ---- outputs ------------------------------------------------------------------------------

    @Property(float, notify=layoutUpdated)
    def contentHeight(self):
        return self._content_height

    @Property(int, notify=layoutUpdated)
    def itemCount(self):
        return len(self._shapes)

    @Property(int, notify=revisionChanged)
    def revision(self):
        """Goes up when a tile's data changed (a favorite, a progress bar) without the layout changing."""
        return self._revision

    @Slot(float, float, float, float, result=list)
    def hitTest(self, x0, y0, x1, y1):
        return tileLayout.hit(self._rows, x0, y0, x1, y1)

    @Slot(int, result="QVariantMap")
    def tileRect(self, index: int):
        """{x, y, width, height} of a tile (picture and name), or {} if there is no such tile."""
        for row in self._rows:
            if row.start <= index < row.start + row.count:
                k = index - row.start
                return {"x": row.xs[k], "y": row.y, "width": row.widths[k], "height": row.height + row.label}
        return {}

    # ---- the model (the window's rows) ------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._last - self._first

    def roleNames(self):
        return {self.KindRole: b"rowKind", self.StartRole: b"rowStart", self.YRole: b"rowY",
                self.HeightRole: b"rowHeight", self.LabelRole: b"rowLabel", self.WidthsRole: b"tileWidths",
                self.XsRole: b"tileXs", self.TilesRole: b"tileCount"}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self._last - self._first:
            return None
        row = self._rows[self._first + index.row()]
        return {self.KindRole: row.kind, self.StartRole: row.start, self.YRole: row.y, self.HeightRole: row.height,
                self.LabelRole: row.label, self.WidthsRole: row.widths, self.XsRole: row.xs,
                self.TilesRole: row.count}.get(role)

    # ---- work ----------------------------------------------------------------------------------

    def _read_shapes(self):
        source = self._source
        return source.shapes() if source is not None and hasattr(source, "shapes") else []

    def _on_data_changed(self, *args):
        shapes = self._read_shapes()
        if shapes != self._shapes:
            self._relayout(shapes)
        else:
            self._revision += 1
            self.revisionChanged.emit()

    def _relayout(self, shapes=None, *args):
        if not isinstance(shapes, list):
            shapes = self._read_shapes()
        self._shapes = shapes
        rows, height = tileLayout.build(shapes, self._width, self._picture_height, self._cover_width,
                                        self._cover_label)
        self.beginResetModel()
        self._rows, self._content_height = rows, height
        self._first, self._last = self._window()
        self.endResetModel()
        self._revision += 1
        self.layoutUpdated.emit()
        self.revisionChanged.emit()

    def _window(self):
        margin = max(self._viewport, 400.0) * MARGIN
        return tileLayout.rows_between(self._rows, self._top - margin, self._top + self._viewport + margin)

    def _move_window(self):
        first, last = self._window()
        if (first, last) == (self._first, self._last):
            return
        if last <= self._first or first >= self._last:
            # a jump: nothing in common
            self.beginResetModel()
            self._first, self._last = first, last
            self.endResetModel()
            return
        # grow or shrink at the ends, so the rows that stay keep their delegates
        if first < self._first:
            self.beginInsertRows(QModelIndex(), 0, self._first - first - 1)
            self._first = first
            self.endInsertRows()
        elif first > self._first:
            self.beginRemoveRows(QModelIndex(), 0, first - self._first - 1)
            self._first = first
            self.endRemoveRows()
        if last > self._last:
            count = self._last - self._first
            self.beginInsertRows(QModelIndex(), count, count + last - self._last - 1)
            self._last = last
            self.endInsertRows()
        elif last < self._last:
            self.beginRemoveRows(QModelIndex(), last - self._first, self._last - self._first - 1)
            self._last = last
            self.endRemoveRows()
