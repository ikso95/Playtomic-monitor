#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Playtomic Monitor"
APP_DIR="$ROOT_DIR/build/$APP_NAME.app"
BIN_DIR="$APP_DIR/Contents/MacOS"
CONTENTS_DIR="$APP_DIR/Contents"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
ICONSET_DIR="$ROOT_DIR/.build/PlaytomicMonitor.iconset"
ICON_SOURCE="$ROOT_DIR/Sources/PlaytomicMonitorApp/Resources/PadelRacketBall.png"

swift build -c release --package-path "$ROOT_DIR"
mkdir -p "$BIN_DIR" "$RESOURCES_DIR" "$ICONSET_DIR"
cp "$ROOT_DIR/.build/release/PlaytomicMonitorApp" "$BIN_DIR/PlaytomicMonitorApp"
cp "$ICON_SOURCE" "$RESOURCES_DIR/PadelRacketBall.png"

sips -z 16 16 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
iconutil -c icns -o "$RESOURCES_DIR/PlaytomicMonitor.icns" "$ICONSET_DIR"
printf 'APPL????' > "$CONTENTS_DIR/PkgInfo"

cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleExecutable</key>
    <string>PlaytomicMonitorApp</string>
    <key>CFBundleIdentifier</key>
    <string>local.playtomic.monitor</string>
    <key>CFBundleIconFile</key>
    <string>PlaytomicMonitor</string>
    <key>CFBundleName</key>
    <string>Playtomic Monitor</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

echo "Built $APP_DIR"
