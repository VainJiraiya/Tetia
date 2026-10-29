from PySide6.QtCore import QObject, Slot, Signal, QUrl
from PySide6.QtWidgets import QFileDialog
from PySide6.QtQml import QmlElement

# Register this module for QML
QML_IMPORT_NAME = "Gallery"
QML_IMPORT_MAJOR_VERSION = 1

@QmlElement
class FilePicker(QObject):
    # Signal emitted when a folder is successfully chosen
    folderSelected = Signal(str)

    @Slot()
    def openFolderDialog(self):
        # getExistingDirectory automatically uses the native KDE KIO dialog on Plasma
        folder_path = QFileDialog.getExistingDirectory(
            None,
            "Select Folder",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        # If the user selected a folder (didn't hit cancel)
        if folder_path:
            # Convert the raw local path to a QUrl string (file://...) to match your existing model logic
            qurl_string = QUrl.fromLocalFile(folder_path).toString()
            self.folderSelected.emit(qurl_string)