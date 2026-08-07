#!/usr/bin/env bash
#
# Build the Linux AppImage from a PyInstaller bundle.
#
#     python -m PyInstaller cycloidgen.spec --noconfirm
#     packaging/appimage.sh
#
# The Windows counterpart of this is `packaging/cycloidgen.nsi`, and the two do
# the same job by opposite means.  NSIS writes an installer that unpacks the
# bundle into Program Files and registers it; an AppImage installs nothing.  It
# is the bundle itself, in a squashfs image, behind a small runtime that mounts
# that image and runs what is inside - one file, chmod +x, double-click.  There
# is no Linux equivalent of "an installer", because there are a dozen of them
# and no two distributions agree; a file that runs everywhere is the closest
# thing to the same promise.
#
# What has to be in an AppDir is fixed by the format: an `AppRun` to start, a
# `.desktop` file naming it, and an icon whose basename matches the desktop
# file's `Icon=`.  Everything else is ours to arrange.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

BUILD_DIR="${BUILD_DIR:-dist/cycloidgen}"
OUT_DIR="${OUT_DIR:-releases}"
ARCH="${ARCH:-$(uname -m)}"

version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' cycloidgen/__init__.py)
[ -n "$version" ] || { echo "cannot read __version__ out of cycloidgen/__init__.py" >&2; exit 1; }
[ -x "$BUILD_DIR/cycloidgen" ] || { echo "no bundle at $BUILD_DIR - run PyInstaller first" >&2; exit 1; }

appdir="build/AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/bin" "$appdir/usr/share/applications" \
         "$appdir/usr/share/icons/hicolor/256x256/apps" "$OUT_DIR"

cp -a "$BUILD_DIR/." "$appdir/usr/bin/"

# The icon has to be a PNG - the runtime and every desktop that reads the
# `.desktop` file want one, and the .ico the Windows build uses is not it.  The
# brand mark is already the right size, so it is copied rather than converted:
# a conversion step is a thing that can silently produce a blank square.
cp cycloidgen/ui/assets/mark-blue.png "$appdir/cycloidgen.png"
cp "$appdir/cycloidgen.png" "$appdir/usr/share/icons/hicolor/256x256/apps/cycloidgen.png"

# `StartupWMClass` is what pairs the running window with this launcher, so the
# taskbar shows one icon with the right name instead of a second, generic entry
# beside it.  Qt reports the executable's name there.
cat > "$appdir/cycloidgen.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=cycloidgen
GenericName=Cycloidal drive generator
Comment=Parametric cycloidal drive design, analysis and CAD export
Exec=cycloidgen %f
Icon=cycloidgen
Terminal=false
Categories=Science;Engineering;Graphics;3DGraphics;
Keywords=cycloidal;gearbox;reducer;CAD;STEP;DXF;
StartupWMClass=cycloidgen
DESKTOP
cp "$appdir/cycloidgen.desktop" "$appdir/usr/share/applications/cycloidgen.desktop"

# A script rather than a symlink to the binary.  A symlink would work - the
# bootloader finds its own directory through /proc/self/exe, which resolves
# through one - but this is also where the two things a frozen Qt application
# needs on a strange machine get set, and there is nowhere else to put them.
cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
# `dirname $0` and not $APPDIR: the runtime exports APPDIR, but a user who
# extracted the image with --appimage-extract and ran AppRun by hand gets
# nothing, and that is the fallback path for a machine with no libfuse2.
root="$(dirname "$(readlink -f "$0")")"
# Qt looks for its platform plugins relative to the binary and finds them, but
# only once it knows it is not to trust a QT_ inherited from the host - a
# QT_PLUGIN_PATH pointing at the system Qt is the classic way for a bundled
# application to load half of one Qt and half of another and abort.
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
exec "$root/usr/bin/cycloidgen" "$@"
APPRUN
chmod +x "$appdir/AppRun"

# appimagetool is not packaged by any distribution, so it is fetched.  Pinned to
# a release rather than `continuous`: the tool that builds a release artefact is
# part of the release, and "whatever was on the server that morning" is not a
# thing a build can be reproduced from.
tool="build/appimagetool-x86_64.AppImage"
if [ ! -x "$tool" ]; then
    curl -fsSL -o "$tool" \
        "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
    chmod +x "$tool"
fi

# The tool is itself an AppImage, so on a machine or a CI runner with no FUSE it
# cannot mount itself either.  This is the documented way round that, and it is
# why the build does not need root to install libfuse2.
export APPIMAGE_EXTRACT_AND_RUN=1
out="$OUT_DIR/cycloidgen-${version}-${ARCH}.AppImage"
rm -f "$out"
ARCH="$ARCH" "$tool" "$appdir" "$out"

ls -l "$out"
