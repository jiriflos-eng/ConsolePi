#!/bin/sh
# Create a portable ConsolePi clean-install archive without credentials.
set -eu

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# BSD tar on macOS otherwise writes Finder metadata (LIBARCHIVE.xattr.*) into
# the archive.  GNU tar simply ignores this environment variable.
COPYFILE_DISABLE=1
export COPYFILE_DISABLE

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(tr -d '[:space:]' <"$ROOT/VERSION")
OUTPUT_DIR=${1:-"$ROOT/dist"}
NAME="ConsolePi-${VERSION}-install"
ARCHIVE="$OUTPUT_DIR/${NAME}.tar.gz"
CHECKSUM="$ARCHIVE.sha256"

[ -n "$VERSION" ] || { printf '%s\n' 'Chybí VERSION.' >&2; exit 1; }
[ ! -e "$ARCHIVE" ] || { printf 'Výstup již existuje: %s\n' "$ARCHIVE" >&2; exit 1; }

CONSOLEPI_SKIP_ARCHIVE_TEST=1 "$ROOT/install.sh" --check-only

mkdir -p "$OUTPUT_DIR"
STAGING=$(mktemp -d "${TMPDIR:-/tmp}/consolepi-install.XXXXXX")
cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT HUP INT TERM

tar --no-xattrs -C "$ROOT" \
    --exclude='./.git' \
    --exclude='./authorized_keys' \
    --exclude='./release-signing-private.pem' \
    --exclude='./release-signing-private.pem.pub' \
    --exclude='./releases' \
    --exclude='./dist' \
    --exclude='./__pycache__' \
    --exclude='./.DS_Store' \
    --exclude='*/.DS_Store' \
    --exclude='./._*' \
    --exclude='*/._*' \
    -cf - . | tar -C "$STAGING" -xf -

# Defence in depth: a bundle must never contain keys from this workstation.
rm -f "$STAGING/authorized_keys" \
    "$STAGING/release-signing-private.pem" \
    "$STAGING/release-signing-private.pem.pub"

# Do not carry Finder metadata from the build workstation into Linux.
find "$STAGING" \( -name '.DS_Store' -o -name '._*' \) -type f -delete
if command -v xattr >/dev/null 2>&1; then
    xattr -cr "$STAGING"
fi

tar --no-xattrs -C "$STAGING" -czf "$ARCHIVE" .
if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$ARCHIVE" >"$CHECKSUM"
else
    sha256sum "$ARCHIVE" >"$CHECKSUM"
fi

printf 'Vytvořeno: %s\nKontrolní součet: %s\n' "$ARCHIVE" "$CHECKSUM"
