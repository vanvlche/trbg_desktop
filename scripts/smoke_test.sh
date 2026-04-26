#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  PYTHON_BIN="python"
fi

SMOKE_DIR="tmp_smoke"
SAVE_FILE="$SMOKE_DIR/tmp_smoke_save.json"
LOG_DIR="$SMOKE_DIR/logs"

mkdir -p "$SMOKE_DIR"

"$PYTHON_BIN" quiet_relay_vertical_slice_datadriven.py \
  --auto \
  --fresh \
  --seed 1 \
  --save-file "$SAVE_FILE" \
  --log-dir "$LOG_DIR"
