#!/usr/bin/env bash
# Archive and upload to TestFlight (internal testing only; never submits for review).
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_macos
for v in ASC_KEY_ID ASC_ISSUER_ID ASC_KEY_CONTENT_BASE64; do
  [ -n "${!v:-}" ] || { echo "error: $v is not set (see README: App Store Connect API key)" >&2; exit 3; }
done
# xcodebuild's -authenticationKeyPath needs a file: decode the key into a private temp file
# (gitignored .factory-tmp, mode 0600) and always delete it on exit.
KEY_DIR="$TMP/asc-key"
mkdir -p "$KEY_DIR"; chmod 700 "$KEY_DIR"
export FACTORY_ASC_KEY_FILE="$KEY_DIR/AuthKey_${ASC_KEY_ID}.p8"
cleanup_key() { rm -f "$FACTORY_ASC_KEY_FILE"; }
trap cleanup_key EXIT
( umask 077; PYTHONPATH="$PLUGIN_ROOT/lib" python3 -c "
import sys
from appfactory.asc.auth import private_key_pem, MissingCredentials
try:
    sys.stdout.write(private_key_pem())
except MissingCredentials as exc:
    sys.exit(f'error: {exc}')" >"$FACTORY_ASC_KEY_FILE" )
generate_project
if [ -f Gemfile ] && command -v bundle >/dev/null 2>&1; then
  bundle check >/dev/null 2>&1 || bundle install --quiet
  FASTLANE=(bundle exec fastlane)
else
  require_tool fastlane "brew install fastlane"
  FASTLANE=(fastlane)
fi
LOG="$TMP/logs/testflight-$(date +%Y%m%d-%H%M%S).log"
set +e
FASTLANE_SKIP_UPDATE_CHECK=1 FASTLANE_HIDE_TIMESTAMP=1 "${FASTLANE[@]}" beta >"$LOG" 2>&1
RC=$?
set -e
# fastlane logs can contain account details; keep them in the gitignored tmp dir only.
if [ $RC -ne 0 ]; then echo "upload FAILED (log: ${LOG#$ROOT/})" >&2; tail -30 "$LOG" | redact_stream >&2; exit $RC; fi
echo "uploaded; now run: app-factory testflight verify" >&2
