## Tetia 0.4.0

A rework of how Tetia shows your library: a Home tab, boards, pages that show pictures in their own shape, and a booru-like search. Nothing on Tetia's pages is picked for you.

### Home

- **Tetia opens on Home**, which takes the Favorites tab's place. It shows:
  - **Continue:** manga and books you are partway through, and long videos (a show as one card, also with season folders). A card carries on where you stopped.
  - **Library:** one card per tab, with a collage and a count ("168 images").
  - **Pinned:** your boards.
  - **Favorites:** favorite folders, series and books as covers, then favorite pictures and videos.
  - **Recently added:** the newest files.
- **On a wide window Home has two columns**: covers and cards on the left, a wall of pictures on the right.
- **Home has a right-click menu**, and the star on a picture favorites it.

### Pages

- **A tab shows what is in its library folders**, not one tile per folder. Folders, series and virtual folders are portrait covers. Each folder's loose files follow under their own title ("Loose in Anime art · 1,204"). With several library folders, chips at the top show one alone.
- **Library folders are added and removed in Library Folders…** (main menu). Removing one never touches a file.
- **Pictures and videos keep their own shape** in rows that fill the width, or in columns (masonry) or a grid of squares. Each folder, virtual folder and tab remembers its own layout. A page of mostly tall pictures opens in columns.
- **Big folders scroll smoothly:** only the rows near the window are made.
- **A tile tells you what you need:**
  - A series shows how many chapters or episodes are left, with a bar while partway, and dims when finished.
  - A folder says what it holds ("2 folders · 127 items").
  - A video shows its length, and a check once watched.
- **Video tiles show the picture without the film strip** of the thumbnailer (Tetia's or Dolphin's). The shared thumbnail cache stays standard.
- **The Photos tab is now Images**: it holds art, screenshots and cosplay as much as photos.

### Boards

- **A board is a saved tag search shown as a collection**, plus files you put on it by hand. A file tagged later joins it by itself, and a file can be on any number of boards. Nothing on disk moves.
- **Make one** with New Board…, Save as Board… on a search or tag page, or Add to board… in a file's menu.
- **Pin a board to Home.** A board's cover is a collage, and the mildest-rated pictures are picked first.

### Search and tags

- **A typed search opens with a tag sidebar**: the tags of the results and how many have each. Clicking a tag narrows the search; its "−" leaves those items out.
- **Chips split the results by kind** (Images, Videos, Manga, EBooks).
- **A tag's page shows the tag** in its category's colour, with what else it is called and what it implies. It can look in one library folder, the whole tab, or everywhere, so a character's art, videos and manga come up on one page.

### Manga and books

- **A series can be given a format** (manga, manhwa, manhua, webtoon, doujin, oneshot, artbook) with Format… in its menu. The format sets how the reader opens it: a webtoon as a long strip, manga right to left. What you set in the reader still wins.
- **Manga and EBooks start with Continue reading**, and the sort menu filters by format.

### Menus and smaller changes

- **Right-click menus are in one order**, from what a click does to what cannot be undone.
- **New file actions:** Show in file manager, Copy path and Rename…. A renamed file keeps its tags, favorite and progress.
- **The image viewer has a black ground**, like the reader. A sun button switches it to a light ground for dark pictures.
- **The player's title** reads "Show — S01E03 · Title".
- **About Tetia and Quit** are in the main menu.
- **Single-colour icons** for the Videos tab and the Cover menu.

### Fixes

- A typed search lost its search when its page came back on top, so it could not be refreshed or saved.
- Clicking a tag in the image viewer stacked a new page for every tag.
- Videos reached through a link or a path with ".." were never measured.
- Removing a library folder now also takes its files off boards and Home. They come back if the folder is added again.

### Behind the scenes

- The library database is upgraded (series formats, boards, pins). **Older versions of Tetia cannot open it afterwards.**

### Install

- **Any distribution:** `git clone --branch v0.4.0 https://github.com/VainJiraiya/Tetia.git && cd Tetia && ./install.sh` (remove with `./uninstall.sh`).
- **Fedora / Nobara:** download the `.rpm` below for your Fedora version and run `sudo dnf install ./tetia-*.rpm` (remove with `sudo dnf remove tetia`).
- **Nix:** `nix run github:VainJiraiya/Tetia/v0.4.0`.
