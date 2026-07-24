#!/usr/bin/env bash
# GuildModel macOS release build — run from the repo root on a Mac:
#   python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev,packaging]"
#   bash scripts/build_release_macos.sh
#
# Gates on the test suite, then produces in dist/:
#   GuildModel-<version>-macos-<arch>.zip   the .app, zipped with ditto
#   GuildModel-<version>-macos-<arch>.dmg   the .app on a drag-to-Applications image
#
# <arch> is the machine you build on (arm64 on Apple Silicon, x86_64 on
# Intel) — PyInstaller does not cross-compile, so ship one artifact per
# architecture. The .github/workflows/macos-build.yml workflow builds both
# on GitHub's runners if building locally is inconvenient.
#
# GuildModel renders 3D through PyVista/VTK, so the frozen .app is large
# (~500 MB). The app is ad-hoc signed by PyInstaller (required on Apple
# Silicon) but NOT notarized — first launch needs right-click > Open.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "missing .venv — create it first (see header)"; exit 1; }

# 1. Test gate — never ship a build from a red suite. CI runs the suite as
#    its own workflow step (with per-test timeouts) and sets the skip.
if [ "${GUILDMODEL_SKIP_TESTS:-0}" != "1" ]; then
    QT_QPA_PLATFORM=offscreen "$PY" -m pytest tests -q
fi

# 2. Version + arch stamps
VERSION="$("$PY" -c 'from guildmodel import __version__; print(__version__)')"
ARCH="$(uname -m)"
echo "Building GuildModel $VERSION for macOS/$ARCH"

# 3. Refresh icons (writes assets/icon.icns used by the spec's BUNDLE step)
"$PY" scripts/make_icon.py

# 4. Freeze -> dist/GuildModel.app
"$PY" -m PyInstaller guildmodel.spec --clean --noconfirm

APP="dist/GuildModel.app"
[ -d "$APP" ] || { echo "PyInstaller produced no $APP"; exit 1; }

# 5. Zip with ditto (preserves symlinks + executable bits; a plain zip of a
#    .app breaks the bundle)
ZIP="dist/GuildModel-$VERSION-macos-$ARCH.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "  zip: $ZIP"

# 6. DMG (drag-to-Applications)
DMG="dist/GuildModel-$VERSION-macos-$ARCH.dmg"
rm -f "$DMG"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "GuildModel $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "  dmg: $DMG"

# 7. Launch smoke test (skipped in headless CI where no window server exists)
if [ "${GUILDMODEL_SKIP_SMOKE:-0}" != "1" ]; then
    "$APP/Contents/MacOS/GuildModel" &
    SMOKE_PID=$!
    sleep 10
    if kill -0 "$SMOKE_PID" 2>/dev/null; then
        echo "  smoke test: app alive after 10s"
        kill "$SMOKE_PID"
    else
        echo "  smoke test FAILED: app exited early"; exit 1
    fi
fi

echo "Done."
