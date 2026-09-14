#!/usr/bin/env bash
# Build Dully.app (and Dully.dmg) for personal use: packaged backend, bundled
# frontend, ad-hoc signed. Output: desktop/src-tauri/target/release/bundle/macos/Dully.app
# and release/Dully.dmg.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/build-backend.sh"

cd "$ROOT/desktop"
npm run tauri build -- --bundles app --config src-tauri/tauri.prod.conf.json

APP="$ROOT/desktop/src-tauri/target/release/bundle/macos/Dully.app"
# Bind the Info.plist to the signature (the linker's own signature does not),
# which macOS needs before it will show the calendar permission prompt.
codesign --force --deep --sign - "$APP"

STAGE="$(mktemp -d)"
ditto "$APP" "$STAGE/Dully.app"
ln -s /Applications "$STAGE/Applications"
mkdir -p "$ROOT/release"
rm -f "$ROOT/release/Dully.dmg"
hdiutil create -volname Dully -srcfolder "$STAGE" -ov -format UDZO "$ROOT/release/Dully.dmg" > /dev/null
rm -rf "$STAGE"

echo "app: $APP"
echo "dmg: $ROOT/release/Dully.dmg"
