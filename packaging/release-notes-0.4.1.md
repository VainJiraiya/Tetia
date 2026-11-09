## Tetia 0.4.1

Faster on hard drives and in encrypted vaults, and private profiles keep more of themselves inside their vault.

### Faster

- **Folders are read with fewer, smaller reads.** A new file is opened once, in the order files lie on the disk, and fingerprinted from 64 KB at each end instead of 1 MB; a picture's size comes from the same read. On a vault on a hard drive, a first scan of 2,015 videos went from 218 s to 91 s, and of 218 small pictures from 3.3 s to 1.9 s.
- **Re-scans of unchanged folders cost almost nothing.** A file whose size and date haven't changed is no longer read or written back to the library.
- **Switching to a big tab is several times quicker.** The page is laid out once per switch instead of two to four times, and each tile reads its details faster. On an SSD, a tab of 4,000 pictures went from about 350 ms to about 85 ms.
- **Thumbnails already shown stay in memory** (up to 192 MB), so going back to a tab or to Home doesn't read them again.
- **Small comic covers are made once.** A cover whose page is smaller than the tile was made again from the archive every time it was shown.
- **Home keeps its tiles** when you come back to it, instead of rebuilding every row.

### Private profiles

- **Thumbnails are kept in one file** (`thumbnails.db`) in the profile's folder instead of thousands of small ones: about 2 ms a thumbnail instead of about 30 ms from a vault on a hard drive. Thumbnails from earlier versions move in by themselves the first time they are shown.
- **Video thumbnails no longer pass through a temporary file** outside the vault.
- **RAR and 7z comics are read into memory**, never unpacked into a temporary folder.
- **The log names nothing.** In a private profile, Tetia's messages, Qt's warnings and error reports leave out file names, paths, tags and searches (started from the menu, the log goes to the system log, outside the vault).

### For testing

- **`TETIA_TIMING=1`** (environment variable) makes Tetia count where its time goes: thumbnails found or made, what tab switches and Home read, and every moment the window stood still. It writes a summary of labels and numbers only, never a name, to the terminal and to `$XDG_RUNTIME_DIR/tetia-timing.txt`.

### Notes

- **Fingerprints changed.** Files keep their old fingerprint until they change, and a file renamed while Tetia was closed is still recognised (with its tags, favorite and progress). Nothing needs doing.
- **A vault on a spinning hard drive** works, but first visits to folders and first thumbnails are slow there; see the README.

### Install

- **Any distribution:** `git clone --branch v0.4.1 https://github.com/VainJiraiya/Tetia.git && cd Tetia && ./install.sh` (remove with `./uninstall.sh`).
- **Fedora / Nobara:** download the `.rpm` below for your Fedora version and run `sudo dnf install ./tetia-*.rpm` (remove with `sudo dnf remove tetia`).
- **Nix:** `nix run github:VainJiraiya/Tetia/v0.4.1`.
