# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""In a private profile, what Tetia writes to its log says what went wrong, not what it went wrong with.

Started from the application menu, Tetia's output goes to the system log, which lives outside any vault. So in a
private profile no file name, path, tag or search may reach it:

- Tetia's own messages keep their text, but every detail passed into them is hidden except numbers (an exit
  code, a media id); an error is reduced to its type, since its text often names a file.
- A traceback keeps where in Tetia it happened, and only the type of the error.
- Qt's warnings (a picture QML could not load names its address) lose any address or path in them, from where it
  starts to the end of the line; the location of Tetia's own QML files is kept.

General's log is left as it is.
"""
import logging
import re
import sys
import traceback
from collections.abc import Mapping

HIDDEN = "<hidden>"

# An address or an absolute path, to the end of the line (a file name may hold spaces, so nothing shorter is safe)
_PATHS = re.compile(r"(?:[a-z][a-z0-9+.-]*://|(?<![\w.:/~\x00-])/)[^\n]*", re.IGNORECASE)

_installed = False


def _plain(value):
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, BaseException):
        return type(value).__name__
    return HIDDEN


def scrub_text(text: str, keep=()) -> str:
    """`text` without addresses or paths. The prefixes in `keep` (Tetia's own QML folder, as a URL) stay, so a
    warning still says which of its files and lines it came from."""
    marks = {}
    for i, prefix in enumerate(p for p in keep if p):
        mark = "\x00%d\x00" % i
        marks[mark] = prefix
        text = text.replace(prefix, mark)
    text = _PATHS.sub(HIDDEN, text)
    for mark, prefix in marks.items():
        text = text.replace(mark, prefix)
    return text


def _short_traceback(exc_type, exc_tb) -> str:
    return "Traceback (most recent call last):\n" + "".join(traceback.format_tb(exc_tb)) + exc_type.__name__


def install(qml_folder_url: str = ""):
    """Hide the details from here on (call once the active profile is known to be private)."""
    global _installed
    if _installed:
        return
    _installed = True

    previous = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = {key: _plain(value) for key, value in record.args.items()}
            else:
                record.args = tuple(_plain(value) for value in record.args)
        if isinstance(record.msg, str):
            record.msg = scrub_text(record.msg)
        else:
            record.msg = _plain(record.msg)
        if record.exc_info and record.exc_info[0] is not None:
            record.exc_text = _short_traceback(record.exc_info[0], record.exc_info[2])
            record.exc_info = None
        return record

    logging.setLogRecordFactory(record_factory)

    def excepthook(exc_type, exc_value, exc_tb):
        sys.stderr.write(_short_traceback(exc_type, exc_tb) + "\n")

    sys.excepthook = excepthook

    from PySide6.QtCore import qInstallMessageHandler

    keep = (qml_folder_url,)

    def qt_messages(mode, context, message):
        sys.stderr.write(scrub_text(message, keep) + "\n")

    qInstallMessageHandler(qt_messages)
