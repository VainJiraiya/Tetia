# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The background indexer and the media grid scan the same folder at the same time
(right after a folder is added, or when the app starts and a folder is opened at once).
Both write to the database, so a scan must wait for the other one's write lock and
never fail with "database is locked"."""
import threading

from tetia.models import covers
from tetia.models.database import Database
from tetia.models.scanner import scan_folder


def _hash(path):
    return "h" + path[-12:]


def test_two_scans_of_the_same_new_files_do_not_lock_each_other_out(tmp_path):
    folder = tmp_path / "pics"
    folder.mkdir()
    for i in range(30):
        (folder / f"img{i:02d}.png").write_bytes(b"x" * (i + 1))

    Database().close()      # create the schema once, so only the scans race

    errors = []
    for attempt in range(15):
        # fresh unscanned files each round
        for i in range(30):
            (folder / f"img{i:02d}.png").write_bytes(b"x" * (i + 1 + attempt * 31))
        barrier = threading.Barrier(2, timeout=30)    # a thread that fails early must not hang the other

        def scan():
            db = None
            try:
                db = Database()      # a connection of its own, like the indexer thread
                barrier.wait()
                scan_folder(db, folder, _hash)
            except Exception as e:   # noqa: BLE001 - the test reports anything
                errors.append(repr(e))
            finally:
                if db is not None:
                    db.close()

        threads = [threading.Thread(target=scan) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not any(t.is_alive() for t in threads)
    assert errors == []
