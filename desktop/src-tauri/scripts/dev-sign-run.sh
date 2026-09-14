#!/bin/sh
# Cargo runner used by `tauri dev` on macOS.
#
# rustc leaves a "linker-signed" ad-hoc signature that does not bind the
# Info.plist embedded by build.rs (`codesign -dv` reports "Info.plist=not
# bound"). Re-signing binds it and gives the dev binary a stable identifier.
#
# Note this is NOT enough to obtain calendar permission in `tauri dev`: macOS
# attributes a privacy request to the responsible process, which for a binary
# started from a terminal is the terminal itself, so EventKit refuses without
# prompting. Calendar access has to be granted from a real bundle -- see
# docs/calendar-design.md. Everything else works normally here.
set -e

BIN="$1"
shift

codesign --force --sign - --identifier com.linerenza.personal-ai-assistant "$BIN" 2>/dev/null \
    || echo "warning: could not re-sign $BIN" >&2

exec "$BIN" "$@"
