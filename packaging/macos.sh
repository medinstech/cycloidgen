#!/usr/bin/env bash
#
# Wrap the macOS application bundle in a disk image.
#
#     python -m PyInstaller cycloidgen.spec --noconfirm
#     packaging/macos.sh
#
# The spec builds `dist/cycloidgen.app`; this is only the delivery.  A .dmg is
# what a Mac user expects to download - it opens to a window with the
# application on one side and a shortcut to /Applications on the other, and
# installing is dragging one onto the other.  There is nothing to run and
# nothing to uninstall afterwards but the folder itself.
#
# What this cannot do is make the first launch pleasant.  The bundle is signed
# ad-hoc, which is the minimum Apple Silicon will execute at all, but it is not
# signed with a Developer ID and it is not notarized - so Gatekeeper stops it
# once, and the user has to allow it by hand.  See RELEASING.md: that is a
# certificate away, not a rewrite.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

APP="${APP:-dist/cycloidgen.app}"
OUT_DIR="${OUT_DIR:-releases}"
ARCH="${ARCH:-$(uname -m)}"

version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' cycloidgen/__init__.py)
[ -n "$version" ] || { echo "cannot read __version__ out of cycloidgen/__init__.py" >&2; exit 1; }
[ -d "$APP" ] || { echo "no bundle at $APP - run PyInstaller first" >&2; exit 1; }

# Reported, not imposed.  PyInstaller signs every Mach-O it collects and then
# the bundle, ad-hoc, because arm64 refuses to load unsigned code at all - so
# there is a signature here already and re-signing over it with `--deep` is the
# documented way to break the nested ones.  This says what is actually on the
# thing that is about to ship.
#
# And it is allowed to stop the build: `set -e` and `pipefail` are still in
# force, so an unsigned or broken bundle fails here rather than on somebody
# else's Mac, where the symptom is an application that will not open and no
# reason given.
echo "signature:"
codesign --display --verbose=2 "$APP" 2>&1 | sed 's/^/  /'
codesign --verify --verbose=1 "$APP" 2>&1 | sed 's/^/  /'

staging="build/dmg"
rm -rf "$staging"
mkdir -p "$staging" "$OUT_DIR"
# `ditto` and not `cp`, because this bundle is signed.  A signature is not only
# bytes inside the Mach-O: for everything that is not one it lives in an
# extended attribute, and a copy that drops those produces a bundle that still
# looks complete and no longer verifies.  `ditto` is the tool Apple ships for
# copying a bundle without disturbing it - symlinks, xattrs, ACLs and all - and
# it names its destination, so the bundle has to be spelled out on both sides.
ditto "$APP" "$staging/$(basename "$APP")"
ln -s /Applications "$staging/Applications"

out="$OUT_DIR/cycloidgen-${version}-${ARCH}.dmg"
rm -f "$out"
# ULFO (LZFSE) rather than UDZO (zlib): it is both smaller and faster to
# decompress, and the only thing it costs is macOS 10.11 and older, which cannot
# run an arm64 binary anyway.  On a bundle that is most of a gigabyte of CAD
# kernel the difference is not academic.
hdiutil create \
    -volname "cycloidgen $version" \
    -srcfolder "$staging" \
    -ov -format ULFO \
    "$out"

ls -lh "$out"
