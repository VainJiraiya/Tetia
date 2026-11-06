# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""libmpv through ctypes: no Python package to install, and nothing breaks when the library is missing.

`available()` says whether libmpv can be loaded; everything else needs it. No Qt in here, so it can be tested
with the null video output (see tests/test_player.py). The OpenGL side (the render context) is in player.py.
"""
import ctypes
import ctypes.util
import locale
import logging
import weakref

logger = logging.getLogger(__name__)

# the property value formats of mpv_get_property
FORMAT_FLAG, FORMAT_DOUBLE = 3, 5

_lib = None
_tried = False


def library():
    """The loaded libmpv, or None if it is not installed."""
    global _lib, _tried
    if _tried:
        return _lib
    _tried = True
    for name in ("libmpv.so.2", "libmpv.so.1", ctypes.util.find_library("mpv")):
        if not name:
            continue
        try:
            _lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if _lib is None:
        logger.info("libmpv is not installed: videos open in the system player")
        return None
    c_void_p, c_char_p, c_int = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    _lib.mpv_create.restype = c_void_p
    _lib.mpv_initialize.argtypes = [c_void_p]
    _lib.mpv_set_option_string.argtypes = [c_void_p, c_char_p, c_char_p]
    _lib.mpv_set_property_string.argtypes = [c_void_p, c_char_p, c_char_p]
    _lib.mpv_get_property_string.argtypes = [c_void_p, c_char_p]
    _lib.mpv_get_property_string.restype = c_void_p
    _lib.mpv_get_property.argtypes = [c_void_p, c_char_p, c_int, c_void_p]
    _lib.mpv_free.argtypes = [c_void_p]
    _lib.mpv_command.argtypes = [c_void_p, ctypes.POINTER(c_char_p)]
    _lib.mpv_terminate_destroy.argtypes = [c_void_p]
    return _lib


def available() -> bool:
    return library() is not None


class MpvError(RuntimeError):
    pass


_live = weakref.WeakSet()


def live_count() -> int:
    """How many mpv instances are open (a player left running would show here)."""
    return sum(1 for m in _live if m.handle)


class Mpv:
    """One mpv instance: options, commands and properties. Not tied to any window."""

    def __init__(self, options: dict | None = None):
        lib = library()
        if lib is None:
            raise MpvError("libmpv is not installed")
        # mpv_create gives NULL (and the next call crashes) unless the numeric locale is "C"; Qt sets the user's
        locale.setlocale(locale.LC_NUMERIC, "C")
        self._lib = lib
        _live.add(self)
        self.handle = lib.mpv_create()
        if not self.handle:
            raise MpvError("mpv_create failed")
        for key, value in (options or {}).items():
            lib.mpv_set_option_string(self.handle, key.encode(), str(value).encode())
        if lib.mpv_initialize(self.handle) < 0:
            lib.mpv_terminate_destroy(self.handle)
            self.handle = None
            raise MpvError("mpv_initialize failed")

    def command(self, *args) -> bool:
        if not self.handle:
            return False
        items = [str(a).encode() for a in args] + [None]
        array = (ctypes.c_char_p * len(items))(*items)
        return self._lib.mpv_command(self.handle, array) >= 0

    def set(self, name: str, value) -> bool:
        if isinstance(value, bool):
            value = "yes" if value else "no"
        return bool(self.handle) and self._lib.mpv_set_property_string(self.handle, name.encode(), str(value).encode()) >= 0

    def get(self, name: str) -> str | None:
        """A property as text, None if mpv has no value for it now."""
        if not self.handle:
            return None
        raw = self._lib.mpv_get_property_string(self.handle, name.encode())
        if not raw:
            return None
        try:
            return ctypes.cast(raw, ctypes.c_char_p).value.decode(errors="replace")
        finally:
            self._lib.mpv_free(raw)

    def get_double(self, name: str) -> float | None:
        if not self.handle:
            return None
        value = ctypes.c_double()
        status = self._lib.mpv_get_property(self.handle, name.encode(), FORMAT_DOUBLE, ctypes.byref(value))
        return value.value if status >= 0 else None

    def get_flag(self, name: str) -> bool | None:
        if not self.handle:
            return None
        value = ctypes.c_int()
        status = self._lib.mpv_get_property(self.handle, name.encode(), FORMAT_FLAG, ctypes.byref(value))
        return bool(value.value) if status >= 0 else None

    def tracks(self) -> list[dict]:
        """[{id, type: video|audio|sub, title, lang, selected, default, codec}] of the file playing."""
        count = int(self.get_double("track-list/count") or 0)
        found = []
        for i in range(count):
            base = "track-list/%d/" % i
            found.append({
                "id": int(self.get_double(base + "id") or 0),
                "type": self.get(base + "type") or "",
                "title": self.get(base + "title") or "",
                "lang": self.get(base + "lang") or "",
                "codec": self.get(base + "codec") or "",
                "selected": bool(self.get_flag(base + "selected")),
                "default": bool(self.get_flag(base + "default")),
                "external": bool(self.get_flag(base + "external")),     # a separate file beside the video
            })
        return found

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            self._lib.mpv_terminate_destroy(handle)
