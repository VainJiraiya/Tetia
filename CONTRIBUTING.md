# Contributing to Tetia

Thanks for helping! Small, focused changes are easiest to review.

## Reporting bugs and asking for features

Use the issue templates. Please do **not** attach private pictures, and remove
personal file paths from logs before posting.

## Setting up

You need Python 3.10+, PySide6, and the KDE pieces listed in the README
(Kirigami, qqc2-desktop-style, Breeze icons). On NixOS `nix develop` provides them.

```sh
pip install -e ".[dev]"            # in a venv that can see your PySide6 (--system-site-packages)
tetia                              # or: python -m tetia
```

## Checks

```sh
QT_QPA_PLATFORM=offscreen python -m pytest
pyside6-qmllint src/tetia/qml/main.qml src/tetia/qml/views/*.qml    # or qmllint
```

CI runs both. The tests give every test a throwaway `HOME` and unset `XDG_DATA_HOME`
/ `XDG_CACHE_HOME`, so they never touch your real library. If you write a test that
starts the app or opens a database, keep it that way.

## Code

- `AGENTS.md` describes the layout and the conventions worth knowing (it is written
  for AI coding tools but reads fine for people).
- Python models live in `src/tetia/models/`, QML in `src/tetia/qml/`. Data paths come
  from `tetia/paths.py` and `profiles.py`; never hard-code `~/.local/share`.
- Anything that holds files open inside a profile folder (a thread, a watcher, a
  database connection) must register a release hook, or an encrypted private profile
  cannot be locked. See `AGENTS.md`.
- Plasma Vault support must stay optional: nothing may import or call it at startup.

## Pull requests

- One change per pull request; describe what and why, and how you tested it.
- Add or update tests for behaviour you change.
- New source files start with the SPDX header used elsewhere
  (`SPDX-License-Identifier: GPL-3.0-or-later`).
- By contributing you agree that your work is licensed under GPL-3.0-or-later.
- If an AI tool wrote a substantial part, please say so in the description.
