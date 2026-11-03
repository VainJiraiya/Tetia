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
        favoritesModel, file_picker, folderModel, gridModel, mediaActions,
        mediaModel, profileModel, searchModel, subfolderModel, tagModel,
    )


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # The profile must be chosen BEFORE any model opens the database or a cache
    # folder. A normal launch is always General; only a relaunch started by the
    # profile switcher passes --profile.
    from tetia.models import profiles
    profiles.activate(profiles.pop_profile_argument(argv))

    # QApplication, not QGuiApplication: the file dialogs need widgets
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication

    _register_qml_types()
    from tetia.models.thumbModel import ThumbnailProvider

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)

    # Enable Ctrl+C termination
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("thumbnail", ThumbnailProvider())
    engine.load(str(qml_main_file()))

    # Exit if the QML engine fails to load the file
    if not engine.rootObjects():
        return -1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
