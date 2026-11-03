# Tetia

*Tetia - a media library for manga, images and video.*

Tetia keeps your manga, pictures and videos in one place on KDE Plasma: browse
collections, tag and rate what is in them, and find anything with one search box.
It is built with Python, Qt Quick and Kirigami.

> **Status: early (0.1.0).** It is in daily use by its author, but expect rough
> edges. Developed and tested on NixOS with Plasma 6, PySide6 6.11 and Python 3.14;
> other setups are untested.

## Features

- **Collections** - add folders under *Photos*, *Videos*, *Manga* or *Books*. Each
  folder is a tile with a cover (its first picture, or one you choose). Subfolders
  nest, with a breadcrumb trail; a subfolder only shows if
  something inside it matches the current tab.
- **Browsing** - a thumbnail grid in natural order ("Chapter 2" before "Chapter 10").
  Thumbnails use the shared freedesktop cache, so Dolphin and Gwenview reuse them.
  Images open in a full-screen viewer; videos, manga archives (CBZ and friends) and
  books open in your default application (there is no built-in player or reader yet).
- **Tags** - five categories (creator, series, character, genre, content), a tag
  panel with suggestions, and bulk tagging. Select items by clicking, with Ctrl or
  Shift, or by dragging a rectangle.
- **Ratings and favorites** - rate items General, Suggestive, Mature or Explicit;
  favorite items and whole collections and find them on the *Favorites* tab.
- **Search** - one box for tags and file names, for example
  `series:starfall character:mira -chibi type:photo rating:general`. From the top
  level it searches your whole library; inside a folder, that folder and its
  subfolders. It suggests as you type, shows your terms as chips, and indexes your
  library in the background. The (i) button in the search bar explains the syntax.
- **Keeps track of your files** - move or rename a file and it keeps its tags and
  favorites; a file that disappears is marked missing rather than forgotten.
  Deleting moves files to the system trash.
- **Private profiles** - a separate library, tags, covers and thumbnails that never
  touch your normal profile or the shared thumbnail cache. Encrypted in a KDE Plasma
  Vault if you have one (see below), or kept in a separate, unencrypted folder.

Not there yet: a built-in video player, a comic/e-book reader, an editor for tag
aliases and implications (search already honours them), importing tags from
ComicInfo.xml, and any platform other than Linux.

## Requirements

Python 3.10 or newer and PySide6 come from pip (or your distribution). Tetia also
needs a few things that pip cannot install; get them from your distribution:

| Needed for | Package (typical names) |
|---|---|
| The interface (required) | **Kirigami** (`kirigami`, `qml6-module-org-kde-kirigami`) and **qqc2-desktop-style** |
| Icons (required) | **Breeze icons** (`breeze-icon-theme`) |
| Video thumbnails in the grid | **ffmpegthumbnailer** |
| Video covers | **ffmpeg** (provides `ffmpeg` and `ffprobe`) |
| SQLite | version 3.35 or newer (almost always already the case) |

Without ffmpegthumbnailer videos show a placeholder instead of a thumbnail, and
without ffmpeg you cannot use a video frame as a folder cover. Everything else works.

> pip's PySide6 bundles its own copy of Qt, which usually cannot see the Kirigami
> your distribution installed. Prefer your distribution's PySide6 package
> (`python3-pyside6`, `pyside6`, ...) so that Qt, Kirigami and Tetia agree.

## Install from source

```sh
git clone https://github.com/VainJiraiya/Tetia.git
cd Tetia
python -m venv --system-site-packages .venv     # sees the distribution's PySide6
.venv/bin/pip install --no-deps .
.venv/bin/tetia
```

`--no-deps` stops pip from downloading its own PySide6 over the distribution's. If
you do want pip's PySide6, leave it out and make sure Kirigami is on `QML_IMPORT_PATH`.

Your data lives in `$XDG_DATA_HOME/tetia` (usually `~/.local/share/tetia`). Data
from early pre-release builds (`~/.local/share/GalleryApp`) is copied there on the
first start; the old folder is left untouched as a backup.

## Optional: encrypted private profiles with Plasma Vault

[KDE Plasma Vaults](https://userbase.kde.org/Plasma/Vaults) (the `plasma-vault`
package plus `gocryptfs` or CryFS) can hold a private profile. Tetia only asks the
Plasma Vault service to unlock and lock the vault: KDE shows its own password
dialog and Tetia never sees the password. The vault is locked again when you leave
the profile or close Tetia.

This is entirely optional and never required. Without it the profile dialog offers
a local private profile instead, which is separate from your normal one but **not**
encrypted, and tells you how to get encryption.

## Contributing

Bug reports, ideas and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Tetia is free software under the **GNU General Public License, version 3 or (at
your option) any later version** (`GPL-3.0-or-later`); see [LICENSE](LICENSE).

## AI assistance

Tetia is developed with the help of AI coding tools, mainly Claude Code
(Anthropic), under human direction: a person sets the goals, reviews and tests the
changes, and is responsible for what is released. Commits where an AI wrote
substantial parts carry a `Co-Authored-By` trailer. If you use an AI tool for a
contribution, please say so in your pull request.
