#!/usr/bin/env python3
"""Focused behaviour checks for the read-only ConsolePi SNMP exporter."""
from importlib.machinery import SourceFileLoader
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "usr/local/sbin/consolepi-snmp-pass-persist"
MODULE = SourceFileLoader("consolepi_snmp_pass_persist", str(EXPORTER)).load_module()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        ports = directory / "ports.conf"
        state = directory / "update-status.json"
        ports.write_text(
            "# SSH_PORT|DEVICE_NAME|SERIAL_DEVICE\n"
            "2201|KONZOLE-1|/dev/consolepi/unassigned-1\n"
            "2202|KONZOLE-2|/dev/null\n"
            "2203|KONZOLE-3|/missing/serial-adapter\n"
            "not-a-port|ignored|/dev/null\n"
        )
        state.write_text('{"updates": 4, "reboot_required": true}\n')
        MODULE.PORTS_CONFIG = ports
        MODULE.UPDATE_STATE = state

        check(MODULE.update_status() == (4, 1), "cached update status")
        check(
            MODULE.serial_ports()
            == [(2201, "KONZOLE-1", 1), (2202, "KONZOLE-2", 3), (2203, "KONZOLE-3", 2)],
            "serial console states",
        )

        state.write_text("not json\n")
        check(MODULE.update_status() == (0, 0), "invalid update state fails safely")

    print("SNMP_BEHAVIOR=PASS")


if __name__ == "__main__":
    main()
