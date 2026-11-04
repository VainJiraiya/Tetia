# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from tetia.models.wheelZoom import WheelZoom


@pytest.fixture
def zoom(qapp):
    window = QObject()          # stands in for the window: any object can have a filter
    wheel = WheelZoom()
    steps = []
    wheel.stepped.connect(steps.append)
    wheel.target = window
    return wheel, window, steps


def _send(window, modifiers, angle=QPoint(0, 0), pixels=QPoint(0, 0)):
    pos = QPointF(10, 10)
    event = QWheelEvent(pos, pos, pixels, angle, Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
    # sendEvent runs the installed filters; a filter that consumes the event returns True
    return QCoreApplication.sendEvent(window, event)


def test_ctrl_wheel_steps_once_per_notch(zoom):
    wheel, window, steps = zoom
    _send(window, Qt.ControlModifier, QPoint(0, 120))
    _send(window, Qt.ControlModifier, QPoint(0, -120))
    assert steps == [1, -1]


def test_extra_modifier_flags_still_count_as_ctrl(zoom):
    wheel, window, steps = zoom
    _send(window, Qt.ControlModifier | Qt.KeypadModifier, QPoint(0, 120))
    _send(window, Qt.ControlModifier | Qt.ShiftModifier, QPoint(0, 120))
    assert steps == [1, 1]


def test_small_touchpad_deltas_add_up(zoom):
    wheel, window, steps = zoom
    for _ in range(8):
        _send(window, Qt.ControlModifier, QPoint(0, 15))
    assert steps == [1]                      # 8 x 15 = 120


def test_pixel_only_and_sideways_wheels_work(zoom):
    wheel, window, steps = zoom
    _send(window, Qt.ControlModifier, pixels=QPoint(0, 50))
    _send(window, Qt.ControlModifier, QPoint(120, 0))
    assert steps == [1, 1]


def test_without_ctrl_or_when_disabled_nothing_happens(zoom):
    wheel, window, steps = zoom
    _send(window, Qt.NoModifier, QPoint(0, 120))
    wheel.enabled = False
    _send(window, Qt.ControlModifier, QPoint(0, 120))
    assert steps == []


def test_ctrl_wheel_is_consumed_so_the_grid_does_not_also_scroll(zoom):
    wheel, window, steps = zoom
    pos = QPointF(10, 10)
    event = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.ControlModifier,
                        Qt.NoScrollPhase, False)
    assert wheel.eventFilter(window, event) is True
    plain = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    assert wheel.eventFilter(window, plain) is False          # an ordinary wheel is left for the grid
