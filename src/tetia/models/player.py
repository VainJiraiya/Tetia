# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The video player for QML: `Player` (what is playing: position, tracks, volume...) and `MpvVideo` (the item that
draws it). libmpv decodes (hardware where it can) and draws into the item's OpenGL framebuffer; everything else,
the controls above all, is QML.

`Player.available` is false when libmpv is not installed; the host then opens videos in the system player.
"""
import ctypes
import logging
import os
import re
import weakref

import shiboken6

from PySide6.QtCore import Property, QObject, QRunnable, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QOpenGLContext
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import QQuickFramebufferObject, QQuickWindow

from tetia.models import mpv, profiles
from tetia.models.scanner import VIDEO_EXTENSIONS

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

# the render parameter types and flags of mpv's render API
_API_TYPE, _GL_INIT, _GL_FBO, _FLIP_Y, _X11_DISPLAY, _WL_DISPLAY = 1, 2, 3, 4, 8, 9

_GET_PROC = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
_UPDATE_CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p)

END_MARGIN = 2.0   # a start this close to a file's end (seconds) means the remembered spot no longer fits it



def _call_if_alive(stopper):
    """Call a weakly held method, unless its object is gone, or only its Python side is left (a closed player's
    Qt object is deleted first; touching its timer then raises RuntimeError)."""
    method = stopper()
    if method is not None and shiboken6.isValid(method.__self__):
        method()

class _Param(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("data", ctypes.c_void_p)]


class _GLInit(ctypes.Structure):
    _fields_ = [("get_proc_address", _GET_PROC), ("get_proc_address_ctx", ctypes.c_void_p)]


class _GLFbo(ctypes.Structure):
    _fields_ = [("fbo", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int), ("internal_format", ctypes.c_int)]


_LANGUAGES = {
    "eng": "English", "jpn": "Japanese", "spa": "Spanish", "fre": "French", "fra": "French", "ger": "German",
    "deu": "German", "ita": "Italian", "por": "Portuguese", "rus": "Russian", "kor": "Korean", "chi": "Chinese",
    "zho": "Chinese", "ara": "Arabic", "hin": "Hindi", "tha": "Thai", "vie": "Vietnamese", "ind": "Indonesian",
    "pol": "Polish", "dut": "Dutch", "nld": "Dutch", "swe": "Swedish", "tur": "Turkish", "und": "Unknown",
}


def track_label(track: dict, position: int) -> str:
    """"Japanese", "English - Commentary", or "Track 2" for a track the file does not name."""
    lang = _LANGUAGES.get(track.get("lang", ""), track.get("lang", "").upper())
    title = track.get("title", "")
    if track.get("external") and re.search(r"\.[A-Za-z0-9]{2,4}$", title):
        title = ""              # mpv names a separate file's track after the file ("eng.srt"): no use as a label
    if lang and title and title.casefold() != lang.casefold():
        label = "%s - %s" % (lang, title)
    else:
        label = lang or title or "Track %d" % position
    return label + " (external)" if track.get("external") else label


def _native_display():
    """The display Qt draws on, which mpv shares for hardware decoding without a copy: (param type, pointer)."""
    try:
        from PySide6.QtGui import QNativeInterface
        iface = QGuiApplication.instance().nativeInterface()
        if isinstance(iface, QNativeInterface.QWaylandApplication):
            return _WL_DISPLAY, int(iface.display())
        if isinstance(iface, QNativeInterface.QX11Application):
            return _X11_DISPLAY, int(iface.display())
    except Exception as e:           # no native interface: mpv falls back to copying frames
        logger.debug("No native display for mpv: %s", e)
    return None


@QmlElement
class Player(QObject):
    availableChanged = Signal()
    stateChanged = Signal()
    positionChanged = Signal()
    tracksChanged = Signal()
    frameReady = Signal()
    errorChanged = Signal()
    endReached = Signal()

    _extra_options: dict = {}          # tests: no window and no sound

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mpv = None
        self._ctx = ctypes.c_void_p()
        self._callbacks = []           # the ctypes callbacks must outlive the render context
        self._pending = ""
        self._loading = False
        self._loading_ticks = 0
        self._loaded = False
        self._paused = False
        self._ended = False
        self._position = 0.0
        self._start = 0.0
        self._restarting = False
        self._duration = 0.0
        self._volume = 100.0
        self._muted = False
        self._speed = 1.0
        self._title = ""
        self._error = ""
        self._hwdec = ""
        self._audio = []
        self._subs = []
        self._track_key = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        # a file held open would keep a vault from locking (a weak reference: a closed player is not kept alive)
        stopper = weakref.WeakMethod(self.stop)
        profiles.add_release_hook(lambda: _call_if_alive(stopper), order=0)

    # ---- the engine ------------------------------------------------------------------------------

    @Property(bool, constant=True)
    def available(self):
        return mpv.available()

    def _engine(self):
        if self._mpv is None:
            try:
                self._mpv = mpv.Mpv({
                    "vo": "libmpv", "hwdec": "auto-safe", "keep-open": "yes", "terminal": "no",
                    "audio-display": "no", "input-default-bindings": "no", "input-vo-keyboard": "no",
                    "osc": "no", "volume-max": "100", "force-seekable": "yes",
                    # separate files beside the video: subtitles and audio with a similar name, also in a Subs folder
                    "sub-auto": "fuzzy", "audio-file-auto": "fuzzy",
                    "sub-file-paths": "Subs:subs:Subtitles:subtitles:Sub:sub",
                    "audio-file-paths": "Audio:audio:Dubs:dubs",
                    "idle": "yes", **self._extra_options,
                })
            except mpv.MpvError as e:
                self._set_error(str(e))
                return None
        return self._mpv

    # ---- playing ---------------------------------------------------------------------------------

    @Slot(str, result=bool)
    def canPlay(self, location: str) -> bool:
        """Whether this file is a video the player opens (libmpv is installed and it is a video file)."""
        path = QUrl(location).toLocalFile() if location.startswith("file:") else location
        return mpv.available() and os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS

    @Slot(str, float)
    def load(self, location: str, start: float = 0.0):
        """Play a file (a file:// address or a path), from `start` seconds."""
        engine = self._engine()
        if engine is None:
            return
        path = QUrl(location).toLocalFile() if location.startswith("file:") else location
        self._set_error("")
        self._loaded = False
        self._ended = False
        self._position = float(start)
        self._start = float(start)
        self._restarting = False
        self._duration = 0.0
        self._audio, self._subs, self._track_key = [], [], None
        self._title = os.path.basename(path)
        engine.set("start", "%.3f" % max(0.0, start) if start > 1 else "0")
        engine.set("pause", False)
        self._pending = path
        self._loading, self._loading_ticks = True, 0
        # mpv sets its video output up when a file starts, and the output needs the render context, which only the
        # drawing can make (it needs the OpenGL context): so the first file waits for the first draw
        if self._ctx or self._headless():
            self._start_pending()
        self._timer.start()
        self.frameReady.emit()          # the item may have drawn before there was an engine: draw again, which starts the output
        self.stateChanged.emit()
        self.tracksChanged.emit()
        self.positionChanged.emit()

    def _headless(self) -> bool:
        return self._extra_options.get("vo", "libmpv") != "libmpv"

    def _start_pending(self):
        path, self._pending = self._pending, ""
        if path and self._mpv is not None and not self._mpv.command("loadfile", path, "replace"):
            self._loading = False
            self._set_error("Couldn't play this file")

    @Slot()
    def stop(self):
        self._timer.stop()
        self._loading = False
        if self._mpv is not None:
            self._mpv.command("stop")
        if self._loaded:
            self._loaded = False
            self.stateChanged.emit()

    @Slot()
    def togglePause(self):
        self.setPaused(not self._paused)

    @Slot(bool)
    def setPaused(self, paused: bool):
        if self._mpv is not None:
            self._mpv.set("pause", paused)
            self._paused = paused
            if not paused and self._ended:
                self._mpv.command("seek", "0", "absolute")
            self.stateChanged.emit()

    @Slot(float)
    def seek(self, seconds: float):
        """Skip forward (positive) or back (negative) by `seconds`."""
        if self._mpv is not None and self._loaded:
            self._mpv.command("seek", "%.2f" % seconds, "relative+exact")    # exact: a keyframe seek lands seconds off

    @Slot(float)
    def seekTo(self, seconds: float):
        if self._mpv is not None and self._loaded:
            self._position = max(0.0, min(seconds, self._duration or seconds))
            self._mpv.command("seek", "%.2f" % self._position, "absolute+exact")
            self.positionChanged.emit()

    @Slot(float)
    def setVolume(self, volume: float):
        if self._mpv is not None:
            self._volume = max(0.0, min(100.0, volume))
            self._mpv.set("volume", "%.0f" % self._volume)
            self.stateChanged.emit()

    @Slot()
    def toggleMute(self):
        if self._mpv is not None:
            self._muted = not self._muted
            self._mpv.set("mute", self._muted)
            self.stateChanged.emit()

    @Slot(bool)
    def setLoop(self, loop: bool):
        """Start over at the end instead of stopping (short clips)."""
        if self._mpv is not None:
            self._mpv.set("loop-file", "inf" if loop else "no")

    @Slot(float)
    def setSpeed(self, speed: float):
        if self._mpv is not None:
            self._speed = max(0.25, min(4.0, speed))
            self._mpv.set("speed", "%.2f" % self._speed)
            self.stateChanged.emit()

    @Slot(int)
    def setAudioTrack(self, track_id: int):
        if self._mpv is not None:
            self._mpv.set("aid", track_id if track_id > 0 else "no")

    @Slot(int)
    def setSubtitleTrack(self, track_id: int):
        """A subtitle track by its id; 0 turns the subtitles off."""
        if self._mpv is not None:
            self._mpv.set("sid", track_id if track_id > 0 else "no")

    @Slot(str)
    def addSubtitleFile(self, location: str):
        if self._mpv is not None:
            path = QUrl(location).toLocalFile() if location.startswith("file:") else location
            self._mpv.command("sub-add", path, "select")

    # ---- what the controls show --------------------------------------------------------------------

    def _set_error(self, text: str):
        if text != self._error:
            self._error = text
            self.errorChanged.emit()

    @Property(str, notify=errorChanged)
    def error(self):
        return self._error

    @Property(bool, notify=stateChanged)
    def loaded(self):
        return self._loaded

    @Property(bool, notify=stateChanged)
    def paused(self):
        return self._paused

    @Property(bool, notify=stateChanged)
    def ended(self):
        return self._ended

    @Property(float, notify=positionChanged)
    def position(self):
        return self._position

    @Property(float, notify=stateChanged)
    def duration(self):
        return self._duration

    @Property(float, notify=stateChanged)
    def volume(self):
        return self._volume

    @Property(bool, notify=stateChanged)
    def muted(self):
        return self._muted

    @Property(float, notify=stateChanged)
    def speed(self):
        return self._speed

    @Property(str, notify=stateChanged)
    def title(self):
        return self._title

    @Property(str, notify=stateChanged)
    def hwdec(self):
        """The hardware decoder in use ("" while decoding in software)."""
        return self._hwdec

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self):
        """[{id, label, selected}]"""
        return self._audio

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self):
        """[{id, label, selected}]; the host adds its own "Off" row."""
        return self._subs

    @Slot()
    def _poll(self):
        engine = self._mpv
        if engine is None or not engine.handle:
            return
        changed = False
        duration = engine.get_double("duration")
        if self._loading:
            self._loading_ticks += 1
            if duration is not None:
                self._loading, self._loaded, changed = False, True, True
                if self._start > 1 and self._start >= duration - END_MARGIN:
                    # The remembered spot is past this file's end (it was replaced by a shorter one):
                    # start over, not at the end, which would count it as watched and move on
                    engine.command("seek", "0", "absolute+exact")
                    self._restarting = True
                    self._position = 0.0
                    self.positionChanged.emit()
            elif engine.get_flag("idle-active") and self._loading_ticks > 3:
                self._loading = False
                self._set_error("Couldn't play this file")
        if self._loaded and self._restarting:
            position = engine.get_double("time-pos")
            if position is None or position >= (duration or 0.0) - END_MARGIN:
                if changed:                 # until the seek lands, mpv still says "at the end": don't believe it
                    self.stateChanged.emit()
                return
            self._restarting = False
        if self._loaded:
            position = engine.get_double("time-pos")
            if position is not None and abs(position - self._position) >= 0.05:
                self._position = position
                self.positionChanged.emit()
            values = {
                "_duration": duration or 0.0,
                "_paused": bool(engine.get_flag("pause")),
                "_volume": engine.get_double("volume") or 0.0,
                "_muted": bool(engine.get_flag("mute")),
                "_speed": engine.get_double("speed") or 1.0,
                "_hwdec": (lambda v: "" if v in (None, "no") else v)(engine.get("hwdec-current")),
            }
            for name, value in values.items():
                if getattr(self, name) != value:
                    setattr(self, name, value)
                    changed = True
            title = engine.get("media-title") or self._title
            if title != self._title:
                self._title, changed = title, True
            ended = bool(engine.get_flag("eof-reached"))
            if ended != self._ended:
                self._ended, changed = ended, True
                if ended:
                    self.endReached.emit()
            key = (engine.get_double("track-list/count"), engine.get("aid"), engine.get("sid"))
            if key != self._track_key:
                self._track_key = key
                self._read_tracks(engine)
        if changed:
            self.stateChanged.emit()

    def _read_tracks(self, engine):
        audio, subs = [], []
        for track in engine.tracks():
            bucket = audio if track["type"] == "audio" else subs if track["type"] == "sub" else None
            if bucket is not None:
                bucket.append({"id": track["id"], "label": track_label(track, len(bucket) + 1),
                               "selected": track["selected"]})
        self._audio, self._subs = audio, subs
        self.tracksChanged.emit()

    # ---- drawing (called on the render thread, with the OpenGL context current) -----------------------

    def render(self, fbo: int, width: int, height: int):
        engine = self._mpv
        if engine is None or not engine.handle:
            return
        lib = mpv.library()
        if not self._ctx:
            gl = QOpenGLContext.currentContext()

            def get_proc(_ctx, name):
                address = gl.getProcAddress(name.decode())
                return int(address) if address else None

            get_proc_cb = _GET_PROC(get_proc)
            init = _GLInit(get_proc_cb, None)
            api = ctypes.c_char_p(b"opengl")
            params = [_Param(_API_TYPE, ctypes.cast(api, ctypes.c_void_p)),
                      _Param(_GL_INIT, ctypes.cast(ctypes.pointer(init), ctypes.c_void_p))]
            display = _native_display()
            if display:
                params.append(_Param(display[0], display[1]))
            params.append(_Param(0, None))
            array = (_Param * len(params))(*params)
            lib.mpv_render_context_create.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                                      ctypes.POINTER(_Param)]
            if lib.mpv_render_context_create(ctypes.byref(self._ctx), engine.handle, array) < 0:
                self._ctx = ctypes.c_void_p()
                self._set_error("Couldn't start video output")
                return
            update_cb = _UPDATE_CB(self._on_update)         # called from an mpv thread     # called from an mpv thread
            lib.mpv_render_context_set_update_callback.argtypes = [ctypes.c_void_p, _UPDATE_CB, ctypes.c_void_p]
            lib.mpv_render_context_set_update_callback(self._ctx, update_cb, None)
            self._callbacks = [get_proc_cb, update_cb, init, api]
            self._start_pending()
        lib.mpv_render_context_update.argtypes = [ctypes.c_void_p]
        lib.mpv_render_context_update.restype = ctypes.c_uint64
        lib.mpv_render_context_update(self._ctx)
        target = _GLFbo(fbo, width, height, 0)
        flip = ctypes.c_int(0)
        lib.mpv_render_context_render.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Param)]
        array = (_Param * 3)(_Param(_GL_FBO, ctypes.cast(ctypes.pointer(target), ctypes.c_void_p)),
                             _Param(_FLIP_Y, ctypes.cast(ctypes.pointer(flip), ctypes.c_void_p)),
                             _Param(0, None))
        lib.mpv_render_context_render(self._ctx, array)

    def _on_update(self, _ctx):
        try:
            self.frameReady.emit()
        except RuntimeError:            # the player is gone; the callback is being taken away
            pass

    @Slot()
    def shutdown(self):
        """Stop and let go of mpv: the sound ends at once; the render context is freed on the render thread (it needs
        the OpenGL context), and mpv is closed after it."""
        self._timer.stop()
        self._pending = ""
        engine, self._mpv = self._mpv, None
        if engine is None:
            return
        engine.command("stop")
        ctx, callbacks, window = self._ctx, self._callbacks, getattr(self, "_window", None)
        self._ctx, self._callbacks = ctypes.c_void_p(), []
        if ctx:
            lib = mpv.library()
            lib.mpv_render_context_set_update_callback.argtypes = [ctypes.c_void_p, _UPDATE_CB, ctypes.c_void_p]
            lib.mpv_render_context_set_update_callback(ctx, _UPDATE_CB(0), None)
        job = _Cleanup(engine, ctx, callbacks)
        if ctx and window is not None:
            _jobs.append(job)
            job.finished = lambda: _jobs.remove(job) if job in _jobs else None
            window.scheduleRenderJob(job, QQuickWindow.BeforeSynchronizingStage)
            window.update()
        elif not ctx:
            job.run()
        # else: no window left to free the context in; the process is closing, which frees it


_jobs: list = []        # cleanups waiting for the render thread, kept alive until they ran


class _Cleanup(QRunnable):
    """Frees a render context and closes its mpv, on the render thread with the OpenGL context current."""

    def __init__(self, engine, ctx, callbacks):
        super().__init__()
        self.engine, self.ctx, self.callbacks = engine, ctx, callbacks
        self.finished = None
        self.setAutoDelete(False)

    def run(self):
        if self.ctx:
            lib = mpv.library()
            lib.mpv_render_context_free.argtypes = [ctypes.c_void_p]
            lib.mpv_render_context_free(self.ctx)
        self.engine.close()
        if self.finished:
            self.finished()


class _Renderer(QQuickFramebufferObject.Renderer):
    def __init__(self):
        super().__init__()
        self.player = None

    def synchronize(self, item):
        self.player = item.player

    def render(self):
        if self.player is not None:
            fbo = self.framebufferObject()
            self.player.render(fbo.handle(), fbo.width(), fbo.height())


@QmlElement
class MpvVideo(QQuickFramebufferObject):
    """The picture of a Player. Give it `player`; it fills its own area (the picture keeps its proportions)."""
    playerChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = None

    def createRenderer(self):
        return _Renderer()

    @Property(QObject, notify=playerChanged)
    def player(self):
        return self._player

    @player.setter
    def player(self, player):
        if player is self._player:
            return
        if self._player is not None:
            try:
                self._player.frameReady.disconnect(self.update)
            except (RuntimeError, TypeError):
                pass
        self._player = player
        if player is not None:
            player.frameReady.connect(self.update)
            player._window = self.window()
            self.windowChanged.connect(lambda window, p=player: setattr(p, "_window", window))
        self.playerChanged.emit()
        self.update()
