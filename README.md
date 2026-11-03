# Tetia

*Tetia - a media library for manga, images and video.*

## Requirements

Python 3.10 or newer and PySide6 are installed by pip. Tetia also needs some
things that pip cannot install; get them from your distribution:

| Needed for | Package (typical names) |
|---|---|
| The interface (required) | **Kirigami** (`kirigami`, `qml6-module-org-kde-kirigami`) and **qqc2-desktop-style** |
| Icons (required) | **Breeze icons** (`breeze-icon-theme`) |
| Video thumbnails in the grid | **ffmpegthumbnailer** |
| Video covers | **ffmpeg** (provides `ffmpeg` and `ffprobe`) |
| SQLite | version 3.35 or newer (almost always already the case) |

Without ffmpegthumbnailer videos show a placeholder instead of a thumbnail, and
without ffmpeg you cannot use a video frame as a folder cover. Everything else works.

**Optional:** [KDE Plasma Vaults](https://userbase.kde.org/Plasma/Vaults) (the
`plasma-vault` package plus `gocryptfs` or CryFS) lets you keep an encrypted
private profile. Tetia never needs it: without it the profile dialog offers a
local, non-encrypted private profile instead and says how to get encryption.
