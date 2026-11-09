# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""A private profile's log (the system log, outside the vault) says what went wrong but names no file, tag or
search."""
import os
import subprocess
import sys

from tetia import privatelog


def test_addresses_and_paths_are_hidden_to_the_end_of_the_line():
    scrub = privatelog.scrub_text
    assert scrub("Cannot open: image://thumbnail/vault/My Secret Book/p 01.png") == "Cannot open: <hidden>"
    assert scrub("no such file /run/media/x/Private/a b.mkv\nnext line") == "no such file <hidden>\nnext line"
    assert scrub("Failed to load folder covers/favorites: locked") == "Failed to load folder covers/favorites: locked"
    qml = "file:///opt/tetia/qml"
    assert scrub(qml + "/views/Grid.qml:12:5: Unable to assign [undefined] to int", (qml,)) == \
        qml + "/views/Grid.qml:12:5: Unable to assign [undefined] to int"
    assert scrub(qml + "/main.qml:7: Error opening file:///vault/secret.png", (qml,)) == \
        qml + "/main.qml:7: Error opening <hidden>"


SCRIPT = """
import logging, sys
from PySide6.QtCore import qWarning
from tetia import privatelog
privatelog.install("file:///opt/tetia/qml")
log = logging.getLogger("tetia.test")
where = "/vault/Secret Series/ch 01.cbz"
log.warning("Could not read %s: %s", where, FileNotFoundError(2, "No such file", where))
log.error("Failed to add tag to media_id=%d: %s", 12, "character:secret_name")
log.error("Search failed (%s): %s", "secret_query rating:explicit", ValueError("near secret_query"))
try:
    open(where)
except OSError:
    log.exception("Opening failed")
qWarning("file:///opt/tetia/qml/views/Grid.qml:40: QML Image: Cannot open: image://thumbnail" + where)
try:
    raise KeyError(where)
except KeyError as e:
    sys.excepthook(type(e), e, e.__traceback__)
"""


def test_nothing_private_reaches_the_log():
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    result = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, env=env, timeout=60)
    out = result.stderr
    assert result.returncode == 0, out
    assert "ecret" not in out                                         # no path, tag or search, anywhere
    assert "Could not read <hidden>: FileNotFoundError" in out
    assert "media_id=12" in out                                       # numbers stay
    assert "Search failed (<hidden>): ValueError" in out
    assert "Opening failed" in out and "Traceback" in out and "FileNotFoundError" in out
    assert "file:///opt/tetia/qml/views/Grid.qml:40: QML Image: Cannot open: <hidden>" in out
    assert "KeyError" in out
