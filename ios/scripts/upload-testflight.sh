#!/bin/bash
# Run only with authorized App Store Connect credentials, after the UI tests pass.
# Apple automatic provisioning / cloud signing must be permitted for this API key.
set -euo pipefail
set +x

for name in MISHMARON_TEAM_ID ASC_KEY_ID ASC_ISSUER_ID ASC_PRIVATE_KEY_BASE64 MISHMARON_BUILD_NUMBER; do
  if [ -z "${!name:-}" ]; then
    printf 'Missing required secret/input: %s\n' "$name" >&2
    exit 1
  fi
done
[[ "$MISHMARON_TEAM_ID" =~ ^[A-Z0-9]{10}$ ]] || { echo 'Invalid Team ID format.' >&2; exit 1; }
[[ "$ASC_KEY_ID" =~ ^[A-Z0-9]{10}$ ]] || { echo 'Invalid API Key ID format.' >&2; exit 1; }
[[ "$ASC_ISSUER_ID" =~ ^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$ ]] || { echo 'Invalid Issuer ID format.' >&2; exit 1; }
[[ "$MISHMARON_BUILD_NUMBER" =~ ^[1-9][0-9]{0,3}$ ]] || { echo 'Build number must be an unused integer from 1 to 9999.' >&2; exit 1; }
if [ "${GITHUB_ACTIONS:-}" = true ] && [ "${GITHUB_REF:-}" != refs/heads/mishmaron-ios-preparation ]; then
  echo 'Uploads are restricted to mishmaron-ios-preparation.' >&2
  exit 1
fi
[[ "$(uname -s)" = Darwin ]] || { echo 'Signing requires a Mac with Xcode.' >&2; exit 1; }
command -v xcodegen >/dev/null
sdk_version=$(xcrun --sdk iphoneos --show-sdk-version)
[[ "${sdk_version%%.*}" -ge 26 ]] || { echo 'iOS SDK 26 or later is required.' >&2; exit 1; }

cd "$(dirname "$0")/.."
umask 077
private_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/mishmaron-signing.XXXXXX")
keychain_path="$private_dir/signing.keychain-db"
original_keychain=$(security default-keychain -d user | tr -d '"' | sed 's/^ *//')
cleanup() {
  security default-keychain -d user -s "$original_keychain" >/dev/null 2>&1 || true
  security delete-keychain "$keychain_path" >/dev/null 2>&1 || true
  rm -rf "$private_dir"
}
trap cleanup EXIT
export MISHMARON_PRIVATE_DIR="$private_dir"
python3 - <<'PY'
import base64, os, pathlib
try:
    key = base64.b64decode(''.join(os.environ['ASC_PRIVATE_KEY_BASE64'].split()), validate=True)
    if not key.startswith(b'-----BEGIN PRIVATE KEY-----'):
        raise ValueError()
    path = pathlib.Path(os.environ['MISHMARON_PRIVATE_DIR']) / 'AuthKey.p8'
    path.write_bytes(key)
    path.chmod(0o600)
except (ValueError, OSError):
    raise SystemExit('Invalid App Store Connect private key; configure the GitHub secret securely.')
PY
unset ASC_PRIVATE_KEY_BASE64
openssl pkey -in "$private_dir/AuthKey.p8" -check -noout >/dev/null 2>&1 || { echo 'Invalid private key.' >&2; exit 1; }
keychain_password=$(openssl rand -hex 32)
security create-keychain -p "$keychain_password" "$keychain_path"
security set-keychain-settings -lut 21600 "$keychain_path"
security unlock-keychain -p "$keychain_password" "$keychain_path"
security default-keychain -d user -s "$keychain_path"

auth=(-allowProvisioningUpdates -authenticationKeyPath "$private_dir/AuthKey.p8" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
build_dir="$PWD/build/testflight"
if [ -e "$build_dir" ]; then
  echo 'ios/build/testflight already exists; use a fresh checkout for each upload.' >&2
  exit 1
fi
mkdir -p "$build_dir"
xcodegen generate
xcodebuild -project Mishmaron.xcodeproj -scheme Mishmaron -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$build_dir/Mishmaron.xcarchive" \
  DEVELOPMENT_TEAM="$MISHMARON_TEAM_ID" CODE_SIGN_STYLE=Automatic \
  CURRENT_PROJECT_VERSION="$MISHMARON_BUILD_NUMBER" MARKETING_VERSION=1.2.0 \
  "${auth[@]}" archive

export MISHMARON_BUILD_DIR="$build_dir"
python3 - <<'PY'
import os, pathlib, plistlib
root = pathlib.Path(os.environ['MISHMARON_BUILD_DIR'])
app = root / 'Mishmaron.xcarchive/Products/Applications/Mishmaron.app'
with (app / 'Info.plist').open('rb') as f:
    info = plistlib.load(f)
expected = {'CFBundleIdentifier': 'il.co.mishmaron.app', 'CFBundleShortVersionString': '1.2.0', 'CFBundleVersion': os.environ['MISHMARON_BUILD_NUMBER']}
if any(info.get(k) != v for k, v in expected.items()):
    raise SystemExit('Archive identity/version mismatch; upload stopped.')
for destination in ('export', 'upload'):
    options = {'method': 'app-store-connect', 'teamID': os.environ['MISHMARON_TEAM_ID'], 'signingStyle': 'automatic', 'destination': destination, 'manageAppVersionAndBuildNumber': False, 'uploadSymbols': True}
    with (root / (destination + '.plist')).open('wb') as f:
        plistlib.dump(options, f)
PY
xcodebuild -exportArchive -archivePath "$build_dir/Mishmaron.xcarchive" \
  -exportOptionsPlist "$build_dir/export.plist" -exportPath "$build_dir/export" "${auth[@]}"
shopt -s nullglob
ipas=("$build_dir/export/"*.ipa)
[[ "${#ipas[@]}" -eq 1 ]] || { echo 'Expected exactly one signed IPA.' >&2; exit 1; }
ditto -x -k "${ipas[0]}" "$private_dir/ipa"
apps=("$private_dir/ipa/Payload/"*.app)
[[ "${#apps[@]}" -eq 1 ]] || { echo 'Expected one application inside the IPA.' >&2; exit 1; }
codesign --verify --deep --strict "${apps[0]}"

xcodebuild -exportArchive -archivePath "$build_dir/Mishmaron.xcarchive" \
  -exportOptionsPlist "$build_dir/upload.plist" -exportPath "$build_dir/upload" "${auth[@]}"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    printf 'Apple upload command succeeded for il.co.mishmaron.app 1.2.0 (%s).\n\n' "$MISHMARON_BUILD_NUMBER"
    printf 'Commit: %s\n\n' "${GITHUB_SHA:-local}"
    printf 'Confirm processing and build availability in App Store Connect app 6820580792 before reporting TestFlight success. No App Review or public release was submitted.\n'
  } >> "$GITHUB_STEP_SUMMARY"
fi
printf 'Upload command completed. App Store Connect processing and TestFlight device checks still need verification.\n'
