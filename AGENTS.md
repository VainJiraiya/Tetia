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
  file_picker.py       QmlElement wrapper around QFileDialog for folder selection
  database.py          thin sqlite3 wrapper — migration system (PRAGMA user_version)
                        tables: folders, item_metadata (legacy), media (Phase 1)
                        media columns: id, path, name, kind, size, mtime, content_hash,
                                      favorite, rating, missing
src/qml/
  main.qml             app window, header, page stack, model instances, navigation
  views/
    FolderGridView.qml     folder collection grid (cards with hero images)
    MediaGridView.qml      media item grid (thumbnails + filenames + favorite ribbon)
    ImageViewer.qml        fullscreen image viewer (pinch-zoom, arrow keys, favorite + rating)
mediaModel.py          legacy copy at repo root — DO NOT use; src/models/mediaModel.py is the active one
guide.md               reference docs (not agent-facing)
TAGGING_SPEC.md        phased spec for tagging, favorites, rating, and search system
```

## Key details

- **QML import:** All Python models declare `QML_IMPORT_NAME = "Gallery"`, `QML_IMPORT_MAJOR_VERSION = 1`. In QML: `import Gallery 1.0`.
- **Thumbnail cache:** `thumbModel.py` writes to the freedesktop `~/.cache/thumbnails` cache. URI hashing uses RFC 2396-style encoding (`urllib.parse.quote` with safe `"/-_.!~*'()"`) — not Qt's `FullyEncoded` — to match glib's `g_filename_to_uri` behavior. Files with characters like `(` or `)` will hash differently under Qt's encoder.
- **Video thumbnails:** Require `ffmpegthumbnailer` on `PATH`. Not yet in `flake.nix` — add `pkgs.ffmpegthumbnailer` to the flake packages if video thumb generation is needed.
- **Kirigami version:** `import org.kde.kirigami 2.20 as Kirigami` in QML files.
- **Database:** SQLite at `~/.local/share/GalleryApp/gallery.db`. Auto-created on first run. Migration system via `PRAGMA user_version` (Phase 1: `media` table).
- **Media persistence:** Each scanned file is upserted into `media` by `path`. `content_hash` (SHA-1: size + first 1MB + last 1MB) enables move/rename reconciliation. Missing files get `missing=1` instead of row deletion.
- **Favorites & Rating:** `favorite` (boolean) and `rating` (0-3 or NULL) stored per `media_id`. UI toggles in MediaGridView (favorite ribbon) and ImageViewer (star selector). Operations emit `dataChanged` for single-row updates.
- **No tests, no linter, no pyproject.toml.** The flake is the only tooling.
- **`QAbstractListModel`** uses `beginResetModel()`/`endResetModel()` for bulk updates, not row-by-row insert/remove.
- **Page stack cleanup:** When popping pages or switching tabs, always call `poppedPage.destroy()` after `pageStack.pop()` to prevent orphaned QML components (a known issue when the window is at minimum size and transition animations don't fire).
