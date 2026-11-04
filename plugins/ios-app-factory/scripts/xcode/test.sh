#!/usr/bin/env bash
# Run unit + UI tests in English and Japanese; write factory/reports/tests.json.
#
#   test.sh                                         full run (both locales, all tests)
#   test.sh --only-failed --reason environment --note "simulator boot timed out"
#   test.sh --only-failed --reason test-defect --note "fixed wrong accessibility id in AppUITests"
#
# A partial re-run executes only the failed cases (plus every test of test classes whose files
# changed, for test-defect) and merges them into the last report. It is refused when app code
# changed since the full run, and limited to testing.max_partial_reruns (default 2).
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
ONLY_FAILED=0; REASON=""; NOTE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --only-failed) ONLY_FAILED=1 ;;
    --reason) REASON="$2"; shift ;;
    --note) NOTE="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ $ONLY_FAILED -eq 1 ]; then
  [ -n "$REASON" ] && [ -n "$NOTE" ] || { echo "error: --only-failed needs --reason environment|test-defect and --note" >&2; exit 2; }
  "$AF" report rerun-plan --reason "$REASON" >/dev/null   # fails early with the policy reason if not allowed
fi
require_macos
generate_project
SIM="$(default_simulator)"
DEST="platform=iOS Simulator,name=$SIM"
ARGS=()
OVERALL=0
for pair in "en-US:en:US" "ja:ja:JP"; do
  IFS=: read -r LOCALE LANG REGION <<<"$pair"
  SELECT=(-skip-testing:AppUITests/ScreenshotTests)
  SUFFIX=""
  if [ $ONLY_FAILED -eq 1 ]; then
    SELECT=()
    while IFS= read -r line; do [ -n "$line" ] && SELECT+=("$line"); done < <("$AF" report rerun-plan --reason "$REASON" --locale "$LOCALE")
    if [ ${#SELECT[@]} -eq 0 ]; then echo "tests [$LOCALE] nothing to re-run" >&2; continue; fi
    SUFFIX="-rerun"
  fi
  BUNDLE="$TMP/results/test-$LOCALE$SUFFIX.xcresult"
  rm -rf "$BUNDLE"
  LOG="$TMP/logs/test-$LOCALE$SUFFIX.log"
  set +e
  xcodebuild test -project "$PROJECT_NAME.xcodeproj" -scheme "$SCHEME" -destination "$DEST" \
    -derivedDataPath "$DERIVED" -resultBundlePath "$BUNDLE" \
    -testLanguage "$LANG" -testRegion "$REGION" \
    "${SELECT[@]}" CODE_SIGNING_ALLOWED=NO >"$LOG" 2>&1
  RC=$?
  set -e
  [ $RC -eq 0 ] || OVERALL=$RC
  xcrun xcresulttool get test-results tests --path "$BUNDLE" >"$TMP/results/tests-$LOCALE$SUFFIX.json"
  ARGS+=("$LOCALE=$TMP/results/tests-$LOCALE$SUFFIX.json")
  echo "tests [$LOCALE]$SUFFIX exit=$RC (log ${LOG#$ROOT/})" >&2
done
if [ ${#ARGS[@]} -eq 0 ]; then echo "error: no tests were run" >&2; exit 2; fi
if [ $ONLY_FAILED -eq 1 ]; then
  "$AF" report tests "${ARGS[@]}" --rerun --reason "$REASON" --note "$NOTE"
else
  "$AF" report tests "${ARGS[@]}" --destination "$DEST" --xcode-version "$(xcode_version)"
fi
exit $OVERALL
