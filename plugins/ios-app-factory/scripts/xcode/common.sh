#!/usr/bin/env bash
# Shared helpers for ios-app-factory Xcode scripts. Never prints secret values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AF="$PLUGIN_ROOT/bin/app-factory"

find_root() {
  local d="${APP_FACTORY_PROJECT:-$PWD}"
  while [ "$d" != "/" ]; do
    if [ -f "$d/factory/config.json" ]; then echo "$d"; return 0; fi
    d="$(dirname "$d")"
  done
  echo "error: factory/config.json not found (run app-factory init)" >&2
  return 1
}

ROOT="$(find_root)"
cd "$ROOT"
TMP="$ROOT/.factory-tmp"
mkdir -p "$TMP/logs" "$TMP/results"

cfg() { python3 -c "import json,sys; c=json.load(open('factory/config.json')); v=c
for k in sys.argv[1].split('.'): v=v[k]
print(v if not isinstance(v,(list,dict)) else json.dumps(v))" "$1"; }

PROJECT_NAME="$(cfg app.project_name)"
SCHEME="$(cfg app.scheme)"
DERIVED="$TMP/DerivedData"
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

require_macos() {
  if [ "$(uname -s)" != "Darwin" ] || ! command -v xcodebuild >/dev/null 2>&1; then
    echo "error: this step needs macOS with Xcode (xcodebuild). Run it on a Mac; the gate stays failed until then." >&2
    exit 3
  fi
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found. Install with: $2" >&2; exit 3; }
}

generate_project() {
  require_tool xcodegen "brew install xcodegen"
  xcodegen generate --spec project.yml --quiet
}

xcode_version() { xcodebuild -version 2>/dev/null | head -1 | tr -d '\n'; }

default_simulator() {
  if [ -n "${FACTORY_SIMULATOR:-}" ]; then echo "$FACTORY_SIMULATOR"; return; fi
  "$AF" screenshots devices | python3 -c "import json,sys; d=json.load(sys.stdin); print(next(iter(d.values()))['simulator'])"
}

# Print stdin with secrets redacted (env secret values, private keys, JWTs).
redact_stream() { PYTHONPATH="$PLUGIN_ROOT/lib" python3 -c "import sys; from appfactory.redact import redact; sys.stdout.write(redact(sys.stdin.read()))"; }
