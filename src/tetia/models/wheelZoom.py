# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ctrl + mouse wheel, for QML.

A QML WheelHandler only reacts to exactly Ctrl with a vertical angle delta, so it
misses wheels and touchpads that report extra modifier flags, pixel deltas or a
sideways delta. This filter sees the event before the window delivers it."""
from PySide6.QtCore import QEvent, QObject, Property, Qt, Signal
from PySide6.QtQml import QmlElement

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

NOTCH = 120          # one wheel click, in angleDelta units
PIXELS_PER_NOTCH = 50


@QmlElement
class WheelZoom(QObject):
    targetChanged = Signal()
    enabledChanged = Signal()
    # +1 for wheel up (zoom in), -1 for wheel down
    stepped = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target = None
        self._enabled = True
        self._carried = 0.0

    @Property(QObject, notify=targetChanged)
    def target(self):
        return self._target

    @target.setter
    def target(self, obj):
        if obj is self._target:
            return
        if self._target is not None:
            self._target.removeEventFilter(self)
        self._target = obj
        if obj is not None:
            obj.installEventFilter(self)
        self.targetChanged.emit()

    @Property(bool, notify=enabledChanged)
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        if value != self._enabled:
            self._enabled = value
            self._carried = 0.0
            self.enabledChanged.emit()

    def eventFilter(self, watched, event):
        if not self._enabled or event.type() != QEvent.Type.Wheel:
            return False
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            return False
        angle, pixels = event.angleDelta(), event.pixelDelta()
        amount = angle.y() or angle.x()
        if not amount:
            amount = (pixels.y() or pixels.x()) * NOTCH / PIXELS_PER_NOTCH
        self._carried += amount
        while abs(self._carried) >= NOTCH:
            direction = 1 if self._carried > 0 else -1
            self._carried -= direction * NOTCH
            self.stepped.emit(direction)
        return True      # Ctrl + wheel is ours; the grid must not scroll too
