# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""One-time migration of the data folder from the old name (GalleryApp) to Tetia's.

If the new data folder does not exist yet and the old one does, the old one is
COPIED (never moved: it stays untouched as a backup) and every absolute path
that pointed into the old folder is rewritten to point into the new one.

What stores such paths: only `collection.cover_path` in each gallery.db (the
covers live inside the data folder). That covers General's database AND the
database of every local private profile, which sits under profiles/<id>/. The
profile registry holds ids and vault device paths, never paths into this
folder, and thumbnails are plain files that are referenced by source URI, so
neither needs rewriting. Vault profiles keep their data in the vault.

The copy is built in a temporary folder next to the destination and renamed into
place at the end, so an interrupted run never leaves a half-migrated folder.
Pure Python (sqlite3 + shutil), no Qt.
"""
import logging
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from tetia import paths

logger = logging.getLogger(__name__)

_DB_SIDE_FILES = ("-wal", "-shm")


class MigrationError(Exception):
    """The copy could not be completed; the old folder is untouched."""


def needs_migration(old: Path = None, new: Path = None) -> bool:
    old = old or paths.legacy_data_dir()
    new = new or paths.data_dir()
    return old.is_dir() and not new.exists()


def _copy_tree(old: Path, tmp: Path):
    """Copy everything, including each database's -wal/-shm (so changes that
    were not yet checkpointed are not lost). Symlinks are copied as links."""
    for root, dirs, files in os.walk(old):
        target_dir = tmp / Path(root).relative_to(old)
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copy2(Path(root) / name, target_dir / name, follow_symlinks=False)


def _rewrite_paths(tmp: Path, old_prefix: str, new_prefix: str) -> int:
    """Re-point cover paths in every database of the copy. Returns rows changed."""
    changed = 0
    for db_file in sorted(tmp.rglob("*.db")):
        conn = sqlite3.connect(str(db_file))
        try:
            try:
                cursor = conn.execute(
                    "UPDATE collection SET cover_path = ? || substr(cover_path, ?) "
                    "WHERE cover_path IS NOT NULL AND substr(cover_path, 1, ?) = ?",
                    (new_prefix, len(old_prefix) + 1, len(old_prefix), old_prefix))
                changed += max(cursor.rowcount, 0)
                conn.commit()
            except sqlite3.OperationalError as e:
                if "no such table" not in str(e):      # a database from before covers existed
                    raise
            # Fold the copied WAL into the main file so the copy is self-contained
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        for suffix in _DB_SIDE_FILES:
            side = Path(str(db_file) + suffix)
            if side.exists() and side.stat().st_size == 0:
                side.unlink()
    return changed


def migrate_legacy_data(old: Path = None, new: Path = None) -> bool:
    """Copy the old data folder to the new one if that is needed and possible.
    Returns True if a migration was done, False if there was nothing to do.
    Raises MigrationError if the copy failed (the old folder is never modified)."""
    old = Path(old) if old else paths.legacy_data_dir()
    new = Path(new) if new else paths.data_dir()
    if not needs_migration(old, new):
        return False

    new.parent.mkdir(parents=True, exist_ok=True)
    tmp = new.parent / f".{new.name}.migrating-{uuid.uuid4().hex[:8]}"
    try:
        _copy_tree(old, tmp)
        # The prefix includes the trailing slash so "GalleryApp2/..." is not matched
        changed = _rewrite_paths(tmp, str(old) + "/", str(new) + "/")
        os.rename(tmp, new)
    except (OSError, sqlite3.Error, shutil.Error) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise MigrationError(f"Could not copy {old} to {new}: {e}") from e
    logger.info("Copied %s to %s (%d cover paths rewritten); the old folder was left in place",
                old, new, changed)
    return True
