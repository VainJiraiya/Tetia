# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from tetia.models import tileLayout as tl
from tetia.models.tileRows import TileRows

P, C = tl.PICTURE, tl.COVER


def _pictures(aspects):
    return [(P, a) for a in aspects]


def test_full_picture_rows_fill_the_width_exactly_and_keep_each_shape():
    rows, _ = tl.build(_pictures([1.5, 0.75, 1.0, 1.5, 0.8, 1.2, 1.0]), 1000, 200, 150, 40)
    for row in rows[:-1]:
        right = row.xs[-1] + row.widths[-1]
        assert right == pytest.approx(1000)
        for k in range(row.count):
            assert row.widths[k] / row.height == pytest.approx(_pictures([1.5, 0.75, 1.0, 1.5, 0.8, 1.2, 1.0])[row.start + k][1])
    assert all(r.height <= 200 * 1.0001 or r is not rows[-1] for r in rows)


def test_the_last_row_keeps_the_usual_height_instead_of_blowing_up():
    rows, _ = tl.build(_pictures([1.0, 1.0, 1.0, 1.0, 1.0, 1.0]), 1000, 200, 150, 40)
    assert rows[-1].height == 200 and rows[-1].xs[-1] + rows[-1].widths[-1] < 1000


def test_extreme_shapes_are_held_in():
    rows, _ = tl.build(_pictures([0.2, 9.0]), 2000, 200, 150, 40)
    widths = rows[0].widths
    assert widths[0] / rows[0].height == pytest.approx(tl.MIN_ASPECT)
    assert widths[1] / rows[0].height == pytest.approx(tl.MAX_ASPECT)


def test_a_picture_wider_than_the_page_still_fits():
    rows, _ = tl.build(_pictures([1.7]), 100, 200, 150, 40)
    assert rows[0].widths[0] == pytest.approx(100)


def test_covers_sit_in_rows_of_equal_cells_with_room_for_their_names():
    rows, height = tl.build([(C, tl.COVER_ASPECT)] * 9, 1000, 200, 150, 40)
    columns = int((1000 + tl.COVER_GAP) // (150 + tl.COVER_GAP))
    assert [r.count for r in rows] == [columns, 9 - columns]
    first = rows[0]
    assert first.xs[-1] + first.widths[-1] == pytest.approx(1000)            # a full shelf meets both edges
    assert first.height == round(first.widths[0] / tl.COVER_ASPECT) and first.label == 40
    assert rows[1].y == first.y + first.height + 40 + tl.COVER_ROW_GAP
    assert height == rows[-1].bottom


def test_a_short_shelf_is_not_stretched():
    rows, _ = tl.build([(C, tl.COVER_ASPECT)] * 2, 1000, 200, 150, 40)
    assert rows[0].widths == [150, 150]


def test_folders_then_files_each_start_their_own_rows():
    shapes = [(C, tl.COVER_ASPECT)] * 2 + _pictures([1.0] * 3) + [(C, tl.COVER_ASPECT)]
    rows, _ = tl.build(shapes, 1000, 200, 150, 40)
    assert [(r.kind, r.start, r.count) for r in rows] == [(C, 0, 2), (P, 2, 3), (C, 5, 1)]
    assert rows[1].y == rows[0].bottom + tl.GROUP_GAP


def test_the_rows_near_a_window_and_a_rubber_band():
    rows, _ = tl.build(_pictures([1.0] * 40), 1000, 200, 150, 40)
    first, last = tl.rows_between(rows, 500, 900)
    assert all(rows[k].bottom >= 500 and rows[k].y <= 900 for k in range(first, last))
    assert first == 0 or rows[first - 1].bottom < 500
    assert last == len(rows) or rows[last].y > 900
    band = tl.hit(rows, 0, 0, 5, 5)                                         # the top-left corner: the first tile
    assert band == [0]
    everything = tl.hit(rows, 0, 0, 1000, rows[-1].bottom)
    assert everything == list(range(40))
    assert tl.hit(rows, 0, rows[0].bottom + 1, 1000, rows[0].bottom + 2) == []   # the gap between rows


def test_nothing_to_lay_out():
    assert tl.build([], 1000, 200, 150, 40) == ([], 0.0)
    assert tl.build(_pictures([1.0]), 0, 200, 150, 40) == ([], 0.0)


class _Source(QAbstractListModel):
    def __init__(self, shapes):
        super().__init__()
        self._shapes = shapes

    def rowCount(self, parent=QModelIndex()):
        return len(self._shapes)

    def data(self, index, role=Qt.DisplayRole):
        return None

    def shapes(self):
        return list(self._shapes)

    def change(self, shapes):
        self._shapes = shapes
        self.dataChanged.emit(self.index(0), self.index(len(shapes) - 1))


def test_the_model_holds_only_the_rows_near_the_window(qapp):
    rows = TileRows()
    rows.width = 1000
    rows.pictureHeight = 200
    rows.source = _Source(_pictures([1.0] * 500))
    assert rows.itemCount == 500 and rows.contentHeight > 10000
    rows.setViewport(0, 600)
    shown = rows.rowCount()
    assert 0 < shown < 20
    first_start = rows.data(rows.index(0), TileRows.StartRole)
    assert first_start == 0
    inserted, removed = [], []
    rows.rowsInserted.connect(lambda *a: inserted.append(a))
    rows.rowsRemoved.connect(lambda *a: removed.append(a))
    rows.setViewport(300, 600)                                             # a small scroll grows the window
    assert inserted and rows.rowCount() >= shown
    rows.setViewport(rows.contentHeight - 600, 600)                       # a jump to the end
    last = rows.index(rows.rowCount() - 1)
    assert rows.data(last, TileRows.StartRole) + rows.data(last, TileRows.TilesRole) == 500


def test_a_shape_learned_later_lays_the_page_out_again_but_other_changes_do_not(qapp):
    source = _Source(_pictures([1.0] * 10))
    rows = TileRows()
    rows.width = 1000
    rows.source = source
    rows.setViewport(0, 800)
    height, revision = rows.contentHeight, rows.revision
    source.change(_pictures([1.0] * 10))                                    # a favorite: same shapes
    assert rows.contentHeight == height and rows.revision == revision + 1
    source.change(_pictures([0.75] * 10))                                   # the real shapes arrived
    assert rows.contentHeight != height
    rect = rows.tileRect(0)
    assert rect["width"] / rect["height"] == pytest.approx(0.75)


def test_columns_put_each_picture_in_the_shortest_column():
    rows, height = tl.build(_pictures([0.5, 1.0, 1.0, 2.0, 0.75]), 1000, 200, 150, 40, mode="columns")
    width = rows[0].widths[0]
    assert all(r.widths == [width] for r in rows)                     # one column width
    for r in rows:                                                    # each as tall as its own shape
        assert r.height == pytest.approx(width / tl.clamp_aspect(_pictures([0.5, 1.0, 1.0, 2.0, 0.75])[r.start][1]))
    assert [r.y for r in rows] == sorted(r.y for r in rows)           # sorted by top, for the window
    assert height == pytest.approx(max(r.bottom for r in rows))


def test_a_tall_column_tile_starting_above_the_window_is_kept():
    rows, _ = tl.build(_pictures([0.75] + [1.7] * 30), 600, 200, 150, 40, mode="columns")
    tall = next(r for r in rows if r.start == 0)
    first, last = tl.rows_between(rows, tall.y + tall.height - 10, tall.y + tall.height + 300)
    assert tall in rows[first:last]


def test_grid_cells_are_square():
    rows, _ = tl.build(_pictures([0.5, 2.0, 1.0, 1.0, 1.0]), 1000, 200, 150, 40, mode="grid")
    assert all(w == pytest.approx(r.height) for r in rows for w in r.widths)
    assert rows[0].xs[-1] + rows[0].widths[-1] == pytest.approx(1000)
