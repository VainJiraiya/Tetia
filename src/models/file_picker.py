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

    # Emitted when a cover image is chosen: (folder as passed in, local image path)
    coverImageSelected = Signal(str, str)

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

    @Slot(str)
    def openCoverImageDialog(self, folder_path: str):
        """Pick an image to use as the cover of `folder_path` (a file:// URI
        or a plain path). Opens in that folder."""
        start = QUrl(folder_path).toLocalFile() if folder_path.startswith("file:") else folder_path
        image_path, _ = QFileDialog.getOpenFileName(
            None,
            "Choose cover image",
            start,
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.avif *.jxl *.tif *.tiff);;All files (*)"
        )
        if image_path:
            self.coverImageSelected.emit(folder_path, image_path)
