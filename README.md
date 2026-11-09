# Tetia

*Tetia - a media library for manga, images and video.*

Tetia keeps your manga, pictures and videos in one place on KDE Plasma: browse
collections, tag and rate what is in them, and find anything with one search box.
It is built with Python, Qt Quick and Kirigami.

> **Status: early (0.4.1).** It is in daily use by its author, but expect rough
> edges. Developed and tested on NixOS with Plasma 6, PySide6 6.11 and Python 3.14;
> other setups are untested.

## Features

- **Home** - what you are in the middle of (manga, books and long videos partway),
  a card per tab with what your library holds, the boards you pinned, your favorites,
  and the files added lately. Nothing on it is picked for you.
- **Library** - add folders under *Images*, *Videos*, *Manga* or *EBooks*. A tab shows
  what is in them: folders, series and virtual folders as portrait covers (with a cover
  you can choose), then each folder's loose files under its own title. Subfolders nest,
  with a breadcrumb trail; a subfolder only shows if something inside it matches the
  current tab.
- **Browsing** - pictures and videos keep their own shape, in rows, columns
  (masonry) or a grid of squares, remembered per folder; natural order ("Chapter 2"
  before "Chapter 10").
  Thumbnails use the shared freedesktop cache, so Dolphin and Gwenview reuse them.
  Images open in a full-screen viewer. Comics (CBZ, CBR and friends), PDFs and
  EPUBs made of page pictures open in the built-in reader (below), and videos in the
  built-in player (below); text EPUBs open in your default application.
  PDFs show up in both the Manga and the Books tab, since both are common for manga.
- **Reader** - paged or long-strip layout (webtoons), left-to-right or right-to-left,
  mouse-wheel page turning, zoom by double-click or Ctrl + scroll, a page slider,
  auto-scroll for strips, cards for the next and previous chapter, and your place
  remembered per book. A series opens at the first chapter you have not finished.
  The Help tab in the reader's side panel lists every key and gesture.
- **Video player** - built on libmpv, with hardware decoding. Single click plays or
  pauses; double-click the left or right third to skip 10 seconds, or the middle for
  fullscreen. Pick subtitle and audio tracks, including separate files next to the
  video (or in a `Subs` folder). In a folder of clips the arrows go to the previous
  and next video like the picture viewer, and short clips loop. Videos of 15 minutes
  or more resume where you stopped, and watched ones are marked.
- **Shows** - mark a video folder as a series and it becomes one tile that opens a
  page with its poster, a description you type, tags, and the episodes by season, with
  progress bars and lengths. Seasons can be folders (`Season 1`) and episodes are
  numbered from their names (`S01E02`, `1x02`, `Ep 12`, `Dragon Ball 001`, even `9.5`).
  A series, manga or show, is one item: tag, rate and favorite it as a whole.
- **Boards** - a saved tag search shown as a collection, plus files put on it by
  hand: a file tagged later joins it by itself, and a file can be on any number of
  boards. Nothing on disk moves.
- **Virtual folders** - sort a library without touching the disk: select files or
  whole subfolders and put them in a named virtual folder inside the folder you are
  in. Virtual folders nest, and a thing lives in one place at a time, like in a real
  folder. Taking something out puts it back where it came from, and deleting a virtual
  folder gives everything back. Files on disk never move.
- **Tags** - five categories (creator, series, character, genre, content), a tag
  panel with suggestions, and bulk tagging. Select items by clicking, with Ctrl or
  Shift, or by dragging a rectangle.
- **Ratings and favorites** - rate items General, Suggestive, Mature or Explicit;
  favorite items and whole collections and find them on *Home*.
- **Search** - one box for tags and file names, for example
  `series:starfall character:mira -chibi type:photo rating:general`. From the top
  level it searches your whole library; inside a folder, that folder and its
  subfolders. It suggests as you type, shows your terms as chips, and indexes your
  library in the background. A tag sidebar narrows the results or leaves a tag out,
  and a tag's page can look in one folder, its tab, or everywhere. The (i) button in the search bar explains the syntax.
- **Keeps track of your files** - move or rename a file and it keeps its tags and
  favorites; a file that disappears is marked missing rather than forgotten.
  Trashing moves files to the system Trash.
- **Private profiles** - a separate library, tags, covers and thumbnails that never
  touch your normal profile or the shared thumbnail cache. Encrypted in a KDE Plasma
  Vault if you have one (see below), or kept in a separate, unencrypted folder.

Not there yet: a reader for text e-books, an editor for tag
aliases and implications (search already honours them), importing tags from
ComicInfo.xml, and any platform other than Linux.

## Requirements

Python 3.10 or newer and PySide6 come from pip (or your distribution). Tetia also
needs a few things that pip cannot install; get them from your distribution:

| Needed for | Package (typical names) |
|---|---|
| The interface (required) | **Kirigami** (`kirigami`, `qml6-module-org-kde-kirigami`) and **qqc2-desktop-style** |
| Icons (required) | **Breeze icons** (`breeze-icon-theme`) |
| Playing videos | **libmpv** (`mpv-libs`, `libmpv2`, `libmpv-dev`) |
| Video thumbnails in the grid | **ffmpegthumbnailer** |
| Video covers | **ffmpeg** (provides `ffmpeg` and `ffprobe`) |
| SQLite | version 3.35 or newer (almost always already the case) |

Without libmpv videos open in your default application instead of the built-in
player. Without ffmpegthumbnailer videos show a placeholder instead of a thumbnail,
and without ffmpeg you cannot use a video frame as a folder cover. Everything else
works.

> pip's PySide6 bundles its own copy of Qt, which usually cannot see the Kirigami
> your distribution installed. Prefer your distribution's PySide6 package
> (`python3-pyside6`, `pyside6`, ...) so that Qt, Kirigami and Tetia agree.

## Install

**With the script** (any distribution; installs for your user only, no root):

```sh
git clone --branch v0.4.1 https://github.com/VainJiraiya/Tetia.git
cd Tetia
./install.sh          # checks the requirements above and tells you what is missing
```

It puts a `tetia` command in `~/.local/bin` and an entry in the application menu.
Run `./install.sh` again to upgrade. To remove it: `./uninstall.sh` (your library is
kept; `./uninstall.sh --purge` deletes that too, after asking).

**Fedora and Nobara:** download the `.rpm` from the
[releases page](https://github.com/VainJiraiya/Tetia/releases) and run
`sudo dnf install ./tetia-*.rpm`. It pulls in the requirements for you. Remove it with
`sudo dnf remove tetia`. The package is built for one Fedora version, so use the one
made for yours (`cat /etc/os-release`).

**Nix:** `nix run github:VainJiraiya/Tetia`, or add `tetia.packages.${system}.default`
from this flake to your system packages.

**By hand:** see below.

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

A vault on a spinning hard drive works, but the first visit to each folder and the
first thumbnail of each file are slow there: encryption adds work to every file read,
and a hard drive pays for each one with a seek. After that, thumbnails and pages come
from memory and from Tetia's own caches. For a large private library, an SSD makes
the first visits far quicker.

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
