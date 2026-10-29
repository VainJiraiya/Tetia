

# MediaModel Overview

MediaModel bridges your system folders and your QML grid. It scans directories for media, watches for file updates automatically, and feeds formatted data to your interface.

### What You Pass In (Inputs)

* **Folder Path:** Pass in a folder path or QUrl string using `load_from_qurl()`. The model cleans the path, sets up real-time disk monitoring, and scans the folder for images and videos.
* **Filter Mode:** Set `filterMode` to `0` for All Media, `1` for Images Only, or `2` for Videos Only. The model swaps the active list instantly in memory without re-scanning your hard drive.

### What It Gives to QML (Outputs)

Assign `MediaModel` to your QML GridView or ListView to unlock three layout variables inside every grid cell:

* **`fileUri`**: Provides the exact formatted file URL string needed by QML Image and MediaPlayer components to display media.
* **`fileName`**: Provides the plain file name string to display beneath thumbnails.
* **`isVideo`**: Provides a True or False answer so your layout knows whether to display play icons or video badges over an item.

### Automatic Updates

* **Disk Monitoring:** If files are added, deleted, or renamed in the open folder on your computer, the model detects the change and updates your display automatically.
