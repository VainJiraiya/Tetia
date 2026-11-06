## Tetia 0.3.0: video, a reader, and shows

- **Video player** built on libmpv with hardware decoding. Single click plays or pauses, double-click the left or right third to skip 10 seconds, the middle for fullscreen. Pick subtitle and audio tracks, including separate files next to the video or in a `Subs` folder. In a folder of clips the arrows step through the videos and short clips loop.
- **Shows:** mark a video folder as a series and it opens a page with its poster, description, tags and the episodes by season. Season and episode numbers are read from the names (`S01E02`, `1x02`, `Ep 12`, `001`, `9.5`).
- **Watch progress:** Tetia remembers where you stopped in videos of 15 minutes or more, marks what you have watched, and shows progress bars, episode lengths and a Resume button. "Play from beginning" is in the right-click menu.
- **Page reader** for comics, PDFs and picture EPUBs: paged or long-strip, right-to-left, zoom, auto-scroll, your place kept per book.
- **Virtual folders:** sort a library without moving any files.
- **Tags:** a tag browser, tags in the picture viewer, and series that are tagged, rated and favorited as one item and found as one tile in a search.
- One tile layout for every grid.

libmpv is optional: without it, videos open in your default application.

### Install

- **Any distribution:** `git clone --branch v0.3.0 https://github.com/VainJiraiya/Tetia.git && cd Tetia && ./install.sh` (remove with `./uninstall.sh`).
- **Fedora / Nobara:** download the `.rpm` below for your Fedora version and run `sudo dnf install ./tetia-*.rpm` (remove with `sudo dnf remove tetia`).
- **Nix:** `nix run github:VainJiraiya/Tetia`.

The database is upgraded automatically on first start (schema v13). Back up `~/.local/share/tetia` first if you like.
