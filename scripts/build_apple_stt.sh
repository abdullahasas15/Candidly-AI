#!/usr/bin/env bash
# R3.5: Build the Apple on-device STT helper (SwiftPM).
set -euo pipefail
cd "$(dirname "$0")/../native/apple_stt"
swift build -c release
BIN="$(swift build -c release --show-bin-path)/apple_stt"
if [[ ! -x "$BIN" ]]; then
  echo "ERROR: apple_stt binary not found at $BIN" >&2
  exit 1
fi
echo "APPLE_STT_BINARY=$BIN"
"$BIN" --check --mode speechanalyzer --locale "${1:-en-US}" || true
