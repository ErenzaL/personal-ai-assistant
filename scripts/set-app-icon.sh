#!/usr/bin/env bash
# Make an image the app icon: generates every size into desktop/src-tauri/icons,
# rebuilds the release app and DMG, and reinstalls /Applications/Dully.app.
# Usage: scripts/set-app-icon.sh path/to/logo.png   (square PNG, 1024 px or larger)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${1:?usage: set-app-icon.sh path/to/logo.png}"
[ -f "$IMAGE" ] || { echo "no such file: $IMAGE" >&2; exit 1; }
# Absolute path: the icon tool runs from desktop/, not from where this was called.
IMAGE="$(cd "$(dirname "$IMAGE")" && pwd)/$(basename "$IMAGE")"

cd "$ROOT/desktop"
npx tauri icon "$IMAGE"
"$ROOT/scripts/build-release.sh"

APP="$ROOT/desktop/src-tauri/target/release/bundle/macos/Dully.app"
pkill -TERM -f "/Applications/Dully.app/Contents/MacOS/Dully" 2>/dev/null || true
sleep 2
rm -rf /Applications/Dully.app
ditto "$APP" /Applications/Dully.app
touch /Applications/Dully.app
open /Applications/Dully.app
echo "installed with the new icon"
