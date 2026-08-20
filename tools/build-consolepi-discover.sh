#!/bin/sh
# Build standalone ConsolePi Plus discovery clients for administrator workstations.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE="$ROOT/tools/consolepi-discover"
OUTPUT=${1:-"$ROOT/dist/consolepi-discover"}
VERSION=$(tr -d '\r\n' < "$ROOT/VERSION")

command -v go >/dev/null 2>&1 || {
    printf '%s\n' 'Chybí Go 1.22 nebo novější.' >&2
    exit 1
}

mkdir -p "$OUTPUT"
for target in darwin/amd64 darwin/arm64 linux/amd64 linux/arm64 windows/amd64; do
    os=${target%/*}
    arch=${target#*/}
    suffix=
    [ "$os" = windows ] && suffix=.exe
    name="consolepi-discover-${os}-${arch}${suffix}"
    printf 'Building %s\n' "$name"
    (
        cd "$SOURCE"
        GOOS="$os" GOARCH="$arch" CGO_ENABLED=0 go build -trimpath \
            -buildvcs=false -ldflags='-s -w' -o "$OUTPUT/$name" .
    )
done

if [ "$(uname -s)" = Darwin ] && command -v lipo >/dev/null 2>&1 && command -v ditto >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
    mac_app="$OUTPUT/ConsolePi Plus Discovery.app"
    icon_work=$(mktemp -d "$OUTPUT/.consolepi-discover-icon.XXXXXX")
    iconset="$icon_work/ConsolePiDiscovery.iconset"
    windows_resource="$SOURCE/consolepi-discovery_windows_amd64.syso"
    trap 'rm -rf "$icon_work"; rm -f "$windows_resource"' EXIT HUP INT TERM
    # An older Finder-opened application bundle can retain metadata that
    # invalidates a fresh ad-hoc signature.  Recreate only this generated
    # package from scratch for every build.
    rm -rf "$mac_app"
    mkdir -p "$iconset"
    for icon_spec in \
        'icon_16x16.png:16' 'icon_16x16@2x.png:32' \
        'icon_32x32.png:32' 'icon_32x32@2x.png:64' \
        'icon_128x128.png:128' 'icon_128x128@2x.png:256' \
        'icon_256x256.png:256' 'icon_256x256@2x.png:512' \
        'icon_512x512.png:512' 'icon_512x512@2x.png:1024'; do
        icon_name=${icon_spec%:*}
        icon_size=${icon_spec#*:}
        icon_source="$icon_work/source-$icon_size.png"
        sips -Z "$icon_size" "$SOURCE/assets/consolepi-discovery-icon.png" --out "$icon_source" >/dev/null 2>&1
        sips --padToHeightWidth "$icon_size" "$icon_size" --padColor 12302e \
            "$icon_source" --out "$iconset/$icon_name" >/dev/null 2>&1
    done
    mkdir -p "$mac_app/Contents/MacOS"
    mkdir -p "$mac_app/Contents/Resources"
    lipo -create \
        "$OUTPUT/consolepi-discover-darwin-amd64" \
        "$OUTPUT/consolepi-discover-darwin-arm64" \
        -output "$mac_app/Contents/MacOS/ConsolePi Plus Discovery"
    chmod 0755 "$mac_app/Contents/MacOS/ConsolePi Plus Discovery"
    go run "$ROOT/tools/consolepi-discover-iconpack.go" "$iconset" \
        "$mac_app/Contents/Resources/ConsolePiDiscovery.icns" \
        "$OUTPUT/ConsolePi-Plus-Discovery.ico" "$windows_resource"
    printf '%s\n' \
        '<?xml version="1.0" encoding="UTF-8"?>' \
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
        '<plist version="1.0"><dict>' \
        '<key>CFBundleName</key><string>ConsolePi Plus Discovery</string>' \
        '<key>CFBundleDisplayName</key><string>ConsolePi Plus Discovery</string>' \
        '<key>CFBundleIdentifier</key><string>cz.consolepi.discovery</string>' \
        '<key>CFBundleExecutable</key><string>ConsolePi Plus Discovery</string>' \
        '<key>CFBundleIconFile</key><string>ConsolePiDiscovery</string>' \
        '<key>CFBundlePackageType</key><string>APPL</string>' \
        '<key>LSUIElement</key><true/>' \
        "<key>CFBundleShortVersionString</key><string>$VERSION</string>" \
        "<key>CFBundleVersion</key><string>$VERSION</string>" \
        '</dict></plist>' > "$mac_app/Contents/Info.plist"
    plutil -lint "$mac_app/Contents/Info.plist" >/dev/null
    # Finder metadata must not be included in an application bundle: codesign
    # treats extended attributes as unsigned bundle content.
    if command -v xattr >/dev/null 2>&1; then
        xattr -cr "$mac_app"
    fi
    if command -v codesign >/dev/null 2>&1; then
        codesign --force --sign - "$mac_app" >/dev/null
        codesign --verify --verbose "$mac_app" >/dev/null
    fi
    mac_package="$icon_work/ConsolePi Plus Discovery"
    mkdir -p "$mac_package"
    cp -R "$mac_app" "$mac_package/ConsolePi Plus Discovery.app"
    printf '%s\n' \
        '#!/bin/bash' \
        'set -euo pipefail' \
        '' \
        'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"' \
        'APP="$SCRIPT_DIR/ConsolePi Plus Discovery.app"' \
        '' \
        'if [[ ! -d "$APP" ]]; then' \
        '    echo "Nenalezena aplikace: $APP" >&2' \
        '    exit 1' \
        'fi' \
        '' \
        '# Týká se výhradně přibalené aplikace v tomto adresáři.' \
        'xattr -dr com.apple.quarantine "$APP"' \
        'open "$APP"' \
        > "$mac_package/Spustit ConsolePi Plus Discovery.command"
    chmod 0755 "$mac_package/Spustit ConsolePi Plus Discovery.command"
    if ! command -v zip >/dev/null 2>&1; then
        echo "zip is required to build the macOS desktop package" >&2
        exit 1
    fi
    # Start from a new archive.  COPYFILE_DISABLE and -X keep AppleDouble
    # files out of the ZIP; those files would invalidate the ad-hoc signature.
    rm -f "$OUTPUT/ConsolePi-Plus-Discovery-macOS-universal.zip"
    (
        cd "$icon_work"
        COPYFILE_DISABLE=1 zip -X -q -r "$OUTPUT/ConsolePi-Plus-Discovery-macOS-universal.zip" \
            'ConsolePi Plus Discovery'
    )
fi

# Desktop packages are GUI-first: double-clicking opens the local discovery
# page in the default browser.  Keep the architecture-specific command-line
# binaries above as well, for --shell and automation use.
windows_gui="$OUTPUT/ConsolePi-Plus-Discovery.exe"
printf 'Building %s\n' "$(basename "$windows_gui")"
(
    cd "$SOURCE"
    GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath \
        -buildvcs=false -ldflags='-s -w -H=windowsgui' -o "$windows_gui" .
)

if command -v zip >/dev/null 2>&1; then
    windows_work=$(mktemp -d "$OUTPUT/.consolepi-discover-windows.XXXXXX")
    windows_package="$windows_work/ConsolePi Plus Discovery"
    mkdir -p "$windows_package"
    cp "$windows_gui" "$windows_package/ConsolePi Plus Discovery.exe"
    cp "$OUTPUT/ConsolePi-Plus-Discovery.ico" "$windows_package/ConsolePi Plus Discovery.ico"
    printf '%s\r\n' \
        '@echo off' \
        'setlocal' \
        'start "" "%~dp0ConsolePi Plus Discovery.exe"' \
        > "$windows_package/Spustit ConsolePi Plus Discovery.cmd"
    (
        cd "$windows_work"
        rm -f "$OUTPUT/ConsolePi-Plus-Discovery-Windows-x64.zip"
        zip -q -r "$OUTPUT/ConsolePi-Plus-Discovery-Windows-x64.zip" 'ConsolePi Plus Discovery'
    )
    rm -rf "$windows_work"
fi

if command -v shasum >/dev/null 2>&1; then
    (
        cd "$OUTPUT"
        shasum -a 256 \
            consolepi-discover-darwin-amd64 \
            consolepi-discover-darwin-arm64 \
            consolepi-discover-linux-amd64 \
            consolepi-discover-linux-arm64 \
            consolepi-discover-windows-amd64.exe \
            ConsolePi-Plus-Discovery.exe \
            ConsolePi-Plus-Discovery.ico \
            ConsolePi-Plus-Discovery-macOS-universal.zip \
            ConsolePi-Plus-Discovery-Windows-x64.zip \
            > "consolepi-discover-v${VERSION}.sha256"
    )
fi
