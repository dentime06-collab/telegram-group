#!/bin/bash
set -eo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == Darwin ]] || { echo 'Для сборки требуется macOS'; exit 1; }
arch="$(uname -m)"
args=()
if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  args+=(--codesign-identity "$CODESIGN_IDENTITY" --osx-entitlements-file scripts/entitlements.plist)
fi
python -m PyInstaller --noconfirm --clean --windowed --onedir --name 'Telegram Group Sender' \
  --osx-bundle-identifier org.telegramgroupsender.desktop --target-arch "$arch" \
  --collect-submodules keyring.backends --hidden-import telethon.crypto.aes "${args[@]}" main.py
app='dist/Telegram Group Sender.app'
codesign --verify --deep --strict "$app"
QT_QPA_PLATFORM=offscreen "$app/Contents/MacOS/Telegram Group Sender" --smoke-test
mkdir -p release
ditto -c -k --sequesterRsrc --keepParent "$app" "release/TelegramGroupSender-${arch}.zip"
if [[ -n "${NOTARY_APPLE_ID:-}" ]]; then
  : "${NOTARY_TEAM_ID:?Required}" "${NOTARY_PASSWORD:?Required}"
  xcrun notarytool submit "release/TelegramGroupSender-${arch}.zip" --apple-id "$NOTARY_APPLE_ID" --team-id "$NOTARY_TEAM_ID" --password "$NOTARY_PASSWORD" --wait
  xcrun stapler staple "$app"
  xcrun stapler validate "$app"
  spctl --assess --type execute --verbose "$app"
  ditto -c -k --sequesterRsrc --keepParent "$app" "release/TelegramGroupSender-${arch}.zip"
fi
shasum -a 256 "release/TelegramGroupSender-${arch}.zip" > "release/TelegramGroupSender-${arch}.sha256"
