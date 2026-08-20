#!/usr/bin/env python3
"""Behaviour checks for ConsolePi-managed APT repository configuration."""

import contextlib
import io
import json
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "usr/local/sbin/consolepi-control"
source = CONTROL.read_text().split("\ntry:\n    main()", 1)[0]
module = ModuleType("consolepi_control")
exec(compile(source, str(CONTROL), "exec"), module.__dict__)


official = {
    "mode": "official",
    "codename": "bookworm",
    "debian_uri": "http://deb.debian.org/debian",
    "security_uri": "http://security.debian.org/debian-security",
    "raspberrypi_uri": "http://archive.raspberrypi.com/debian",
}

assert module.validate_apt_uri("https://mirror.example.local/debian", "mirror") == "https://mirror.example.local/debian"
for unsafe in (
    "ftp://mirror.example.local/debian",
    "https://user:secret@mirror.example.local/debian",
    "https://mirror.example.local/debian?option=value",
    "https://mirror.example.local/debian\nSigned-By: /tmp/key",
    "https://mirror.example.local/../debian",
):
    try:
        module.validate_apt_uri(unsafe, "mirror")
    except ValueError:
        pass
    else:
        raise AssertionError(f"unsafe URI accepted: {unsafe!r}")

rendered = module.render_apt_sources(official)
assert set(rendered) == {"debian.sources", "raspi.sources"}
assert "Suites: bookworm bookworm-updates" in rendered["debian.sources"]
assert rendered["debian.sources"].count("Architectures: arm64\n") == 2
assert "Architectures: arm64\n" in rendered["raspi.sources"]
assert "Signed-By: /usr/share/keyrings/raspberrypi-archive-keyring.gpg" in rendered["raspi.sources"]

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    module.APT_SOURCE_PARTS = root / "etc/apt/sources.list.d"
    module.DEBIAN_SOURCES = module.APT_SOURCE_PARTS / "debian.sources"
    module.RASPI_SOURCES = module.APT_SOURCE_PARTS / "raspi.sources"
    module.APT_SOURCES_CONFIG = root / "etc/consolepi/apt-sources.json"
    module.APT_SOURCES_CONFIG.parent.mkdir(parents=True)
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    module.run = fake_run
    module.verify_apt_sources = lambda files: calls.append(("verify", files))
    with contextlib.redirect_stdout(io.StringIO()):
        module.apply_apt_sources(official, verify=True)
    assert calls[0][0] == "verify"
    assert module.DEBIAN_SOURCES.read_text() == rendered["debian.sources"]
    assert module.RASPI_SOURCES.read_text() == rendered["raspi.sources"]
    assert json.loads(module.APT_SOURCES_CONFIG.read_text()) == official
    assert module.DEBIAN_SOURCES.stat().st_mode & 0o777 == 0o644

    previous = module.DEBIAN_SOURCES.read_text()
    module.verify_apt_sources = lambda files: (_ for _ in ()).throw(ValueError("mirror unavailable"))
    changed = dict(official, mode="mirror", debian_uri="https://mirror.example/debian")
    try:
        module.apply_apt_sources(changed, verify=True)
    except ValueError:
        pass
    else:
        raise AssertionError("unverified mirror was applied")
    assert module.DEBIAN_SOURCES.read_text() == previous

    module.apt_sources_defaults = lambda: dict(official)
    module.run = fake_run
    with contextlib.redirect_stdout(io.StringIO()):
        module.apt_sources_reset()
    assert json.loads(module.APT_SOURCES_CONFIG.read_text())["mode"] == "official"

print("OK: APT repository source behavior")
