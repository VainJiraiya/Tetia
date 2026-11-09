# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tetia's entry point: `tetia` (console script) or `python -m tetia`."""
import os
import signal
import sys
from importlib import resources
from pathlib import Path

APP_NAME = "Tetia"
# The reverse-DNS id of the desktop file and AppStream metadata (data/)
APP_ID = "io.github.VainJiraiya.Tetia"


def qml_main_file() -> Path:
    """main.qml inside the installed package (never relative to the working directory)."""
    return Path(str(resources.files("tetia").joinpath("qml", "main.qml")))


def _register_qml_types():
    """Import every model so its @QmlElement decorator registers it with QML
    (module "Tetia"). Must run after the profile has been chosen."""
    from tetia.models import (  # noqa: F401
        boardService, coverPicker, downloadService, favoritesModel, file_picker, folderModel, gridModel, mediaActions,
        mediaModel, metadataModel, player, playbackStore, profileModel, purgeSession, readerSession, searchModel, homeModel, showModel, subfolderModel, tagImportService, tagModel, tileRows, uiSettings, virtualFolderService, wheelZoom,
    )


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # Outside Plasma nothing selects a Qt Quick Controls style that matches
    # Kirigami; use the KDE desktop style unless the user chose one.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    # Bring data over from the old (GalleryApp) folder, once, before anything
    # creates the new one. The old folder is only ever copied from.
    from tetia import migration
    try:
        if migration.migrate_legacy_data():
            print(f"Tetia: copied your data from {migration.paths.legacy_data_dir()} "
                  f"to {migration.paths.data_dir()} (the old folder is left as a backup).")
    except migration.MigrationError as e:
        # Starting with an empty library would look like data loss; stop instead.
        print(f"Tetia could not migrate your data: {e}\nYour old data is untouched.", file=sys.stderr)
        return 1

    # The profile must be chosen BEFORE any model opens the database or a cache
    # folder. A normal launch is always General; only a relaunch started by the
    # profile switcher passes --profile.
    from tetia.models import profiles
    profiles.activate(profiles.pop_profile_argument(argv))
    if profiles.is_private():
        # the log goes to the system log, outside the vault: no paths, tags or searches in it
        from PySide6.QtCore import QUrl
        from tetia import privatelog
        privatelog.install(QUrl.fromLocalFile(str(qml_main_file().parent)).toString())

    # QApplication, not QGuiApplication: the file dialogs need widgets
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication

    _register_qml_types()
    from tetia.models.bookpages import BookPageProvider
    from tetia.models.readerSession import ReaderPageProvider
    from tetia.models.thumbModel import ThumbnailProvider

    # The video player draws through OpenGL (libmpv into a Qt Quick framebuffer item), so Qt Quick must use it too
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    from tetia import timing
    timing.start(app)                                    # (only with TETIA_TIMING=1: where the time goes)
    try:
        from importlib.metadata import version
        app.setApplicationVersion(version("tetia"))      # shown in About (from the installed package)
    except Exception:
        pass                                             # run from a source tree that was never installed
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)

    # Enable Ctrl+C termination
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("thumbnail", ThumbnailProvider())
    engine.addImageProvider("bookpage", BookPageProvider())
    engine.addImageProvider("readerpage", ReaderPageProvider())
    engine.load(str(qml_main_file()))

    # Exit if the QML engine fails to load the file
    if not engine.rootObjects():
        return -1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
