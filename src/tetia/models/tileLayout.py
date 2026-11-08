# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where every tile of a page goes (no Qt, so it is easy to test).

Two kinds of tile, laid out differently on purpose:

* covers: folders, series, comics and books. A collection is a portrait cover, the same size as its
  neighbours, with its name under it, like books on a shelf: rows of equal cells.
* pictures: images and videos. They keep their own shape: justified rows, each as tall as it needs to be for
  its pictures to fill the width exactly, so nothing is cropped and no cell is left half empty. Only extreme
  shapes are held in (a panorama or a phone-tall strip would otherwise shrink a whole row to a sliver).

A page's tiles come in runs of one kind (folders first, then files); each run starts a new row.
"""
from bisect import bisect_right
from dataclasses import dataclass, field

COVER = "cover"
PICTURE = "picture"
HEADER = "header"             # a title over a group of tiles (no tiles in it)

COVER_ASPECT = 2 / 3          # width / height of a cover
MIN_ASPECT = 3 / 4            # a picture is never drawn narrower than this (a tall strip is cropped to it)...
MAX_ASPECT = 16 / 9           # ...nor wider than this

PICTURE_GAP = 6               # between pictures, across and down
COVER_GAP = 20                # between covers, across
COVER_ROW_GAP = 22            # between rows of covers (their names sit in it)
GROUP_GAP = 28                # between the covers and the pictures
HEADER_HEIGHT = 30            # a group's title, and the space under it


@dataclass
class Row:
    kind: str
    start: int                # the first tile's index in the page
    y: float
    height: float             # the pictures' (or covers') height; a cover row adds `label` under it
    label: float
    widths: list = field(default_factory=list)
    xs: list = field(default_factory=list)
    title: str = ""

    @property
    def count(self):
        return len(self.widths)

    @property
    def bottom(self):
        return self.y + self.height + self.label


def clamp_aspect(aspect: float) -> float:
    return min(MAX_ASPECT, max(MIN_ASPECT, aspect))


def _cover_rows(count, start, y, width, cover_width, label):
    columns = max(1, int((width + COVER_GAP) // (cover_width + COVER_GAP)))
    # the cells stretch a little so the shelf meets both edges, like the picture rows under it
    cell = (width - (columns - 1) * COVER_GAP) / columns if count >= columns else cover_width
    height = round(cell / COVER_ASPECT)
    rows = []
    for first in range(0, count, columns):
        n = min(columns, count - first)
        rows.append(Row(COVER, start + first, y, height, label, [cell] * n, [i * (cell + COVER_GAP) for i in range(n)]))
        y += height + label + COVER_ROW_GAP
    return rows, y - COVER_ROW_GAP


def _picture_rows(aspects, start, y, width, target):
    rows = []

    def close(first, items, height):
        nonlocal y
        widths, xs, x = [], [], 0.0
        for aspect in items:
            w = aspect * height
            widths.append(w)
            xs.append(x)
            x += w + PICTURE_GAP
        rows.append(Row(PICTURE, first, y, height, 0.0, widths, xs))
        y += height + PICTURE_GAP

    first, items, total = 0, [], 0.0
    for i, aspect in enumerate(aspects):
        items.append(aspect)
        total += aspect
        gaps = (len(items) - 1) * PICTURE_GAP
        if total * target + gaps >= width:
            close(start + first, items, (width - gaps) / total)
            first, items, total = i + 1, [], 0.0
    if items:
        # the last row keeps the usual height (stretched, two pictures would be enormous); it still fits the width
        gaps = (len(items) - 1) * PICTURE_GAP
        close(start + first, items, min(target, (width - gaps) / total))
    return rows, y - PICTURE_GAP


def _column_rows(aspects, start, y, width, target):
    """Pictures in columns of one width, each as tall as its shape needs, the next always in the shortest column
    (a tall picture gets more room than in a row). Each tile is a row of its own, sorted by its top."""
    column = target * 0.85
    count = max(1, int((width + PICTURE_GAP) // (column + PICTURE_GAP)))
    column = (width - (count - 1) * PICTURE_GAP) / count
    tops = [y] * count
    rows = []
    last = [None] * count
    for k, aspect in enumerate(aspects):
        c = min(range(count), key=lambda i: tops[i])
        height = column / aspect
        row = Row(PICTURE, start + k, tops[c], height, 0.0, [column], [c * (column + PICTURE_GAP)])
        rows.append(row)
        last[c] = row
        tops[c] += height + PICTURE_GAP
    # Even the ends out, so a group does not stop in a ragged edge before the next title: the last picture of each
    # column grows or shrinks towards the columns' average end (by a quarter of its height at most, so it is only
    # cropped a little at the tile)
    ends = [r for r in last if r is not None]
    if len(ends) == count and len(aspects) >= 2 * count:
        target = sum(r.y + r.height for r in ends) / count
        for r in ends:
            r.height = min(r.height * 1.25, max(r.height * 0.75, target - r.y))
    rows.sort(key=lambda r: r.y)
    return rows, max(r.y + r.height for r in ends) if ends else y


def _grid_rows(count, start, y, width, target):
    """Square cells, every picture cropped to fill its square: the most pictures at a glance."""
    columns = max(1, int((width + PICTURE_GAP) // (target + PICTURE_GAP)))
    cell = (width - (columns - 1) * PICTURE_GAP) / columns
    rows = []
    for first in range(0, count, columns):
        n = min(columns, count - first)
        rows.append(Row(PICTURE, start + first, y, cell, 0.0, [cell] * n, [i * (cell + PICTURE_GAP) for i in range(n)]))
        y += cell + PICTURE_GAP
    return rows, y - PICTURE_GAP


MODES = ("rows", "columns", "grid")


def build(shapes, width, picture_height, cover_width, cover_label, titles=None, mode="rows"):
    """`shapes`: (kind, aspect) per tile. `titles`: {index: title} for groups that start at that tile under a
    title of their own. `mode`: how pictures are laid out (rows, columns or a square grid). Returns
    (rows, content height)."""
    rows, y = [], 0.0
    if width <= 0:
        return rows, 0.0
    titles = titles or {}
    i = 0
    while i < len(shapes):
        kind = shapes[i][0]
        j = i + 1
        while j < len(shapes) and shapes[j][0] == kind and j not in titles:
            j += 1
        if rows:
            y += GROUP_GAP
        if i in titles:
            rows.append(Row(HEADER, i, y, HEADER_HEIGHT, 0.0, [], [], titles[i]))
            y += HEADER_HEIGHT
        if kind == COVER:
            run, y = _cover_rows(j - i, i, y, width, cover_width, cover_label)
        elif mode == "columns":
            run, y = _column_rows([clamp_aspect(a) for _, a in shapes[i:j]], i, y, width, picture_height)
        elif mode == "grid":
            run, y = _grid_rows(j - i, i, y, width, picture_height)
        else:
            run, y = _picture_rows([clamp_aspect(a) for _, a in shapes[i:j]], i, y, width, picture_height)
        rows.extend(run)
        i = j
    return rows, (max(r.bottom for r in rows) if rows else 0.0)


def tallest(rows) -> float:
    return max((row.height + row.label for row in rows), default=0.0)


def rows_between(rows, top, bottom, reach=None):
    """(first, last + 1): a run of rows (sorted by their top) holding every row that reaches into [top, bottom].
    `reach` (the tallest row, see tallest()) lets a tall tile that starts above the window be found too."""
    if not rows:
        return 0, 0
    reach = tallest(rows) if reach is None else reach
    ys = [row.y for row in rows]
    first = bisect_right(ys, top - reach)
    while first < len(rows) and rows[first].bottom < top and rows[first].y + reach < top:
        first += 1
    last = bisect_right(ys, bottom)
    return first, max(first, last)


def hit(rows, x0, y0, x1, y1):
    """The indices of the tiles that a rectangle (in layout coordinates) touches."""
    left, right = min(x0, x1), max(x0, x1)
    top, bottom = min(y0, y1), max(y0, y1)
    first, last = rows_between(rows, top, bottom)
    found = []
    for row in rows[first:last]:
        if row.bottom <= top or row.y >= bottom:
            continue
        for k in range(row.count):
            if row.xs[k] < right and row.xs[k] + row.widths[k] > left:
                found.append(row.start + k)
    return sorted(found)
