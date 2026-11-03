"""Runs the script-style tests in tests/scripts/ one by one, each in its own
process with a throwaway HOME. They check scanning, tagging, locking and search
end to end against a real SQLite database and exit non-zero on any failure."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
SCRIPTS = sorted((HERE / "scripts").glob("*.py"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_script(script, tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", TETIA_SRC=str(SRC),
               HOME=str(tmp_path), PYTHONPATH=str(SRC))
    for name in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        env.pop(name, None)
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                            env=env, cwd=tmp_path, timeout=300)
    failures = [line for line in result.stdout.splitlines() if line.startswith("FAIL")]
    assert result.returncode == 0 and not failures, (
        f"{script.name} failed\n" + "\n".join(failures) + "\n" + result.stdout[-2000:] + result.stderr[-2000:])
