#!/bin/sh
# Build standalone ConsolePi discovery clients for administrator workstations.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE="$ROOT/tools/consolepi-discover"
OUTPUT=${1:-"$ROOT/dist/consolepi-discover"}

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
