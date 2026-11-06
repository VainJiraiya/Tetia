#!/usr/bin/env bash
# Installs Tetia for the current user (no root needed) from this checkout:
#
#   git clone --branch v0.3.0 https://github.com/VainJiraiya/Tetia.git
#   cd Tetia && ./install.sh
#
# It puts an isolated Python environment in ~/.local/lib/tetia, a `tetia` command in ~/.local/bin, and the menu
# entry and icon in ~/.local/share. ./uninstall.sh removes all of it again. Run ./install.sh once more to upgrade.
#
# Tetia needs the interface libraries of your distribution (Kirigami and friends); pip cannot provide those.
# The script checks for them and says what to install if something is missing.
#
#   ./install.sh --prefix /some/where     # somewhere other than ~/.local
set -euo pipefail

prefix="${HOME}/.local"
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) prefix="${2:?--prefix needs a folder}"; shift 2 ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
done

here=$(cd "$(dirname "$0")" && pwd)
app_dir="$prefix/lib/tetia"
app_id="io.github.VainJiraiya.Tetia"
say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[ -f "$here/pyproject.toml" ] || die "run this from a checkout of Tetia (pyproject.toml not found next to install.sh)"
[ "$(id -u)" -ne 0 ] || die "run this as your normal user, not as root: it installs into your home folder"

# ---- Python -----------------------------------------------------------------------------------------------------
python=$(command -v python3 || true)
[ -n "$python" ] || die "python3 is not installed"
"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10 or newer is needed (found $("$python" --version))"

hint() {
    # install commands for the libraries that pip cannot provide
    local id="" like=""
    [ -r /etc/os-release ] && { id=$(. /etc/os-release; echo "${ID:-}"); like=$(. /etc/os-release; echo "${ID_LIKE:-}"); }
    case " $id $like " in
        *" fedora "*|*" nobara "*)
            say "  sudo dnf install python3-pyside6 kf6-kirigami kf6-qqc2-desktop-style breeze-icon-theme mpv-libs ffmpegthumbnailer" ;;
        *) say "  see the Requirements table in README.md for your distribution's package names" ;;
    esac
}

# PySide6 from the distribution (pip's copy carries its own Qt, which cannot see the distribution's Kirigami)
if ! "$python" -c 'import PySide6.QtQuick, PySide6.QtQml' 2>/dev/null; then
    say "PySide6 (Qt for Python) is not installed for $python. Install it from your distribution, for example:"
    hint
    exit 1
fi

# Kirigami: look where distributions put QML modules
kirigami=""
extra_qml="${QML2_IMPORT_PATH:-}"
for dir in /usr/lib64/qt6/qml /usr/lib/qt6/qml /usr/lib/x86_64-linux-gnu/qt6/qml /usr/lib/aarch64-linux-gnu/qt6/qml \
           /usr/lib/qt/qml /usr/lib64/qt/qml ${extra_qml//:/ }; do
    [ -f "$dir/org/kde/kirigami/qmldir" ] && { kirigami=$dir; break; }
done
if [ -z "$kirigami" ]; then
    say "Kirigami (KDE's interface toolkit) was not found. Install it first, for example:"
    hint
    say "(If it is installed somewhere unusual, put that folder in QML2_IMPORT_PATH and run this again.)"
    exit 1
fi

say "Installing Tetia $(sed -n 's/^version = "\(.*\)"/\1/p' "$here/pyproject.toml") into $prefix ..."

# ---- the Python environment ---------------------------------------------------------------------------------------
# --system-site-packages: use the distribution's PySide6. --no-deps: never fetch pip's PySide6 on top of it.
rm -rf "$app_dir"
mkdir -p "$app_dir"
"$python" -m venv --system-site-packages "$app_dir/venv" \
    || die "could not create a Python environment (on Debian and Ubuntu: sudo apt install python3-venv)"
"$app_dir/venv/bin/python" -m pip install --quiet --no-deps --disable-pip-version-check "$here" \
    || die "pip could not install Tetia (it needs a network connection for the build tools)"

# ---- the command, the menu entry and the icon ----------------------------------------------------------------------
mkdir -p "$prefix/bin" "$prefix/share/applications" "$prefix/share/icons/hicolor/scalable/apps" "$prefix/share/metainfo"
ln -sf "$app_dir/venv/bin/tetia" "$prefix/bin/tetia"
# an absolute Exec, so the menu finds it even when ~/.local/bin is not on the desktop session's PATH
sed "s|^Exec=.*|Exec=$prefix/bin/tetia|" "$here/data/$app_id.desktop" > "$prefix/share/applications/$app_id.desktop"
install -m644 "$here/data/icons/hicolor/scalable/apps/$app_id.svg" "$prefix/share/icons/hicolor/scalable/apps/$app_id.svg"
install -m644 "$here/data/$app_id.metainfo.xml" "$prefix/share/metainfo/$app_id.metainfo.xml"

# refresh the menu and icon caches where those tools exist (harmless when they do not)
command -v update-desktop-database >/dev/null && update-desktop-database "$prefix/share/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$prefix/share/icons/hicolor" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

say ""
say "Done. Start Tetia from the application menu, or run:  $prefix/bin/tetia"
case ":$PATH:" in *":$prefix/bin:"*) ;; *) say "(Add $prefix/bin to your PATH to start it by typing 'tetia'.)" ;; esac
command -v ffmpegthumbnailer >/dev/null || say "Tip: install ffmpegthumbnailer to get video thumbnails."
"$python" -c 'import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library("mpv") else 1)' \
    || say "Tip: install libmpv (mpv-libs / libmpv2) to play videos inside Tetia; without it they open in your default player."
say "To remove it again: ./uninstall.sh"
