#!/usr/bin/env python3
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


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    module.STATE_DIR = root
    module.STATE = root / "network-rollback.json"
    module.NFTABLES = root / "nftables.conf"
    module.NFTABLES.write_text("table inet consolepi_filter {}\n")
    module.nm_get = lambda field: {
        "ipv4.method": "auto",
        "ipv4.addresses": "",
        "ipv4.gateway": "",
        "ipv4.dns": "",
    }[field]
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    module.run = fake_run
    module.active_network = lambda: ("192.0.2.20", "192.0.2.0/24")
    module.update_firewall = lambda network: calls.append(("update_firewall", network))

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        module.apply(["static", "192.0.2.20", "24", "192.0.2.1", "192.0.2.53"])
    response = json.loads(output.getvalue())
    assert response == {"address": "192.0.2.20", "mode": "static", "delay": 5}
    assert not any(call[:3] == ("nmcli", "connection", "modify") for call in calls)
    assert not any(call[:4] == ("nmcli", "connection", "up", module.CONNECTION) for call in calls)
    scheduled = [call for call in calls if call and call[0] == "systemd-run"]
    assert len(scheduled) == 1
    assert "--on-active=5s" in scheduled[0]
    assert scheduled[0][-3:-1] == ("network", "activate")

    state = json.loads(module.STATE.read_text())
    assert state["phase"] == "staged"
    assert state["candidate"] == {
        "mode": "static",
        "address": "192.0.2.20",
        "prefix": "24",
        "gateway": "192.0.2.1",
        "dns": "192.0.2.53",
    }
    try:
        module.confirm(state["token"])
    except ValueError as error:
        assert str(error) == "Síťová změna ještě není aktivní."
    else:
        raise AssertionError("Staged network change was confirmed")

    try:
        module.apply(["dhcp"])
    except ValueError as error:
        assert "předchozí síťovou změnu" in str(error)
    else:
        raise AssertionError("Parallel network change was accepted")

    calls.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        module.activate(state["token"])
    assert any(call[:3] == ("nmcli", "connection", "modify") for call in calls)
    assert any(call[:4] == ("nmcli", "connection", "up", module.CONNECTION) for call in calls)
    rollback = [call for call in calls if call and call[0] == "systemd-run"]
    assert len(rollback) == 1
    assert "--on-active=180" in rollback[0]
    active_state = json.loads(module.STATE.read_text())
    assert active_state["phase"] == "active"
    assert active_state["previous_address"] == "192.0.2.20"
    assert isinstance(active_state["rollback_deadline"], int)
    pending = module.pending_status()
    assert pending["active"] is True
    assert pending["previous_address"] == "192.0.2.20"
    assert 0 < pending["remaining_seconds"] <= 180

    module.STATE.unlink()
    assert module.pending_status() == {"active": False}

    attempts = iter([IndexError("not ready"), ValueError("not ready"), ("192.0.2.30", "192.0.2.0/24")])
    original_active_network = module.active_network
    original_monotonic = module.time.monotonic
    original_sleep = module.time.sleep

    def delayed_active_network():
        attempt = next(attempts)
        if isinstance(attempt, BaseException):
            raise attempt
        return attempt

    module.active_network = delayed_active_network
    module.time.monotonic = lambda: 0
    module.time.sleep = lambda _: None
    assert module.wait_for_active_network() == ("192.0.2.30", "192.0.2.0/24")
    module.active_network = original_active_network
    module.time.monotonic = original_monotonic
    module.time.sleep = original_sleep

print("OK: delayed network apply behavior")
