# Profile registry, paths and isolation. HOME is a throwaway (see conftest.py).
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

from tetia.models import profiles as p

SRC = str(Path(__file__).resolve().parent.parent / "src")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        reg = p._registry_path()
        if reg.exists():
            reg.unlink()
        p.activate(None)

    def test_general_is_default_and_listed_first(self):
        self.assertEqual([x["id"] for x in p.all_profiles()], ["general"])
        self.assertEqual(p.active_id(), "general")
        self.assertFalse(p.is_private())

    def test_create_rename_delete(self):
        prof, err = p.create("  Vacation   pics ")
        self.assertEqual(err, "")
        self.assertEqual(prof["name"], "Vacation pics")
        self.assertTrue((p.base_dir() / "profiles" / prof["id"]).is_dir())
        self.assertEqual(p.rename(prof["id"], "Trips"), "")
        self.assertEqual(p.get(prof["id"])["name"], "Trips")
        (p.base_dir() / "profiles" / prof["id"] / "gallery.db").write_text("x")
        self.assertEqual(p.delete(prof["id"]), "")
        self.assertFalse((p.base_dir() / "profiles" / prof["id"]).exists())
        self.assertIsNone(p.get(prof["id"]))

    def test_name_rules(self):
        self.assertTrue(p.name_error(""))
        self.assertTrue(p.name_error("   "))
        self.assertTrue(p.name_error("x" * 41))
        self.assertTrue(p.name_error("general"))          # reserved, case-insensitive
        p.create("Work")
        self.assertTrue(p.name_error("WORK"))
        self.assertEqual(p.name_error("Work2"), "")
        wid = [x for x in p.private_profiles() if x["name"] == "Work"][0]["id"]
        self.assertEqual(p.name_error("work", ignore_id=wid), "")   # renaming to itself/case is fine

    def test_general_cannot_be_renamed_or_deleted(self):
        self.assertTrue(p.rename("general", "x"))
        self.assertTrue(p.delete("general"))

    def test_active_profile_cannot_be_deleted(self):
        prof, _ = p.create("Active one")
        p.activate(prof["id"])
        self.assertTrue(p.delete(prof["id"]))
        p.activate(None)
        self.assertEqual(p.delete(prof["id"]), "")

    def test_corrupt_registry_is_ignored(self):
        p._registry_path().write_text("{not json")
        self.assertEqual(p.private_profiles(), [])
        p._registry_path().write_text(json.dumps({"profiles": [
            {"id": "../../etc", "name": "evil"}, {"id": "abc", "name": "short"},
            {"id": "0123456789ab", "name": "ok"}]}))
        self.assertEqual([x["name"] for x in p.private_profiles()], ["ok"])

    def test_unknown_profile_activates_general(self):
        self.assertEqual(p.activate("0123456789ab"), "general")
        self.assertEqual(p.activate("../../etc"), "general")
        self.assertEqual(p.activate(""), "general")

    def test_paths(self):
        self.assertEqual(p.profile_dir(), p.base_dir())
        self.assertEqual(p.thumbnail_base(), Path.home() / ".cache" / "thumbnails")
        prof, _ = p.create("Hidden")
        p.activate(prof["id"])
        base = p.base_dir() / "profiles" / prof["id"]
        self.assertEqual(p.profile_dir(), base)
        self.assertEqual(p.thumbnail_base(), base / "thumbnails")
        self.assertNotIn(".cache", str(p.thumbnail_base()))

    def test_relaunch_and_argument(self):
        self.assertEqual(p.relaunch_command("general")[1:], ["-m", "tetia"])
        self.assertEqual(p.relaunch_command("0123456789ab")[1:],
                         ["-m", "tetia", "--profile", "0123456789ab"])
        argv = ["main.py", "--profile", "abc", "--other"]
        self.assertEqual(p.pop_profile_argument(argv), "abc")
        self.assertEqual(argv, ["main.py", "--other"])
        argv = ["main.py", "--profile"]
        self.assertIsNone(p.pop_profile_argument(argv))
        self.assertEqual(argv, ["main.py"])
        self.assertIsNone(p.pop_profile_argument(["main.py"]))


class IsolationTests(unittest.TestCase):
    """The database really lands in the profile's folder, and a plain launch is General."""

    def run_py(self, code, home):
        env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
        env.update(HOME=home, PYTHONPATH=SRC)
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env=env, cwd=SRC)

    def test_private_database_is_separate(self):
        home = tempfile.mkdtemp(prefix="home")
        code = '''
import sys
from tetia.models import profiles
prof, _ = profiles.create("Secret")
%s
from tetia.models.database import Database, app_data_dir
db = Database()
db.add_folder("file:///secret", "photos")
db.close()
print(app_data_dir())
'''
        # private
        first = self.run_py(code % 'profiles.activate(prof["id"])', home)
        self.assertEqual(first.returncode, 0, first.stderr)
        private_dir = Path(first.stdout.strip())
        self.assertIn("profiles", private_dir.parts)
        self.assertTrue((private_dir / "gallery.db").exists())
        general_db = Path(home) / ".local/share/tetia/gallery.db"
        self.assertFalse(general_db.exists(), "private launch must not create General's database")
        # general, same HOME: its own database, with none of the private folders
        second = self.run_py('''
from tetia.models import profiles
profiles.activate(None)
from tetia.models.database import Database
db = Database(); print(db.get_all_folders())
''', home)
        self.assertEqual(second.stdout.strip(), "[]", second.stderr)
        self.assertTrue(general_db.exists())

    def test_plain_launch_is_general(self):
        home = tempfile.mkdtemp(prefix="home")
        out = self.run_py('''
import sys
from tetia.models import profiles
profiles.create("Secret")
profiles.activate(profiles.pop_profile_argument(["main.py"]))
print(profiles.active_id())
''', home)
        self.assertEqual(out.stdout.strip(), "general", out.stderr)




class XdgTests(unittest.TestCase):
    def test_profile_data_follows_xdg_data_home(self):
        old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="xdg")
        try:
            self.assertEqual(p.base_dir(), Path(os.environ["XDG_DATA_HOME"]) / "tetia")
            prof, _ = p.create("Where am I")
            self.assertTrue((Path(os.environ["XDG_DATA_HOME"]) / "tetia" / "profiles" / prof["id"]).is_dir())
        finally:
            os.environ.pop("XDG_DATA_HOME", None)
            if old is not None:
                os.environ["XDG_DATA_HOME"] = old

    def test_general_thumbnails_follow_xdg_cache_home(self):
        os.environ["XDG_CACHE_HOME"] = tempfile.mkdtemp(prefix="xdgc")
        try:
            self.assertEqual(p.thumbnail_base(), Path(os.environ["XDG_CACHE_HOME"]) / "thumbnails")
        finally:
            os.environ.pop("XDG_CACHE_HOME", None)


if __name__ == "__main__":
    unittest.main()
