#!/usr/bin/env bash
# Run unit + UI tests in English and Japanese; write factory/reports/tests.json.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_macos
generate_project
SIM="$(default_simulator)"
DEST="platform=iOS Simulator,name=$SIM"
ARGS=()
OVERALL=0
for pair in "en-US:en:US" "ja:ja:JP"; do
  IFS=: read -r LOCALE LANG REGION <<<"$pair"
  BUNDLE="$TMP/results/test-$LOCALE.xcresult"
  rm -rf "$BUNDLE"
  LOG="$TMP/logs/test-$LOCALE.log"
  set +e
  xcodebuild test -project "$PROJECT_NAME.xcodeproj" -scheme "$SCHEME" -destination "$DEST" \
    -derivedDataPath "$DERIVED" -resultBundlePath "$BUNDLE" \
    -testLanguage "$LANG" -testRegion "$REGION" \
    -skip-testing:AppUITests/ScreenshotTests CODE_SIGNING_ALLOWED=NO >"$LOG" 2>&1
  RC=$?
  set -e
  [ $RC -eq 0 ] || OVERALL=$RC
  xcrun xcresulttool get test-results tests --path "$BUNDLE" >"$TMP/results/tests-$LOCALE.json"
  ARGS+=("$LOCALE=$TMP/results/tests-$LOCALE.json")
  echo "tests [$LOCALE] exit=$RC (log ${LOG#$ROOT/})" >&2
done
"$AF" report tests "${ARGS[@]}" --destination "$DEST" --xcode-version "$(xcode_version)"
exit $OVERALL
