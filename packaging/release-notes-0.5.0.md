## Tetia 0.5.0

Tags from your files, downloads with gallery-dl and yt-dlp, and a way to send files into a private profile.

### Tags from your files

- **ComicInfo.xml**: a comic's writer, artists, series, characters, genres and tags become tags in their categories. Its age rating sets the content rating, its summary a series' description, and "manga, right to left" a series' format.
- **Downloader metadata**: the `.json` gallery-dl writes beside a download, and yt-dlp's `.info.json`, become tags too. That covers Danbooru, Gelbooru and other boorus, e621, E-Hentai, Pixiv, X and YouTube, plus a general fallback. A booru's rating sets the content rating.
- **A series takes the tags all its chapters share.** A new chapter alone never replaces them.
- **Your own tags are never touched.** A re-import only replaces what the previous import gave. A tag you add yourself is yours, even if an import gave it first. A rating, description or format is only filled in where none was set.
- **New and changed files are read as they arrive.** "Re-import tags" in a file's or folder's menu reads them again, including files Tetia already knew. "Import Tags from Files" in the main menu turns importing off.

### Downloads

- **A download button on the Images and Videos tabs** when gallery-dl or yt-dlp is installed. Paste an address: video sites go to yt-dlp, everything else to gallery-dl, or you can pick the tool when both are installed.
- **Where the files land:** a library folder, optionally a new folder of the name you give, and optionally a board (an existing one or a new one). The files arrive already tagged.
- **Only some results:** "from/to" keeps part of a search, gallery or playlist. "Videos up to" caps yt-dlp's resolution.
- **A queue**, one download at a time, with each download's file count, gallery-dl's or yt-dlp's own error message, and cancel.
- **Logins and site settings** stay in each tool's own configuration. "Logins and site settings" opens it in your editor, creating it if needed. For gallery-dl it lists which sites have a section; nothing else is read from it.
- **Booru tag categories:** Tetia asks gallery-dl for them (its `tags` option), so Gelbooru's tags are sorted into artist, character, series and the rest. It costs one more request per post.

### Move to Private Profile

- **In select mode and in a file's menu** when a private profile exists. Pick the profile; a locked vault is unlocked first (KDE asks for the password). Then pick the folder: its library folders inside the vault, or the vault itself. It can be locked again when done.
- **Safe:** each file is copied, checked and only then deleted, so a file that can't be copied safely stays where it was. Its metadata and subtitles go with it, and so do its tags, favorite and rating.
- **Nothing left behind:** the file's entry here, its tags, progress, places on boards and in virtual folders, any tag only it had, and its thumbnails go. The original is deleted rather than trashed, because the Trash would keep a copy outside the vault.

### Fixes and smaller changes

- **Browse tags counts everything in a page's folders**, not only the files and series in view. A Manga library of plain folders now shows their tags.
- **An empty tab** has its hint and Add Folder button back, and an empty Home has one to match.
- **A library folder holding a single file** shows that file, not a lone tile for the folder.
- **Empty and loading thumbnails** take the theme's colour instead of bright white.
- **Home** follows library folders added or removed while it is shown.
- **Purge** updates the board (or search) it was started from.
- **The private profile's mark** sits beside the menu button.
- **Quieter log:** a release-hook error after closing a video, and two QML warnings.

### Notes

- **The library database is upgraded** (series tags record where they came from). Older versions of Tetia cannot open it afterwards.
- **gallery-dl and yt-dlp are optional** and run as separate programs. Without them there is no download button.

### Install

- **Any distribution:** `git clone --branch v0.5.0 https://github.com/VainJiraiya/Tetia.git && cd Tetia && ./install.sh` (remove with `./uninstall.sh`).
- **Fedora / Nobara:** download the `.rpm` below for your Fedora version and run `sudo dnf install ./tetia-*.rpm` (remove with `sudo dnf remove tetia`).
- **Nix:** `nix run github:VainJiraiya/Tetia/v0.5.0`.
