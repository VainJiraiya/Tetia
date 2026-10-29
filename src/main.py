import signal
import sys
from pathlib import Path

# 1. This MUST be QApplication, not QGuiApplication
from PySide6.QtWidgets import QApplication 
from PySide6.QtQml import QQmlApplicationEngine

from models.mediaModel import MediaModel
from models.thumbModel import ThumbnailProvider
from models.file_picker import FilePicker

# NEW: Import the FolderModel so its @QmlElement decorator registers it with QML
from models.folderModel import FolderModel

if __name__ == "__main__":
    # 2. Initialize the full widget application here
    app = QApplication(sys.argv)

    # Enable Ctrl+C termination
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    engine = QQmlApplicationEngine()
    
    # Register the thumbnail provider
    engine.addImageProvider("thumbnail", ThumbnailProvider())

    # Point to main.qml inside the qml/ subfolder
    qml_file = Path(__file__).parent / "qml" / "main.qml"
    engine.load(str(qml_file))

    # Exit if the QML engine fails to load the file
    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())