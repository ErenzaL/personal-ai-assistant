#!/usr/bin/env bash
# Package the FastAPI backend into one self-contained executable and place it
# where Tauri expects a sidecar: desktop/src-tauri/binaries/dully-backend-<target>.
# Needs backend/.venv (see backend/README.md) and the Rust toolchain (for the
# target triple). Nothing from backend/.env is included.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
PY="$BACKEND/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "backend/.venv is missing; follow backend/README.md first" >&2
  exit 1
fi

"$PY" -m pip install --quiet --disable-pip-version-check -r "$BACKEND/requirements.txt" pyinstaller
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
OUT="$ROOT/desktop/src-tauri/binaries"
mkdir -p "$OUT"

cd "$BACKEND"
mkdir -p build dist
"$PY" -m PyInstaller --noconfirm --clean --onefile --name dully-backend \
  --distpath dist --workpath build --specpath build \
  --add-data "$BACKEND/app/database/migrations:app/database/migrations" \
  --collect-submodules uvicorn --collect-submodules app \
  run_backend.py > build/pyinstaller.log 2>&1 || { tail -40 build/pyinstaller.log >&2; exit 1; }

cp "dist/dully-backend" "$OUT/dully-backend-$TRIPLE"
echo "packaged backend: $OUT/dully-backend-$TRIPLE ($(du -h "dist/dully-backend" | cut -f1))"
