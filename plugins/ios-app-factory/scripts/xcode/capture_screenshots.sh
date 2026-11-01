#!/usr/bin/env bash
# Capture real app screens via AppUITests/ScreenshotTests for every locale x device,
# collect them into factory/screenshots/raw and compose the final store images.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_macos
generate_project
DEVICES_JSON="$("$AF" screenshots devices)"
for DEVICE in $(echo "$DEVICES_JSON" | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin)))"); do
  SIM="${FACTORY_SIMULATOR:-$(echo "$DEVICES_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['$DEVICE']['simulator'])")}"
  UDID="$(xcrun simctl list devices available -j | python3 -c "
import json,sys
d=json.load(sys.stdin)['devices']
m=[x['udid'] for r in d.values() for x in r if x['name']==sys.argv[1]]
print(m[0] if m else '')" "$SIM")"
  if [ -z "$UDID" ]; then echo "error: simulator '$SIM' not installed (set FACTORY_SIMULATOR or install it in Xcode)" >&2; exit 3; fi
  xcrun simctl boot "$UDID" 2>/dev/null || true
  xcrun simctl bootstatus "$UDID" -b >/dev/null
  xcrun simctl status_bar "$UDID" override --time "9:41" --dataNetwork wifi --wifiMode active --wifiBars 3 \
    --cellularMode active --cellularBars 4 --batteryState charged --batteryLevel 100
  for pair in "en-US:en:US" "ja:ja:JP"; do
    IFS=: read -r LOCALE LANG REGION <<<"$pair"
    OUT="$TMP/shots/$LOCALE/$DEVICE"
    BUNDLE="$TMP/results/shots-$LOCALE-$DEVICE.xcresult"
    rm -rf "$OUT" "$BUNDLE"; mkdir -p "$OUT"
    set +e
    TEST_RUNNER_FACTORY_SCREENSHOT_DIR="$OUT" xcodebuild test -project "$PROJECT_NAME.xcodeproj" -scheme "$SCHEME" \
      -destination "id=$UDID" -derivedDataPath "$DERIVED" -resultBundlePath "$BUNDLE" \
      -testLanguage "$LANG" -testRegion "$REGION" -only-testing:AppUITests/ScreenshotTests \
      CODE_SIGNING_ALLOWED=NO >"$TMP/logs/shots-$LOCALE-$DEVICE.log" 2>&1
    RC=$?
    set -e
    if [ $RC -ne 0 ]; then echo "error: ScreenshotTests failed for $LOCALE/$DEVICE (see .factory-tmp/logs)" >&2; exit $RC; fi
    xcrun xcresulttool export attachments --path "$BUNDLE" --output-path "$OUT" >/dev/null 2>&1 || true
    "$AF" screenshots collect --source "$OUT" --locale "$LOCALE" --device "$DEVICE" >/dev/null
    echo "captured $LOCALE/$DEVICE" >&2
  done
  xcrun simctl status_bar "$UDID" clear || true
done
"$AF" screenshots render
