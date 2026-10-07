#!/bin/bash
set -euo pipefail
# Run on an authorized Mac after Apple Developer membership activation.
: "${MISHMARON_TEAM_ID:?Set the activated Apple Developer Team ID}"
cd "$(dirname "$0")/.."
command -v xcodegen >/dev/null
sdk_version=$(xcrun --sdk iphoneos --show-sdk-version)
[ "${sdk_version%%.*}" -ge 26 ] || { echo 'iOS SDK 26 or later is required.' >&2; exit 1; }
xcodegen generate
mkdir -p build
python3 - <<'PY'
import os,plistlib
with open('build/ExportOptions.plist','wb') as f:
 plistlib.dump({'method':'app-store-connect','teamID':os.environ['MISHMARON_TEAM_ID'],'signingStyle':'automatic','destination':'export','manageAppVersionAndBuildNumber':False},f)
PY
xcodebuild -project Mishmaron.xcodeproj -scheme Mishmaron -configuration Release \
 -destination 'generic/platform=iOS' -archivePath build/Mishmaron.xcarchive \
 DEVELOPMENT_TEAM="$MISHMARON_TEAM_ID" -allowProvisioningUpdates archive
xcodebuild -exportArchive -archivePath build/Mishmaron.xcarchive \
 -exportOptionsPlist build/ExportOptions.plist -exportPath build/export -allowProvisioningUpdates
printf '%s\n' 'Signed export created in ios/build/export. This script does not upload or submit to App Review.'
