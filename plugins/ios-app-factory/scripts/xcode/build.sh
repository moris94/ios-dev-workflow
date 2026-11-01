#!/usr/bin/env bash
# Generate the Xcode project and build app + tests for the simulator.
# Writes factory/reports/build.json (status + source digest) for the implementation gate.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_macos
generate_project

STARTED="$(now_utc)"
LOG="$TMP/logs/build-$(date +%Y%m%d-%H%M%S).log"
DEST="generic/platform=iOS Simulator"
set +e
xcodebuild -project "$PROJECT_NAME.xcodeproj" -scheme "$SCHEME" -configuration Debug \
  -destination "$DEST" -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO build-for-testing >"$LOG" 2>&1
RC=$?
set -e
WARN=$(grep -c " warning: " "$LOG" || true)
ERR=$(grep -c " error: " "$LOG" || true)
STATUS=success; [ $RC -eq 0 ] || STATUS=failure
"$AF" report build --status "$STATUS" --scheme "$SCHEME" --configuration Debug --destination "$DEST" \
  --started-at "$STARTED" --log "${LOG#$ROOT/}" --xcode-version "$(xcode_version)" --warnings "$WARN" --errors "$ERR" >/dev/null
if [ $RC -ne 0 ]; then
  echo "build FAILED ($ERR errors). First errors:" >&2
  grep " error: " "$LOG" | head -20 >&2
  exit $RC
fi
echo "build succeeded ($WARN warnings). Log: ${LOG#$ROOT/}" >&2
