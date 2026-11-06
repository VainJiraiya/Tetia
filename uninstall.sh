#!/usr/bin/env bash
# Removes what ./install.sh put in place. Your library (tags, ratings, favorites, covers) is kept unless you ask:
#
#   ./uninstall.sh                # remove the app, keep your data
#   ./uninstall.sh --purge        # also delete your Tetia data (asks first)
#   ./uninstall.sh --prefix DIR   # if you installed with --prefix DIR
#
# The thumbnails Tetia made live in the shared ~/.cache/thumbnails (Dolphin and Gwenview use them too)
# and are never touched. Your photos, videos and books are never touched either.
set -euo pipefail

prefix="${HOME}/.local"
purge=0
yes=0
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) prefix="${2:?--prefix needs a folder}"; shift 2 ;;
        --purge) purge=1; shift ;;
        --yes) yes=1; shift ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
done

app_id="io.github.VainJiraiya.Tetia"
removed=0
remove() {
    if [ -e "$1" ] || [ -L "$1" ]; then rm -rf "$1" && echo "Removed $1" && removed=1; fi
}

remove "$prefix/lib/tetia"
# only a command that points at our environment
if [ -L "$prefix/bin/tetia" ] && [ "$(readlink "$prefix/bin/tetia")" = "$prefix/lib/tetia/venv/bin/tetia" ]; then
    remove "$prefix/bin/tetia"
elif [ -L "$prefix/bin/tetia" ] && [ ! -e "$prefix/bin/tetia" ]; then
    remove "$prefix/bin/tetia"      # left dangling by the removal above
fi
remove "$prefix/share/applications/$app_id.desktop"
remove "$prefix/share/icons/hicolor/scalable/apps/$app_id.svg"
remove "$prefix/share/metainfo/$app_id.metainfo.xml"

command -v update-desktop-database >/dev/null && update-desktop-database "$prefix/share/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$prefix/share/icons/hicolor" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

[ "$removed" = 1 ] || echo "Nothing to remove under $prefix (was it installed with --prefix?)"

data="${XDG_DATA_HOME:-$HOME/.local/share}/tetia"
if [ "$purge" = 1 ]; then
    if [ -d "$data" ]; then
        if [ "$yes" != 1 ]; then
            echo
            echo "This deletes your Tetia data: $data"
            echo "(your library, tags, ratings, favorites and covers; your files themselves are not touched)"
            printf 'Type "delete" to confirm: '
            read -r answer
            [ "$answer" = "delete" ] || { echo "Kept your data."; exit 0; }
        fi
        rm -rf "$data" && echo "Removed $data"
    else
        echo "No Tetia data found at $data"
    fi
elif [ -d "$data" ]; then
    echo
    echo "Kept your data in $data (run ./uninstall.sh --purge to delete it too)."
fi
