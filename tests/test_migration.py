"""The one-time copy of the old GalleryApp data folder to Tetia's XDG folder."""
import os
import sqlite3
from pathlib import Path

import pytest

from tetia import migration, paths
from tetia.models.database import Database

PROFILE_ID = "0123456789ab"


def make_legacy_folder(home: Path):
    """A realistic old data folder: General's database with covers set, a local
    private profile with its own database and covers, thumbnails, the registry."""
    old = home / ".local" / "share" / "GalleryApp"
    (old / "covers").mkdir(parents=True)
    (old / "profiles" / PROFILE_ID / "covers").mkdir(parents=True)
    (old / "profiles" / PROFILE_ID / "thumbnails" / "large").mkdir(parents=True)

    outside = home / "Pictures" / "my-own-cover.png"          # a path that is NOT in the data folder
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"png")

    for folder, covers in ((old, ["a.jpg", "b.jpg"]), (old / "profiles" / PROFILE_ID, ["p.jpg"])):
        for name in covers:
            (folder / "covers" / name).write_bytes(b"cover:" + name.encode())
    (old / "profiles" / PROFILE_ID / "thumbnails" / "large" / "t.png").write_bytes(b"thumb")

    db = Database(old / "gallery.db")
    db.set_collection_cover("/lib/one", str(old / "covers" / "a.jpg"))
    db.set_collection_cover("/lib/two", str(old / "covers" / "b.jpg"))
    db.set_collection_cover("/lib/three", str(outside))
    db.set_collection_cover("/lib/four", str(home / ".local/share/GalleryApp2/covers/x.jpg"))   # lookalike prefix
    db.set_collection_favorite("/lib/fav", True)                                                # no cover at all
    db.conn.execute("INSERT INTO folders (path, category) VALUES ('file:///lib/one', 'photos')")
    db.conn.commit()

    pdb = Database(old / "profiles" / PROFILE_ID / "gallery.db")
    pdb.set_collection_cover("/priv/one", str(old / "profiles" / PROFILE_ID / "covers" / "p.jpg"))
    pdb.conn.commit()

    (old / "profiles.json").write_text(
        '{"profiles": [{"id": "%s", "name": "Local one", "kind": "local", "device": ""}]}' % PROFILE_ID)
    return old, db, pdb, outside


def covers_of(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        return dict(conn.execute("SELECT path, cover_path FROM collection").fetchall())
    finally:
        conn.close()


def test_paths_follow_xdg(monkeypatch, tmp_path):
    home = Path.home()
    assert paths.data_dir() == home / ".local" / "share" / "tetia"
    assert paths.thumbnails_dir() == home / ".cache" / "thumbnails"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert paths.data_dir() == tmp_path / "data" / "tetia"
    assert paths.thumbnails_dir() == tmp_path / "cache" / "thumbnails"
    assert paths.legacy_data_dir() == home / ".local" / "share" / "GalleryApp"   # never XDG-relative
    monkeypatch.setenv("XDG_DATA_HOME", "relative/path")                          # invalid per the spec
    assert paths.data_dir() == home / ".local" / "share" / "tetia"


def test_migration_copies_and_rewrites_cover_paths(isolated_environment):
    home = isolated_environment
    old, db, pdb, outside = make_legacy_folder(home)
    new = paths.data_dir()
    # leave the databases open with uncheckpointed changes in their WAL, as a crashed app would
    db.set_collection_cover("/lib/late", str(old / "covers" / "a.jpg"))
    db.conn.commit()
    assert Path(str(old / "gallery.db") + "-wal").exists()

    before = {p.relative_to(old): p.read_bytes() for p in old.rglob("*") if p.is_file()}

    assert migration.needs_migration()
    assert migration.migrate_legacy_data() is True

    # the new folder is complete and nothing temporary is left behind
    assert new.is_dir()
    assert not [p for p in new.parent.iterdir() if "migrating" in p.name]
    assert (new / "covers" / "a.jpg").read_bytes() == b"cover:a.jpg"
    assert (new / "profiles" / PROFILE_ID / "thumbnails" / "large" / "t.png").read_bytes() == b"thumb"
    assert (new / "profiles.json").read_text() == (old / "profiles.json").read_text()

    # General's database: covers inside the data folder now point into the new one
    covers = covers_of(new / "gallery.db")
    assert covers["/lib/one"] == str(new / "covers" / "a.jpg")
    assert covers["/lib/two"] == str(new / "covers" / "b.jpg")
    assert covers["/lib/late"] == str(new / "covers" / "a.jpg"), "the un-checkpointed WAL row must survive"
    assert covers["/lib/fav"] is None
    for path in (covers["/lib/one"], covers["/lib/two"]):
        assert Path(path).is_file(), "every rewritten cover must exist at its new path"
    # paths that were never inside the old folder are left alone
    assert covers["/lib/three"] == str(outside)
    assert covers["/lib/four"] == str(home / ".local/share/GalleryApp2/covers/x.jpg")

    # a local private profile's own database too
    pcovers = covers_of(new / "profiles" / PROFILE_ID / "gallery.db")
    assert pcovers["/priv/one"] == str(new / "profiles" / PROFILE_ID / "covers" / "p.jpg")
    assert Path(pcovers["/priv/one"]).is_file()

    # other data came across
    conn = sqlite3.connect(str(new / "gallery.db"))
    assert conn.execute("SELECT path FROM folders").fetchall() == [("file:///lib/one",)]
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()

    # the old folder is exactly as it was (apart from SQLite housekeeping on its own DB files)
    for rel, content in before.items():
        if rel.suffix == ".db" or str(rel).endswith(("-wal", "-shm")):
            continue
        assert (old / rel).read_bytes() == content
    assert covers_of(old / "gallery.db")["/lib/one"] == str(old / "covers" / "a.jpg"), \
        "the old database must keep its old paths"


def test_migration_runs_once_and_only_when_needed(isolated_environment):
    home = isolated_environment
    assert migration.migrate_legacy_data() is False                    # no old folder: nothing to do
    old, *_ = make_legacy_folder(home)
    assert migration.migrate_legacy_data() is True
    (paths.data_dir() / "marker.txt").write_text("user changes after migrating")
    assert migration.migrate_legacy_data() is False                    # the new folder exists now
    assert (paths.data_dir() / "marker.txt").exists()


def test_existing_new_folder_is_never_touched(isolated_environment):
    home = isolated_environment
    old, *_ = make_legacy_folder(home)
    paths.data_dir().mkdir(parents=True)
    (paths.data_dir() / "mine.txt").write_text("keep")
    assert migration.migrate_legacy_data() is False
    assert sorted(p.name for p in paths.data_dir().iterdir()) == ["mine.txt"]


def test_migration_into_an_xdg_data_home(isolated_environment, monkeypatch, tmp_path):
    home = isolated_environment
    old, *_ = make_legacy_folder(home)
    xdg = tmp_path / "flatpak-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    assert migration.migrate_legacy_data() is True
    new = xdg / "tetia"
    assert new.is_dir()
    assert covers_of(new / "gallery.db")["/lib/one"] == str(new / "covers" / "a.jpg")
    assert not (home / ".local" / "share" / "tetia").exists()


def test_failed_migration_leaves_no_partial_folder(isolated_environment, monkeypatch):
    home = isolated_environment
    old, *_ = make_legacy_folder(home)
    import shutil
    calls = []
    real = shutil.copy2

    def flaky(src, dst, **kw):
        calls.append(src)
        if len(calls) == 3:
            raise OSError("disk full")
        return real(src, dst, **kw)

    monkeypatch.setattr(migration.shutil, "copy2", flaky)
    with pytest.raises(migration.MigrationError):
        migration.migrate_legacy_data()
    assert not paths.data_dir().exists()
    assert not [p for p in paths.data_dir().parent.iterdir() if "migrating" in p.name]
    assert covers_of(old / "gallery.db")["/lib/one"] == str(old / "covers" / "a.jpg")
    monkeypatch.setattr(migration.shutil, "copy2", real)               # and it works on the next try
    assert migration.migrate_legacy_data() is True


def test_old_database_without_a_collection_table(isolated_environment):
    """A database from before covers existed has no `collection` table."""
    home = isolated_environment
    old = home / ".local" / "share" / "GalleryApp"
    old.mkdir(parents=True)
    conn = sqlite3.connect(str(old / "gallery.db"))
    conn.execute("CREATE TABLE folders (path TEXT, category TEXT)")
    conn.execute("INSERT INTO folders VALUES ('file:///x', 'photos')")
    conn.commit()
    conn.close()
    assert migration.migrate_legacy_data() is True
    conn = sqlite3.connect(str(paths.data_dir() / "gallery.db"))
    assert conn.execute("SELECT * FROM folders").fetchall() == [("file:///x", "photos")]
    conn.close()
