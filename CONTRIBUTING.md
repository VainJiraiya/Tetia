# Contributing to Tetia

Thanks for helping! Small, focused changes are easiest to review.

## Reporting bugs and asking for features

Use the issue templates. Please do **not** attach private pictures, and remove
personal file paths from logs before posting.

## Setting up

You need Python 3.10+, PySide6, and the KDE pieces listed in the README
(Kirigami, qqc2-desktop-style, Breeze icons). On NixOS `nix develop` provides them.

```sh
pip install -e .          # in a venv that can see your PySide6 (--system-site-packages)
tetia                     # or: python -m tetia
```

## Checks

CI installs the package, imports every model, and lints the QML:

```sh
pyside6-qmllint src/tetia/qml/main.qml src/tetia/qml/views/*.qml    # or qmllint
```

Tests live in `tests/` and run without a display and without touching your real data
(each test gets a throwaway `HOME`):

```sh
pip install -e '.[dev]'     # in a venv; on NixOS add --system-site-packages inside `nix develop`
python -m pytest
```

Please add or update a test when you change behaviour, and describe in your pull request
how you tried the change by hand (what you clicked, on which setup).

## Code

- Python models live in `src/tetia/models/`, QML in `src/tetia/qml/`; the QML module
  is called `Tetia`.
- Data paths come from `tetia/paths.py` and `tetia/models/profiles.py`; never
  hard-code `~/.local/share` or `~/.cache`.
- Anything that keeps files open inside a profile folder (a thread, a folder watcher,
  a database connection) must register a release hook with
  `profiles.add_release_hook`, or an encrypted private profile cannot be locked.
- Plasma Vault support must stay optional: nothing may import or call it at startup.

## Pull requests

- One change per pull request; describe what and why, and how you tested it.
- New source files start with the SPDX header used elsewhere
  (`SPDX-License-Identifier: GPL-3.0-or-later`).
- By contributing you agree that your work is licensed under GPL-3.0-or-later.
- If an AI tool wrote a substantial part, please say so in the description.
