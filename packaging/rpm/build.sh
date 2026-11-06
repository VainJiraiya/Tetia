#!/usr/bin/env bash
# Builds the Tetia RPM in a Fedora container (needs Docker or Podman; works from any distribution).
#
#   packaging/rpm/build.sh                 # for the newest Fedora
#   FEDORA=43 packaging/rpm/build.sh       # for the Fedora a Nobara release is based on
#
# The package is plain Python, but it installs into the Python of the Fedora it was built on, so build it on the
# same Fedora version as the machine that installs it. The result is in dist-rpm/. Only committed files go in
# (WORKTREE=1 takes the files as they are now, to try a build before committing).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
version=$(sed -n 's/^version = "\(.*\)"/\1/p' "$root/pyproject.toml")
fedora=${FEDORA:-latest}
runner=${CONTAINER_RUNNER:-$(command -v podman || command -v docker)}
out="$root/dist-rpm"

[ -n "$runner" ] || { echo "Install Docker or Podman first." >&2; exit 1; }
mkdir -p "$out"
rm -f "$out"/*.rpm
if [ "${WORKTREE:-}" = 1 ]; then
    # for trying a build before committing: the files as they are now (not for releases)
    git -C "$root" ls-files -z -c -o --exclude-standard | grep -zv -e '^nix/' -e '^dist-rpm/' -e '^thumbdiag.py$' -e '^uri_check.py$' \
        | tar -C "$root" --null -T - --transform "s,^,Tetia-$version/," -czf "$out/Tetia-$version.tar.gz"
else
    git -C "$root" archive --format=tar.gz --prefix="Tetia-$version/" -o "$out/Tetia-$version.tar.gz" HEAD
fi

"$runner" run --rm -v "$out":/out -v "$here/tetia.spec":/tetia.spec:ro "fedora:$fedora" bash -euo pipefail -c '
    dnf -y -q install rpm-build python3-devel pyproject-rpm-macros python3-pip python3-wheel python3-setuptools \
        python3-pyside6 desktop-file-utils libappstream-glib appstream >/dev/null
    mkdir -p ~/rpmbuild/SOURCES
    cp /out/Tetia-*.tar.gz ~/rpmbuild/SOURCES/
    cp /tetia.spec ~/tetia.spec
    sed -i "s/^Version:.*/Version:        '"$version"'/" ~/tetia.spec
    rpmbuild -ba ~/tetia.spec
    cp ~/rpmbuild/RPMS/noarch/*.rpm ~/rpmbuild/SRPMS/*.src.rpm /out/
'
rm -f "$out/Tetia-$version.tar.gz"
echo
echo "Built:"
ls -1 "$out"/*.rpm
