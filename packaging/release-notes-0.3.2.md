## Tetia 0.3.2

Fixes, mostly for big libraries, private profiles and the player.

### Faster folders

- **Folders open at once.** Opening a folder shows what Tetia already knows about it right away, and checks it for new or removed files in the background. A big folder on a slow drive (or in a vault on an external disk) no longer freezes the window. A folder opened for the first time says "Reading this folder…" while it is read.
- **No file is read twice.** When the background indexer and an open folder reach the same folder together, the second one waits and then has nothing left to do.

### Private profiles

- **Switching out of a vault profile could fail** with "Couldn't lock the vault". Tetia now waits for its own background work (thumbnails, the programs it started) to let go of the vault's files before asking Plasma to lock it, and if something still holds them, it says which files.

### Pictures and the reader

- **Covers and thumbnails are sharp at any tile size.** Tiles ask for the thumbnail size they are drawn at, up to the 1024 px size, instead of always getting the smallest.
- **Reader pages are drawn at the width the screen needs**, sharp on high-DPI screens and without wasting memory on small windows.

### Player and purge

- **A remembered position past a video's end** (the file was replaced by a shorter one) now starts the video over, instead of marking it watched and skipping to the next episode.
- **The speed button's label is readable** (it was dark grey on black).
- **Purge mode's arrow keys keep working** after a button was clicked.
- **The tab bar is hidden in purge mode:** a tab click closed it and dropped the marked pictures without asking.

### Behind the scenes

- Tetia now remembers each picture's size and when it first saw each file (for the layouts coming next). This upgrades the library database: older versions of Tetia cannot open it afterwards.

### Install

- **Any distribution:** `git clone --branch v0.3.2 https://github.com/VainJiraiya/Tetia.git && cd Tetia && ./install.sh` (remove with `./uninstall.sh`).
- **Fedora / Nobara:** download the `.rpm` below for your Fedora version and run `sudo dnf install ./tetia-*.rpm` (remove with `sudo dnf remove tetia`).
- **Nix:** `nix run github:VainJiraiya/Tetia/v0.3.2`.
