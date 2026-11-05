# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The virtual folder actions, for QML. The rules live in virtualfolders.py; this only translates between
what the grid holds (media ids, and tile keys: "virtual:<id>" for a virtual folder, a file:// address for a
real folder) and those functions, and turns a refusal into a sentence."""
import logging
import sqlite3

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtQml import QmlElement

from tetia.models import covers, virtualfolders
from tetia.models.database import get_database

QML_IMPORT_NAME = "Tetia"
QML_IMPORT_MAJOR_VERSION = 1

logger = logging.getLogger(__name__)

PREFIX = "virtual:"


def split_tiles(tile_keys) -> tuple:
    """(real folder keys, virtual folder ids) of the selected tiles."""
    folders, virtual = [], []
    for key in tile_keys or []:
        key = str(key)
        if key.startswith(PREFIX):
            try:
                virtual.append(int(key[len(PREFIX):]))
            except ValueError:
                continue
        elif key:
            folders.append(covers.folder_key(key))
    return folders, virtual


@QmlElement
class VirtualFolderService(QObject):
    changed = Signal()      # something moved: grids showing the library should be reloaded

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = get_database()

    # ---- asking ----------------------------------------------------------------------------------------

    @Slot(list, list, result="QVariant")
    def options(self, media_ids, tile_keys):
        """What can be done with a selection: {home, targets, canCreate}. `home` is the real folder a new
        virtual folder would be made in ('' if the selection spans several library folders), and `targets`
        the existing virtual folders it can go to, as [{id, name, depth}]."""
        folders, virtual = split_tiles(tile_keys)
        ids = [int(i) for i in media_ids or []]
        try:
            home = virtualfolders.common_home(self._db, ids, folders)
            targets = virtualfolders.targets(self._db, ids, folders, exclude_vfolders=virtual)
        except sqlite3.Error as e:
            logger.error("Failed to look up virtual folders: %s", e)
            return {"home": "", "targets": [], "canCreate": False}
        return {"home": home, "targets": targets, "canCreate": bool(home)}

    @Slot(int, result="QVariant")
    def info(self, vfolder_id):
        """{name, home, parentId, crumbs: [names]} of a virtual folder, or {} if it is gone."""
        vf = virtualfolders.get(self._db, vfolder_id)
        if vf is None:
            return {}
        return {"name": vf["name"], "home": vf["home"], "parentId": -1 if vf["parent_id"] is None else vf["parent_id"],
                "crumbs": [name for _, name in virtualfolders.crumbs(self._db, vfolder_id)]}

    # ---- changing ----------------------------------------------------------------------------------------

    def _place(self, vid, media_ids, tile_keys) -> dict:
        folders, virtual = split_tiles(tile_keys)
        moved = skipped = 0
        for count, miss in (virtualfolders.place_media(self._db, vid, [int(i) for i in media_ids or []]),
                            virtualfolders.place_folders(self._db, vid, folders),
                            virtualfolders.place_vfolders(self._db, vid, virtual)):
            moved += count
            skipped += miss
        self.changed.emit()
        return {"moved": moved, "skipped": skipped}

    @Slot(int, list, list, result="QVariant")
    def place(self, vfolder_id, media_ids, tile_keys):
        """Put the selection in a virtual folder. {moved, skipped} or {error}."""
        try:
            return self._place(vfolder_id, media_ids, tile_keys)
        except (virtualfolders.VirtualFolderError, sqlite3.Error) as e:
            return {"error": str(e)}

    @Slot(str, int, str, list, list, result="QVariant")
    def placeInNew(self, name, parent_id, home, media_ids, tile_keys):
        """Make a virtual folder (in `parent_id`, or at the top of `home`) and put the selection in it."""
        try:
            vid = virtualfolders.create(self._db, name, covers.folder_key(home), parent_id if parent_id >= 0 else None)
            result = self._place(vid, media_ids, tile_keys)
            result["id"] = vid
            return result
        except (virtualfolders.VirtualFolderError, sqlite3.Error) as e:
            return {"error": str(e)}

    @Slot(str, str, int, result="QVariant")
    def create(self, name, home, parent_id):
        """An empty virtual folder. {id} or {error}."""
        try:
            vid = virtualfolders.create(self._db, name, covers.folder_key(home), parent_id if parent_id >= 0 else None)
        except (virtualfolders.VirtualFolderError, sqlite3.Error) as e:
            return {"error": str(e)}
        self.changed.emit()
        return {"id": vid}

    @Slot(list, list, result=int)
    def remove(self, media_ids, tile_keys):
        """Take the selection out of the virtual folder it is in (one level up, or back to its real folder)."""
        folders, virtual = split_tiles(tile_keys)
        try:
            count = (virtualfolders.unplace_media(self._db, [int(i) for i in media_ids or []])
                     + virtualfolders.unplace_folders(self._db, folders)
                     + virtualfolders.unplace_vfolders(self._db, virtual))
        except sqlite3.Error as e:
            logger.error("Failed to take items out of a virtual folder: %s", e)
            return 0
        self.changed.emit()
        return count

    @Slot(int, str, result="QVariant")
    def rename(self, vfolder_id, name):
        try:
            virtualfolders.rename(self._db, vfolder_id, name)
        except (virtualfolders.VirtualFolderError, sqlite3.Error) as e:
            return {"error": str(e)}
        self.changed.emit()
        return {}

    @Slot(int)
    def deleteFolder(self, vfolder_id):
        """Delete a virtual folder; what was in it goes back where it was (no file is touched)."""
        try:
            virtualfolders.delete(self._db, vfolder_id)
        except sqlite3.Error as e:
            logger.error("Failed to delete a virtual folder: %s", e)
            return
        self.changed.emit()

    @Slot(int)
    def clearCover(self, vfolder_id):
        try:
            self._db._write(lambda: self._db.conn.execute(
                "UPDATE virtual_folder SET cover_media_id = NULL WHERE id = ?", (int(vfolder_id),)))
        except sqlite3.Error as e:
            logger.error("Failed to clear a virtual folder cover: %s", e)
            return
        self.changed.emit()
