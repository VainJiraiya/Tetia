"""QML face of models/profiles.py: lists, creates, renames, deletes and
switches profiles. Switching relaunches the app into the chosen profile."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QProcess, Property, Signal, Slot
from PySide6.QtQml import QmlElement

from models import profiles

QML_IMPORT_NAME = "Gallery"
QML_IMPORT_MAJOR_VERSION = 1


@QmlElement
class ProfileModel(QObject):
    profilesChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

    @Property(list, notify=profilesChanged)
    def profiles(self):
        """[{id, name, isPrivate, active}], General first."""
        active = profiles.active_id()
        return [{"id": p["id"], "name": p["name"], "isPrivate": p["private"],
                 "active": p["id"] == active} for p in profiles.all_profiles()]

    @Property(bool, constant=True)
    def isPrivate(self):
        return profiles.is_private()

    @Property(str, constant=True)
    def activeName(self):
        return profiles.active_name()

    @Slot(str, str, result=str)
    def nameError(self, name: str, profile_id: str) -> str:
        """Why `name` can't be used ('' if it can). profile_id is the profile
        being renamed, or '' when creating one."""
        return profiles.name_error(name, profile_id or None)

    @Slot(str, result=str)
    def createProfile(self, name: str) -> str:
        """Create a private profile. Returns its id, or '' if it failed
        (use nameError first to show the reason)."""
        profile, _ = profiles.create(name)
        if profile is None:
            return ""
        self.profilesChanged.emit()
        return profile["id"]

    @Slot(str, str, result=str)
    def renameProfile(self, profile_id: str, name: str) -> str:
        error = profiles.rename(profile_id, name)
        if not error:
            self.profilesChanged.emit()
        return error

    @Slot(str, result=str)
    def deleteProfile(self, profile_id: str) -> str:
        error = profiles.delete(profile_id)
        if not error:
            self.profilesChanged.emit()
        return error

    @Slot(str)
    def switchTo(self, profile_id: str):
        """Start a new copy of the app in the profile, then quit this one."""
        if profiles.get(profile_id) is None or profile_id == profiles.active_id():
            return
        script = str(Path(sys.argv[0]).resolve())
        command = profiles.relaunch_command(profile_id, script)
        if QProcess.startDetached(command[0], command[1:], os.getcwd()):
            QCoreApplication.quit()
