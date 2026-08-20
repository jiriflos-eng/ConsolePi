#!/bin/sh
# Create a reviewable public source archive from this local working tree.
set -eu

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
COPYFILE_DISABLE=1
export COPYFILE_DISABLE

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(tr -d '[:space:]' <"$ROOT/VERSION")
OUTPUT_DIR=${1:-"$ROOT/dist-public"}
ARCHIVE="$OUTPUT_DIR/ConsolePi-Plus-${VERSION}-source.tar.gz"
CHECKSUM="$ARCHIVE.sha256"

[ -n "$VERSION" ] || { printf '%s\n' 'VERSION is missing.' >&2; exit 1; }
[ ! -e "$ARCHIVE" ] || { printf 'Output already exists: %s\n' "$ARCHIVE" >&2; exit 1; }

mkdir -p "$OUTPUT_DIR"
STAGING=$(mktemp -d "${TMPDIR:-/tmp}/consolepi-public.XXXXXX")
cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT HUP INT TERM

tar -C "$ROOT" \
    --exclude='./.git' \
    --exclude='./authorized_keys' \
    --exclude='./release-signing-private.pem' \
    --exclude='./dist' \
    --exclude='./releases' \
    --exclude='./dist-public' \
    --exclude='./public-release' \
    --exclude='./*.cpiupdate' \
    --exclude='./*.img' \
    --exclude='./*.img.xz' \
    --exclude='./*.map' \
    --exclude='./.DS_Store' \
    --exclude='*/.DS_Store' \
    --exclude='./._*' \
    --exclude='*/._*' \
    --exclude='./__pycache__' \
    -cf - . | tar -C "$STAGING" -xf -

# Defence in depth; a public archive must not contain private local material.
rm -f "$STAGING/authorized_keys" "$STAGING/release-signing-private.pem"
find "$STAGING" \( -name '.DS_Store' -o -name '._*' \) -type f -delete

tar -C "$STAGING" -czf "$ARCHIVE" .
if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$ARCHIVE" >"$CHECKSUM"
else
    sha256sum "$ARCHIVE" >"$CHECKSUM"
fi

printf 'Public source archive: %s\nSHA-256: %s\n' "$ARCHIVE" "$CHECKSUM"
