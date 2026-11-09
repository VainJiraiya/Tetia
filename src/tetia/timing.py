# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the time goes, when asked: start Tetia with TETIA_TIMING=1.

Thumbnails (how each was found or made, and how long it took), what tab switches and Home ask of the disk, and
every moment the window stood still for 100 ms or more. Every 15 seconds that something happened, and when Tetia
quits, a summary goes to the terminal and to $XDG_RUNTIME_DIR/tetia-timing.txt (in memory, gone at logout; a
relaunch into another profile may lose the terminal): fixed labels and numbers only, never a name, so it is safe
to share and to run in a private profile.
"""
import atexit
import functools
import os
import sys
import threading
import time
from contextlib import contextmanager

ENABLED = os.environ.get("TETIA_TIMING") == "1"

_lock = threading.Lock()
_samples: dict = {}          # label -> [milliseconds]
_dirty = False
STALL_MS = 100               # the window standing still this long is counted


def record(label: str, ms: float):
    global _dirty
    if not ENABLED:
        return
    with _lock:
        _samples.setdefault(label, []).append(ms)
        _dirty = True


@contextmanager
def timed(label: str):
    if not ENABLED:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        record(label, (time.perf_counter() - start) * 1000)


def measured(label: str):
    """A function or slot timed under `label` (left untouched when timing is off)."""
    def wrap(fn):
        if not ENABLED:
            return fn

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            with timed(label):
                return fn(*args, **kwargs)
        return inner
    return wrap


def summary() -> str:
    with _lock:
        rows = sorted(_samples.items())
    lines = ["Tetia timing (ms)                          count    total   median      max"]
    for label, values in rows:
        ordered = sorted(values)
        lines.append("  %-38s %7d %8.0f %8.1f %8.1f" % (label, len(values), sum(values), ordered[len(ordered) // 2],
                                                         ordered[-1]))
    return "\n".join(lines)


def _report(force=False):
    global _dirty
    with _lock:
        due = _dirty or force
        _dirty = False
    if due and _samples:
        text = summary() + "\n"
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        try:
            with open(report_file(), "w") as f:
                f.write(text)
        except OSError:
            pass


def report_file() -> str:
    import tempfile
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "tetia-timing.txt")


def start(app=None):
    """Report every 15 seconds and at the end, and count the window's stalls (on the GUI thread's event loop)."""
    if not ENABLED:
        return

    def every_15_seconds():
        _report()
        timer = threading.Timer(15, every_15_seconds)
        timer.daemon = True
        timer.start()

    every_15_seconds()
    atexit.register(_report, True)

    if app is not None:
        from PySide6.QtCore import QTimer
        ticker = QTimer(app)
        ticker.setInterval(20)
        last = [time.perf_counter()]

        def tick():
            now = time.perf_counter()
            late = (now - last[0]) * 1000 - 20
            if late >= STALL_MS:
                record("window stood still", late)
            last[0] = now

        ticker.timeout.connect(tick)
        ticker.start()
        app._tetia_stall_timer = ticker          # kept alive with the application
