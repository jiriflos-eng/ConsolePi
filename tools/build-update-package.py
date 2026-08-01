#!/usr/bin/env python3
"""Build a signed, offline ConsolePi update package.

The private Ed25519 key is deliberately supplied from outside the package.
Only the matching public key is installed on ConsolePi.
"""
import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Build artefacts must never become part of an update payload.  In particular,
# including dist/ would needlessly inflate the upload and could exceed nginx's
# request-size limit on a Raspberry Pi.
EXCLUDED_PARTS = {".git", ".private", "__pycache__", "releases", "dist"}
EXCLUDED_NAMES = {
    ".DS_Store", "authorized_keys", "release-signing-private.pem", "release-signing-private.pem.pub",
}


def include(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return not any(part in EXCLUDED_PARTS for part in relative.parts) and path.name not in EXCLUDED_NAMES


def add_tree(archive: tarfile.TarFile, root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if not include(path, root) or path.is_dir():
            continue
        archive.add(path, arcname=str(path.relative_to(root)), recursive=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Vytvoří podepsaný aktualizační balíček ConsolePi.")
    parser.add_argument("--private-key", type=Path, required=True, help="Ed25519 PEM pouze na administračním počítači")
    parser.add_argument("--output", type=Path, help="Výstupní .cpiupdate soubor")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text().strip()
    if not version or not all(part.isdigit() for part in version.split(".")):
        raise SystemExit("VERSION musí obsahovat semantickou verzi, například 1.2.3.")
    if not args.private_key.is_file():
        raise SystemExit("Podepisovací klíč neexistuje.")

    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        add_tree(archive, root)
    payload_bytes = payload.getvalue()
    manifest = {
        "format": "consolepi-update-1",
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    with tempfile.TemporaryDirectory(prefix="consolepi-sign-") as temporary:
        manifest_path = Path(temporary) / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        signed = subprocess.run(
            ["ssh-keygen", "-q", "-Y", "sign", "-f", str(args.private_key), "-n", "consolepi-release", str(manifest_path)],
            text=True, capture_output=True, check=False,
        )
        if signed.returncode:
            raise SystemExit(signed.stderr.strip() or "Podpis aktualizace selhal.")
        signature = Path(str(manifest_path) + ".sig").read_bytes()
    output = args.output or root.parent / f"ConsolePi-{version}.cpiupdate"
    with tarfile.open(output, mode="w:gz") as archive:
        for name, content in (("manifest.json", manifest_bytes), ("signature.sshsig", signature), ("payload.tar.gz", payload_bytes)):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    print(output)


if __name__ == "__main__":
    main()
