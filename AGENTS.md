# Tetia — KDE Plasma 6 Media Gallery (PySide6 + Kirigami)

## Run

```
nix develop          # enter dev shell (or rely on direnv via .envrc)
python -m src        # launch the app
```

No venv, no pip. PySide6 and all KDE/Qt libraries come from the Nix flake (`flake.nix`).

## Architecture

```
flake.nix              dev shell + env vars (QML2_IMPORT_PATH, QT_PLUGIN_PATH, etc.)
src/main.py            entry point — creates QApplication, registers ThumbnailProvider, loads qml/main.qml
src/models/
  mediaModel.py        QAbstractListModel — scans folders, exposes media items to QML
                        roles: mediaId, fileUri, fileName, isVideo, isComic, isBook, isFavorite, rating
                        slots: setFavorite(media_id, bool), setRating(media_id, int)
                        persistent media identity via SQLite upsert + content_hash reconciliation
  folderModel.py       QAbstractListModel — persisted folder collection (SQLite)
  thumbModel.py        QQuickImageProvider — thumbnail cache at ~/.cache/thumbnails (freedesktop spec)
  subfolderModel.py    subfolders of the open folder (nested collections), filtered like the grid
  gridModel.py         stitches subfolders + media into the one list the media grid shows
  scanner.py           shared folder-scan/upsert logic (MediaModel and the indexer)
  searchModel.py       search: runs tag_query, suggestions, background library indexer
  tag_query.py         search grammar -> SQL (pure Python; tests in test_phase3_query.py)
  profiles.py          General + private profiles (vault or local): data/thumbnail paths, registry, release hooks (pure Python)
  vaults.py            Plasma Vault helpers with no Qt: mount lookup in /proc/self/mounts, decoding the service's structs
  vaultService.py      D-Bus client for the Plasma Vault KDED module (open/close/list/new, signals)
  profileModel.py      QML face of profiles.py; unlock -> lock -> relaunch state machine for switching and quitting
  file_picker.py       QmlElement wrapper around QFileDialog for folder selection
  database.py          thin sqlite3 wrapper — migration system (PRAGMA user_version)
                        tables: folders, item_metadata (legacy), media (Phase 1)
                        media columns: id, path, name, kind, size, mtime, content_hash,
                                      favorite, rating, missing
src/qml/
  main.qml             app window, header, page stack, model instances, navigation
  views/
    FolderGridView.qml     folder collection grid (cards with hero images)
    MediaGridView.qml      media item grid (thumbnails + filenames)
    ImageViewer.qml        fullscreen image viewer (pinch-zoom, arrow keys)
    SearchBar.qml          search strip under the header (field, suggestions, term chips)
    ProfilesDialog.qml     list/create/rename/delete/switch profiles (encrypted vault or local)
    VaultBusyDialog.qml    progress and recovery while a vault unlocks or locks
mediaModel.py          legacy copy at repo root — DO NOT use; src/models/mediaModel.py is the active one
guide.md               reference docs (not agent-facing)
TAGGING_SPEC.md        phased spec for tagging, favorites, rating, and search system
```

## Key details

- **QML import:** All Python models declare `QML_IMPORT_NAME = "Gallery"`, `QML_IMPORT_MAJOR_VERSION = 1`. In QML: `import Gallery 1.0`.
- **Thumbnail cache:** `thumbModel.py` writes to the freedesktop `~/.cache/thumbnails` cache. URI hashing uses RFC 2396-style encoding (`urllib.parse.quote` with safe `"/-_.!~*'()"`) — not Qt's `FullyEncoded` — to match glib's `g_filename_to_uri` behavior. Files with characters like `(` or `)` will hash differently under Qt's encoder.
- **Video thumbnails:** Require `ffmpegthumbnailer` on `PATH`. Not yet in `flake.nix` — add `pkgs.ffmpegthumbnailer` to the flake packages if video thumb generation is needed.
- **Kirigami version:** `import org.kde.kirigami 2.20 as Kirigami` in QML files.
- **Profiles:** the active profile is fixed per process (`main.py` calls `profiles.activate` before any model opens the DB; a plain launch is always General, only the switcher's relaunch passes `--profile <id>`). General = the paths below, unchanged. A private profile is either a **vault** profile (data in `<vault mount>/.tetia`, inside a KDE Plasma Vault; Tetia only remembers the vault's encrypted-folder path) or a **local** profile (`~/.local/share/GalleryApp/profiles/<id>/`, not encrypted, for people without Plasma Vault). Neither touches `~/.cache/thumbnails`. Always get data paths via `profiles.profile_dir()` / `database.app_data_dir()` / `profiles.thumbnail_base()`, never hardcode them. Tests: `test_phase4_profiles.py`, `test_phase5_vaults.py`.
- **Plasma Vault:** Tetia never encrypts or sees a password; `openVault` makes KDE show its own dialog. The service's struct has no usable mount point and says nothing when the dialog is cancelled, so "is it open, and where" is read from `/proc/self/mounts` (`vaults.mount_for`) and unlock is detected by polling. Switching to a vault profile unlocks first (cancel = stay put), then locks the profile being left, then relaunches; closing the window in a vault profile locks first. Before locking, `profiles.run_release_hooks()` must have stopped everything holding files in the profile folder: **any new thread, watcher or long-lived file/DB handle that touches profile data must register a hook with `profiles.add_release_hook`** (order < 100 to stop workers, 100 closes databases), or the vault will refuse to lock.
- **Database:** SQLite at `~/.local/share/GalleryApp/gallery.db` (General). Auto-created on first run. Migration system via `PRAGMA user_version` (Phase 1: `media` table).
- **Media persistence:** Each scanned file is upserted into `media` by `path`. `content_hash` (SHA-1: size + first 1MB + last 1MB) enables move/rename reconciliation. Missing files get `missing=1` instead of row deletion.
- **Favorites & Rating:** `favorite` (boolean) and `rating` (0-3 or NULL) stored per `media_id`. Operations emit `dataChanged` for single-row updates. UI integration pending.
- **No tests, no linter, no pyproject.toml.** The flake is the only tooling.
- **`QAbstractListModel`** uses `beginResetModel()`/`endResetModel()` for bulk updates, not row-by-row insert/remove.
- **Page stack cleanup:** When popping pages or switching tabs, always call `poppedPage.destroy()` after `pageStack.pop()` to prevent orphaned QML components (a known issue when the window is at minimum size and transition animations don't fire).


Never give a QML property the same name as an id in main.qml (e.g. property mediaModel vs id: mediaModel). It silently resolves to null and blanks views with no error.
