#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT=$(mktemp -d "${TMPDIR:-/tmp}/consolepi-archive-test.XXXXXX")
trap 'rm -rf "$OUTPUT"' EXIT HUP INT TERM
CONSOLEPI_SKIP_ARCHIVE_TEST=1 "$ROOT/tools/build-install-bundle.sh" "$OUTPUT" >/dev/null
archive=$(find "$OUTPUT" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)
[ -n "$archive" ]
tar -tzf "$archive" >"$OUTPUT/contents"
! grep -Eq '(^|/)(authorized_keys|release-signing-private\.pem|release-signing-private\.pem\.pub)$' "$OUTPUT/contents"
! grep -Eq '^\./etc/systemd/system/(ssh|nginx|consolepi-web)\.service\.d/consolepi-generic-image\.conf$' "$OUTPUT/contents"
mkdir "$OUTPUT/extracted"
tar -xzf "$archive" -C "$OUTPUT/extracted"
! grep -R -E -l 'BEGIN (OPENSSH|RSA|EC|DSA) PRIVATE KEY' "$OUTPUT/extracted"
python3 - "$OUTPUT/extracted" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
assert json.loads((root / "etc/consolepi/radius-secrets.json").read_text()) == {"primary": "", "secondary": ""}
assert json.loads((root / "etc/consolepi/snmpv3-secrets.json").read_text()) == {"auth_password": "", "privacy_password": ""}
proxy = json.loads((root / "etc/consolepi/proxy.json").read_text())
assert not proxy["enabled"] and not proxy["username"] and not proxy["password"]
PY
printf '%s\n' 'OK: install archive credential scan'
