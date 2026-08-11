#!/usr/bin/python3
import base64
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from io import BytesIO
from functools import wraps
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

APP = Flask(__name__)
APP.config.update(
    SECRET_KEY=Path("/etc/consolepi/web.secret").read_text().strip(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=True,
    SESSION_PERMANENT=False,
    SESSION_REFRESH_EACH_REQUEST=False,
)

PORTS_FILE = Path("/etc/consolepi/ports.conf")
SERIAL_FILE = Path("/etc/consolepi/serial.conf")
AUTH_FILE = Path("/etc/consolepi/web.auth")
LABELS_FILE = Path("/etc/consolepi/labels.json")
IDENTITY_FILE = Path("/etc/consolepi/identity.json")
VERSION_FILE = Path("/usr/share/consolepi/VERSION")
CPU_SAMPLE = None
MAINTENANCE = "/usr/local/sbin/consolepi-maintenance"
RELEASE = "/usr/local/sbin/consolepi-release"
RELEASE_RUNNER = "/usr/local/sbin/consolepi-release-runner"
RELEASE_UPLOAD_DIR = Path("/var/lib/consolepi-web/release-uploads")
RELEASE_MAX_BYTES = 48 * 1024 * 1024
RELEASE_FILE_RE = re.compile(r"^[a-f0-9]{32}\.cpiupdate$")
SNMP_MIB_FILE = Path("/usr/share/snmp/mibs/CONSOLEPI-MIB.txt")


def command(*args, input_text=None, timeout=15):
    return subprocess.run(
        args,
        check=False,
        text=True,
        input=input_text,
        capture_output=True,
        timeout=timeout,
    )


def maintenance(group, action, values=None, timeout=30):
    return command(
        "sudo", MAINTENANCE, group, action,
        input_text=json.dumps(values or {}),
        timeout=timeout,
    )


def maintenance_status(group):
    result = maintenance(group, "status")
    return json.loads(result.stdout) if result.returncode == 0 else {
        "error": result.stderr.strip() or "Stav není dostupný."
    }


def release_update_status():
    result = command("sudo", RELEASE_RUNNER, "status")
    try:
        status = json.loads(result.stdout)
        if status.get("status") == "rebooting":
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(status["updated_at"])).total_seconds()
            except (KeyError, TypeError, ValueError):
                elapsed = 0
            if elapsed > 20:
                return {"status": "completed", "message": "Aktualizace byla dokončena a ConsolePi je znovu dostupné."}
        return status
    except json.JSONDecodeError:
        return {"status": "failed", "message": result.stderr.strip() or "Stav instalace není dostupný."}


def release_candidate():
    filename = str(session.get("release_candidate", ""))
    if not RELEASE_FILE_RE.fullmatch(filename):
        return None
    path = RELEASE_UPLOAD_DIR / filename
    info_path = path.with_suffix(".json")
    if not path.is_file() or not info_path.is_file():
        session.pop("release_candidate", None)
        return None
    try:
        info = json.loads(info_path.read_text())
    except (OSError, json.JSONDecodeError):
        session.pop("release_candidate", None)
        return None
    if not isinstance(info, dict):
        session.pop("release_candidate", None)
        return None
    return info


def firstboot_status():
    result = maintenance("firstboot", "status")
    if result.returncode:
        return {"pending": False, "error": result.stderr.strip()}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"pending": False, "error": "Neplatný stav prvního spuštění."}


def setup_csrf_valid():
    return secrets.compare_digest(
        session.get("setup_csrf", ""), request.form.get("csrf", "")
    )


@APP.after_request
def prevent_authenticated_page_caching(response):
    """Do not let a browser restore an authenticated page from its cache."""
    if session.get("authenticated"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@APP.before_request
def firstboot_gate():
    if request.path.startswith("/static/"):
        return None
    if request.endpoint in {
        "setup", "setup_storage_expand", "setup_admin_key_generate", "login"
    }:
        return None
    if firstboot_status().get("pending"):
        return redirect(url_for("setup"))
    return None


def authenticated(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def csrf_valid():
    return secrets.compare_digest(
        session.get("csrf", ""), request.form.get("csrf", "")
    )


def brand_identity():
    identity = {"display_name": "ConsolePi"}
    try:
        identity.update(json.loads(IDENTITY_FILE.read_text()))
    except (OSError, json.JSONDecodeError):
        pass
    identity["display_name"] = str(
        identity.get("display_name") or "ConsolePi"
    ).strip()
    try:
        identity["version"] = VERSION_FILE.read_text().strip()
    except OSError:
        identity["version"] = "–"
    return identity


@APP.context_processor
def inject_brand_identity():
    # The navigation is shared by all authenticated pages. Supplying the
    # cached APT state here lets it advertise pending updates without an APT
    # query while rendering a page.
    return {
        "brand_identity": brand_identity(),
        "header_updates": update_status(),
    }


def load_ports():
    rows = []
    try:
        labels = json.loads(LABELS_FILE.read_text() or "{}")
    except (OSError, json.JSONDecodeError):
        labels = {}
    host_ip = network_status().get("address", "raspberrypi")
    serial = load_serial_settings()
    for line in PORTS_FILE.read_text().splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        port, name, device = line.split("|", 2)
        target = os.path.realpath(device)
        connected = os.path.exists(device)
        label = str(labels.get(port, "")).strip()
        busy = connected and command(
            "lslocks", "-n", "-o", "PATH"
        ).stdout.find(f"/run/lock/consolepi/{name}.lock") >= 0
        rows.append(
            {
                "port": port,
                "name": name,
                # Popisek má smysl jen pro právě připojený kabel.  Po jeho
                # odpojení se z bezpečnostních i provozních důvodů vrátíme k
                # neutrálnímu názvu portu (KONZOLE-x).
                "display_name": label if connected and label else friendly_cable_name(name),
                "device": device,
                "target": target if connected else "",
                "connected": connected,
                "busy": busy,
                "command": f"ssh -tt -p {port} console@{host_ip}",
                "serial": serial.get(port, default_serial(port)),
                "label": label,
                "hardware_description": hardware_description(
                    device, target if connected else ""
                ),
            }
        )
        rows[-1]["serial_summary"] = format_serial(rows[-1]["serial"])
    return rows


def unassigned_usb_cables():
    """USB adapters present on the Pi but not yet mapped to an SSH port."""
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "ports", "discover"
    )
    if result.returncode:
        APP.logger.warning("USB discovery failed: %s", result.stderr.strip())
        return []
    try:
        devices = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    rows = []
    for device in devices:
        if not isinstance(device, str) or not device.startswith("/dev/serial/by-id/"):
            continue
        rows.append(
            {
                "device": device,
                "stable_id": Path(device).name,
                "target": os.path.realpath(device),
                "hardware_description": hardware_description(
                    device, os.path.realpath(device)
                ),
            }
        )
    return rows


def friendly_cable_name(name):
    match = re.fullmatch(r"RS232-USB-(\d+)", name, re.IGNORECASE)
    return f"USB to RS232 kabel {match.group(1)}" if match else name


def hardware_description(device, target=""):
    if "/unassigned-" in device:
        return "USB konzolový kabel zatím není přiřazen"
    properties = {}
    if target:
        result = command(
            "udevadm", "info", "--query=property", f"--name={target}"
        )
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                properties[key] = value
    vendor = (
        properties.get("ID_VENDOR_FROM_DATABASE")
        or properties.get("ID_VENDOR")
        or ""
    ).replace("_", " ")
    model = (
        properties.get("ID_MODEL_FROM_DATABASE")
        or properties.get("ID_MODEL")
        or ""
    ).replace("_", " ")
    serial = properties.get("ID_SERIAL_SHORT", "")
    driver = properties.get("ID_USB_DRIVER", "")

    if not model or not serial:
        stable_id = Path(device).name
        match = re.match(r"usb-([^-]+?)(?:-if\d+)?-port\d+$", stable_id)
        identity = match.group(1) if match else stable_id.removeprefix("usb-")
        parts = identity.split("_")
        if not vendor and parts:
            vendor = parts[0]
        if not serial and len(parts) >= 2:
            serial = parts[-1]
        if not model and len(parts) >= 3:
            model = " ".join(parts[1:-1])

    details = []
    if vendor:
        details.append(vendor)
    if model and model.lower() != vendor.lower():
        details.append(model)
    if serial:
        details.append(f"S/N {serial}")
    if driver:
        details.append(f"ovladač {driver}")
    return " · ".join(details) or "USB sériový konzolový adaptér"


def default_serial(port):
    return {
        "port": str(port),
        "baud": "9600",
        "databits": "8",
        "parity": "none",
        "stopbits": "1",
        "flow": "none",
        "local_echo": "no",
    }


def load_serial_settings():
    settings = {}
    for line in SERIAL_FILE.read_text().splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        port, baud, databits, parity, stopbits, flow, local_echo = line.split("|")
        settings[port] = {
            "port": port,
            "baud": baud,
            "databits": databits,
            "parity": parity,
            "stopbits": stopbits,
            "flow": flow,
            "local_echo": local_echo,
        }
    return settings


def format_serial(setting):
    parity = {"none": "N", "even": "E", "odd": "O"}[setting["parity"]]
    flow = {"none": "bez flow", "hard": "RTS/CTS", "soft": "XON/XOFF"}[
        setting["flow"]
    ]
    echo = "echo" if setting["local_echo"] == "yes" else "bez echo"
    return (
        f'{setting["baud"]} · {setting["databits"]}{parity}'
        f'{setting["stopbits"]} · {flow} · {echo}'
    )


def network_status():
    result = command(
        "nmcli",
        "-t",
        "-f",
        "GENERAL.CONNECTION,GENERAL.DEVICE,GENERAL.STATE,GENERAL.HWADDR,"
        "GENERAL.MTU,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS",
        "device",
        "show",
        "eth0",
    )
    values = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(":")
        values[key] = value.replace("\\:", ":")
    address = values.get("IP4.ADDRESS[1]", "")
    ip, _, prefix = address.partition("/")
    connection = values.get("GENERAL.CONNECTION", "")
    method = command(
        "nmcli", "-g", "ipv4.method", "connection", "show", connection
    ).stdout.strip()
    state = values.get("GENERAL.STATE", "")
    return {
        "connection": connection,
        "device": values.get("GENERAL.DEVICE", "eth0"),
        "state": state,
        "connected": state.startswith("100"),
        "mac": values.get("GENERAL.HWADDR", ""),
        "mtu": values.get("GENERAL.MTU", ""),
        "address": ip,
        "prefix": prefix or "24",
        "gateway": values.get("IP4.GATEWAY", ""),
        "dns": values.get("IP4.DNS[1]", ""),
        "mode": "dhcp" if method == "auto" else "static",
    }


def access_sources_status():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "access", "status"
    )
    if result.returncode:
        APP.logger.error("Access-source status failed: %s", result.stderr.strip())
        return {"local_network": "Nedostupná", "sources": [], "open_access": False}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        APP.logger.error("Access-source status returned invalid JSON")
        return {"local_network": "Nedostupná", "sources": [], "open_access": False}


def proxy_status():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "proxy", "status"
    )
    if result.returncode:
        return {
            "enabled": False, "scheme": "http", "host": "", "port": 8080,
            "username": "", "password_set": False,
            "no_proxy": "localhost,127.0.0.1,::1",
        }
    return json.loads(result.stdout)


def discovery_status():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "discovery", "status"
    )
    if result.returncode:
        return {"lldp": False, "cdp": False, "active": False, "neighbors": [], "error": result.stderr.strip()}
    return json.loads(result.stdout)


def snmp_status():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "snmp", "status"
    )
    if result.returncode:
        return {"enabled": False, "username": "", "installed": False, "active": False,
                "mib_available": False, "port": 161, "oid_root": "1.3.6.1.4.1.55555.1"}
    return json.loads(result.stdout)


def server_fingerprint():
    result = command(
        "ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub", "-E", "sha256"
    )
    parts = result.stdout.split()
    return parts[1] if len(parts) > 1 else "Fingerprint není dostupný"


def access_keys():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "keys", "list"
    )
    if result.returncode:
        APP.logger.error(
            "Listing access keys failed (rc=%s): %s",
            result.returncode,
            result.stderr.strip(),
        )
        return []
    return json.loads(result.stdout)


def authentication_status():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "auth", "status"
    )
    if result.returncode:
        APP.logger.error("RADIUS status failed: %s", result.stderr.strip())
        return {
            "mode": "local_key",
            "local_password_set": False,
            "primary_host": "",
            "primary_port": 1812,
            "primary_secret_set": False,
            "secondary_host": "",
            "secondary_port": 1812,
            "secondary_secret_set": False,
            "timeout": 3,
            "retries": 1,
        }
    return json.loads(result.stdout)


def logging_status():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "logs", "status"
    )
    if result.returncode:
        APP.logger.error("Logging status failed: %s", result.stderr.strip())
        return {
            "enabled": False,
            "mode": "events",
            "max_total_mb": 256,
            "max_session_mb": 25,
            "min_free_mb": 512,
            "retention_days": 30,
            "usage_bytes": 0,
            "free_bytes": 0,
            "files": 0,
            "event_log_exists": False,
        }
    data = json.loads(result.stdout)
    data["usage"] = human_bytes(data["usage_bytes"])
    data["free"] = human_bytes(data["free_bytes"])
    return data


def log_records():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "logs", "list"
    )
    if result.returncode:
        APP.logger.error("Log listing failed: %s", result.stderr.strip())
        return []
    records = json.loads(result.stdout)
    for record in records:
        record["size_human"] = human_bytes(record["size"])
        record["modified_human"] = datetime.fromtimestamp(
            record["modified"]
        ).strftime("%d.%m.%Y %H:%M:%S")
    return records


def update_status():
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "updates", "status"
    )
    if result.returncode:
        return {
            "status": "unknown",
            "checked_at": "",
            "updates": 0,
            "packages": [],
            "error": result.stderr.strip(),
            "reboot_required": False,
        }
    data = json.loads(result.stdout)
    checked = data.get("checked_at", "")
    data["checked_human"] = (
        checked.replace("T", " ").replace("Z", " UTC") if checked else "Dosud neprovedena"
    )
    return data


def human_bytes(value):
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024


def cpu_percent():
    global CPU_SAMPLE
    fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    total = sum(fields)
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    previous = CPU_SAMPLE
    CPU_SAMPLE = (total, idle)
    if not previous or total <= previous[0]:
        return None
    total_delta = total - previous[0]
    idle_delta = idle - previous[1]
    return round(max(0, min(100, 100 * (total_delta - idle_delta) / total_delta)), 1)


def system_status():
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, value = line.partition(":")
        meminfo[key] = int(value.strip().split()[0]) * 1024
    memory_total = meminfo.get("MemTotal", 0)
    memory_available = meminfo.get("MemAvailable", 0)
    memory_used = max(0, memory_total - memory_available)
    disk = shutil.disk_usage("/")
    uptime_seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    load = os.getloadavg()
    cores = os.cpu_count() or 1
    temperature_path = Path("/sys/class/thermal/thermal_zone0/temp")
    temperature = (
        round(int(temperature_path.read_text().strip()) / 1000, 1)
        if temperature_path.exists()
        else None
    )
    os_release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        key, _, value = line.partition("=")
        os_release[key] = value.strip().strip('"')
    model_path = Path("/proc/device-tree/model")
    services = {}
    for service in (
        "ssh", "nginx", "consolepi-web", "consolepi-port-monitor", "nftables", "snmpd"
    ):
        services[service] = (
            command("systemctl", "is-active", service).stdout.strip() == "active"
        )
    used_disk = disk.total - disk.free
    return {
        "cpu_percent": cpu_percent(),
        "cpu_cores": cores,
        "load_1": round(load[0], 2),
        "load_5": round(load[1], 2),
        "load_15": round(load[2], 2),
        "load_percent": round(min(100, load[0] / cores * 100), 1),
        "temperature": temperature,
        "memory_used": human_bytes(memory_used),
        "memory_total": human_bytes(memory_total),
        "memory_percent": round(memory_used / memory_total * 100, 1) if memory_total else 0,
        "disk_used": human_bytes(used_disk),
        "disk_free": human_bytes(disk.free),
        "disk_total": human_bytes(disk.total),
        "disk_percent": round(used_disk / disk.total * 100, 1) if disk.total else 0,
        "uptime": f"{days} d {hours} h {minutes} min" if days else f"{hours} h {minutes} min",
        "model": model_path.read_text().rstrip("\x00") if model_path.exists() else "Raspberry Pi",
        "os": os_release.get("PRETTY_NAME", "Raspberry Pi OS"),
        "kernel": platform.release(),
        "hostname": platform.node(),
        "services": services,
    }


@APP.route("/login", methods=["GET", "POST"])
def login():
    if firstboot_status().get("pending"):
        return redirect(url_for("setup"))
    if request.method == "POST":
        expected = AUTH_FILE.read_text().strip()
        if check_password_hash(expected, request.form.get("password", "")):
            session.clear()
            session.permanent = False
            session["authenticated"] = True
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin_dashboard"))
        flash("Nesprávné heslo.", "error")
    return render_template("login.html")


@APP.route("/setup", methods=["GET", "POST"])
def setup():
    state = firstboot_status()
    generic_firstboot = state.get("reason") == "generic_image"
    if request.method == "POST":
        if not state.get("pending"):
            return redirect(url_for("login"))
        if not setup_csrf_valid():
            return "Neplatný CSRF token.", 403
        password = request.form.get("web_password", "")
        confirmation = request.form.get("web_password_confirmation", "")
        if password != confirmation:
            flash("Hesla webové administrace se neshodují.", "error")
        elif not 10 <= len(password) <= 128:
            flash("Webové heslo musí mít 10 až 128 znaků.", "error")
        else:
            key_mode = request.form.get("admin_key_mode", "generate")
            public_key = request.form.get("admin_public_key", "").strip()
            if key_mode not in {"keep", "existing", "generate"}:
                flash("Zvolte způsob vytvoření administrativního SSH přístupu.", "error")
                return redirect(url_for("setup"))
            if generic_firstboot and key_mode != "keep":
                flash(
                    "Při prvním spuštění generic image je z bezpečnostních důvodů "
                    "nutné ponechat SSH klíč vložený Raspberry Pi Imagerem.",
                    "error",
                )
                return redirect(url_for("setup"))
            if key_mode == "keep" and not state.get("admin_key_present"):
                flash("Stávající validní administrativní klíč není dostupný.", "error")
                return redirect(url_for("setup"))
            if key_mode == "existing" and not public_key:
                flash("Vložte veřejný SSH klíč nebo zvolte vytvoření nového klíče.", "error")
                return redirect(url_for("setup"))
            result = maintenance("firstboot", "configure", {
                "web_password_hash": generate_password_hash(password),
                "hostname": request.form.get("hostname", ""),
                "display_name": request.form.get("display_name", ""),
                "location": request.form.get("location", ""),
                "description": request.form.get("description", ""),
                "admin_public_key": public_key if key_mode == "existing" else "",
                "key_mode": key_mode,
            }, timeout=120)
            if result.returncode:
                flash(result.stderr.strip() or "Průvodce nelze dokončit.", "error")
            else:
                session.clear()
                session["setup_finished"] = True
                session["setup_csrf"] = secrets.token_urlsafe(32)
                session["setup_admin_key_pending"] = key_mode == "generate"
                return render_template(
                    "setup_complete.html",
                    storage=maintenance_status("storage"),
                    csrf=session["setup_csrf"],
                    admin_key_pending=session["setup_admin_key_pending"],
                )
    if not state.get("pending"):
        if session.get("setup_finished"):
            return render_template(
                "setup_complete.html",
                storage=maintenance_status("storage"),
                csrf=session.get("setup_csrf", ""),
                admin_key_pending=session.get("setup_admin_key_pending", False),
            )
        return redirect(url_for("login"))
    session.setdefault("setup_csrf", secrets.token_urlsafe(32))
    identity = brand_identity()
    return render_template(
        "setup.html",
        csrf=session["setup_csrf"],
        state=state,
        network=network_status(),
        identity=identity,
        hostname=command("hostname").stdout.strip(),
        generic_firstboot=generic_firstboot,
        admin_key_present=bool(state.get("admin_key_present")),
    )


@APP.post("/setup/storage-expand")
def setup_storage_expand():
    if not session.get("setup_finished"):
        return redirect(url_for("setup"))
    if not setup_csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("storage", "expand", {
        "confirmation": request.form.get("confirmation", ""),
    }, timeout=150)
    if result.returncode:
        flash(result.stderr.strip() or "Rozšíření úložiště selhalo.", "error")
    else:
        flash("Datový oddíl byl rozšířen na dostupnou kapacitu SD karty.", "success")
    return redirect(url_for("setup"))


@APP.post("/setup/admin-key/generate")
def setup_admin_key_generate():
    """Generate an administrator key once and return its private half directly."""
    if not session.get("setup_finished") or not session.get("setup_admin_key_pending"):
        return redirect(url_for("setup"))
    if not setup_csrf_valid():
        return "Neplatný CSRF token.", 403
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("ascii") + " consolepi-firstboot"
    result = maintenance("firstboot", "admin-key-install", {
        "public_key": public_key,
    })
    if result.returncode:
        flash(result.stderr.strip() or "Nelze uložit veřejný SSH klíč správce.", "error")
        return redirect(url_for("setup"))
    private_data = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    session["setup_admin_key_pending"] = False
    return send_file(
        BytesIO(private_data),
        as_attachment=True,
        download_name="consolepi-admin",
        mimetype="application/octet-stream",
    )


@APP.post("/logout")
@authenticated
def logout():
    if csrf_valid():
        session.clear()
    return redirect(url_for("index"))


@APP.get("/")
def index():
    return render_template(
        "public.html",
        identity=brand_identity(),
        network=network_status(),
        ports=load_ports(),
        system=system_status(),
    )


@APP.get("/admin")
@authenticated
def admin_dashboard():
    return render_template(
        "index.html",
        ports=load_ports(),
        unassigned_usb_cables=unassigned_usb_cables(),
        network=network_status(),
        access_sources=access_sources_status(),
        proxy=proxy_status(),
        discovery=discovery_status(),
        snmp=snmp_status(),
        storage=maintenance_status("storage"),
        auth=authentication_status(),
        csrf=session["csrf"],
        hostname=command("hostname").stdout.strip(),
    )


@APP.get("/help")
@authenticated
def help_page():
    return render_template(
        "help.html",
        network=network_status(),
        auth=authentication_status(),
        ports=load_ports(),
        csrf=session["csrf"],
        hostname=command("hostname").stdout.strip(),
        server_fingerprint=server_fingerprint(),
    )


@APP.get("/keys")
@authenticated
def keys_page():
    return redirect(url_for("authentication_page"))


@APP.route("/authentication", methods=["GET", "POST"])
@authenticated
def authentication_page():
    if request.method == "POST":
        if not csrf_valid():
            return "Neplatný CSRF token.", 403
        payload = {
            "mode": request.form.get("mode", ""),
            "local_password": request.form.get("local_password", ""),
            "local_password_confirmation": request.form.get(
                "local_password_confirmation", ""
            ),
            "primary_host": request.form.get("primary_host", ""),
            "primary_port": request.form.get("primary_port", "1812"),
            "primary_secret": request.form.get("primary_secret", ""),
            "secondary_host": request.form.get("secondary_host", ""),
            "secondary_port": request.form.get("secondary_port", "1812"),
            "secondary_secret": request.form.get("secondary_secret", ""),
            "secondary_enabled": request.form.get("secondary_enabled") == "yes",
            "timeout": request.form.get("timeout", "3"),
            "retries": request.form.get("retries", "1"),
        }
        result = command(
            "sudo",
            "/usr/local/sbin/consolepi-control",
            "auth",
            "configure",
            input_text=json.dumps(payload),
        )
        flash(
            (
                "Nastavení autentizace bylo uloženo a komunikace s RADIUSem ověřena."
                if result.returncode == 0 and payload["mode"] == "radius"
                else "Nastavení autentizace bylo bezpečně uloženo."
            )
            if result.returncode == 0
            else result.stderr.strip(),
            "success" if result.returncode == 0 else "error",
        )
        return redirect(url_for("authentication_page"))
    return render_template(
        "authentication.html",
        auth=authentication_status(),
        keys=access_keys(),
        csrf=session["csrf"],
        hostname=command("hostname").stdout.strip(),
        network=network_status(),
    )


@APP.get("/system")
@authenticated
def system_page():
    section = request.args.get("section", "overview")
    if section not in {"overview", "device", "security", "logs", "backup", "maintenance"}:
        section = "overview"
    audit = maintenance_status("audit")
    if check_password_hash(AUTH_FILE.read_text().strip(), "consolepi"):
        audit.setdefault("findings", []).insert(0, {
            "level": "error",
            "title": "Výchozí heslo webu",
            "detail": "Změňte výchozí heslo consolepi.",
        })
        audit["score"] = max(0, int(audit.get("score", 100)) - 25)
    return render_template(
        "system.html",
        system=system_status(),
        logging=logging_status(),
        updates=update_status(),
        time_info=maintenance_status("time"),
        storage=maintenance_status("storage"),
        identity=maintenance_status("identity"),
        tls=maintenance_status("tls"),
        audit=audit,
        system_section=section,
        release_candidate=release_candidate(),
        release_status=release_update_status(),
        csrf=session["csrf"],
        network=network_status(),
    )


@APP.post("/system/backup")
@authenticated
def system_backup():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("backup", "create", {
        "passphrase": request.form.get("passphrase", ""),
        "include_secrets": request.form.get("include_secrets") == "yes",
    }, timeout=60)
    if result.returncode:
        flash(result.stderr.strip() or "Zálohu se nepodařilo vytvořit.", "error")
        return redirect(url_for("system_page", section="backup"))
    data = json.loads(result.stdout)
    return send_file(
        BytesIO(base64.b64decode(data["content"])),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=data["filename"],
    )


@APP.post("/system/restore")
@authenticated
def system_restore():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    upload = request.files.get("backup")
    if not upload:
        flash("Vyberte soubor zálohy.", "error")
        return redirect(url_for("system_page", section="backup"))
    content = upload.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        flash("Soubor zálohy je příliš velký.", "error")
        return redirect(url_for("system_page", section="backup"))
    result = maintenance("backup", "restore", {
        "passphrase": request.form.get("passphrase", ""),
        "confirmation": request.form.get("confirmation", ""),
        "content": base64.b64encode(content).decode(),
    }, timeout=90)
    flash(
        "Konfigurace byla obnovena. Doporučen je restart ConsolePi."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="backup"))


@APP.post("/system/diagnostic")
@authenticated
def system_diagnostic():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("diagnostic", "create", timeout=60)
    if result.returncode:
        flash(result.stderr.strip() or "Diagnostiku nelze vytvořit.", "error")
        return redirect(url_for("system_page", section="backup"))
    data = json.loads(result.stdout)
    return send_file(
        BytesIO(base64.b64decode(data["content"])),
        mimetype="application/gzip",
        as_attachment=True,
        download_name=data["filename"],
    )


@APP.post("/system/time")
@authenticated
def system_time():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("time", "configure", {
        "timezone": request.form.get("timezone", ""),
        "servers": request.form.get("servers", ""),
    })
    flash(
        "Nastavení času a NTP bylo uloženo."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="device"))


@APP.post("/system/identity")
@authenticated
def system_identity():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("identity", "configure", {
        "hostname": request.form.get("hostname", ""),
        "display_name": request.form.get("display_name", ""),
        "location": request.form.get("location", ""),
        "description": request.form.get("description", ""),
    })
    flash(
        "Identita zařízení byla uložena."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="device"))


@APP.post("/system/storage/expand")
@authenticated
def system_storage_expand():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("storage", "expand", {
        "confirmation": request.form.get("confirmation", ""),
    }, timeout=150)
    flash(
        "Datový oddíl byl rozšířen na dostupnou kapacitu SD karty."
        if result.returncode == 0 else result.stderr.strip() or "Rozšíření úložiště selhalo.",
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="device"))


@APP.post("/system/tls/generate")
@authenticated
def system_tls_generate():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("tls", "generate", {
        "confirmation": request.form.get("confirmation", "")
    }, timeout=90)
    flash(
        "Byl vytvořen nový HTTPS certifikát."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="security"))


@APP.post("/system/tls/install")
@authenticated
def system_tls_install():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    certificate = request.files.get("certificate")
    private_key = request.files.get("private_key")
    if not certificate or not private_key:
        flash("Vyberte certifikát i privátní klíč.", "error")
        return redirect(url_for("system_page", section="security"))
    cert_data, key_data = certificate.read(1024 * 1024), private_key.read(1024 * 1024)
    result = maintenance("tls", "install", {
        "confirmation": request.form.get("confirmation", ""),
        "certificate": base64.b64encode(cert_data).decode(),
        "private_key": base64.b64encode(key_data).decode(),
    }, timeout=60)
    flash(
        "Vlastní HTTPS certifikát byl nainstalován."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="security"))


@APP.get("/system/tls/certificate")
@authenticated
def system_tls_certificate():
    return send_file(
        "/etc/consolepi/tls/consolepi.crt",
        mimetype="application/x-pem-file",
        as_attachment=True,
        download_name="consolepi-certificate.pem",
    )


@APP.post("/system/clone-rekey")
@authenticated
def system_clone_rekey():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = maintenance("clone", "rekey", {
        "confirmation": request.form.get("confirmation", "")
    }, timeout=90)
    flash(
        "SSH host klíče a HTTPS certifikát byly vytvořeny znovu."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="maintenance"))


@APP.post("/system/web-password")
@authenticated
def system_web_password():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirmation = request.form.get("new_password_confirmation", "")
    if not check_password_hash(AUTH_FILE.read_text().strip(), current):
        flash("Současné administrátorské heslo není správné.", "error")
    elif new != confirmation:
        flash("Nová hesla se neshodují.", "error")
    elif len(new) < 10 or len(new) > 128:
        flash("Nové heslo musí mít 10–128 znaků.", "error")
    elif secrets.compare_digest(current, new):
        flash("Nové heslo musí být odlišné od současného.", "error")
    else:
        result = command(
            "sudo",
            "/usr/local/sbin/consolepi-control",
            "web-password",
            "set",
            input_text=generate_password_hash(new),
        )
        if result.returncode:
            flash(
                result.stderr.strip() or "Heslo se nepodařilo změnit.",
                "error",
            )
        else:
            flash("Heslo webového administrátora bylo změněno.", "success")
    return redirect(url_for("system_page", section="security"))


@APP.post("/system/factory-reset")
@authenticated
def system_factory_reset():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    if request.form.get("confirmation", "") != "RESET":
        flash("Tovární reset vyžaduje přesné zadání textu RESET.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "factory",
        "reset",
        input_text="RESET\n",
        timeout=90,
    )
    if result.returncode:
        flash(
            result.stderr.strip() or "Tovární reset se nepodařilo dokončit.",
            "error",
        )
        return redirect(url_for("system_page", section="maintenance"))
    return render_template("factory_reset.html", **json.loads(result.stdout))


@APP.post("/system/logging")
@authenticated
def system_logging():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    payload = {
        "mode": request.form.get("mode", "events"),
        "max_total_mb": request.form.get("max_total_mb", ""),
        "max_session_mb": request.form.get("max_session_mb", ""),
        "min_free_mb": request.form.get("min_free_mb", ""),
        "retention_days": request.form.get("retention_days", ""),
    }
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "logs",
        "configure",
        input_text=json.dumps(payload),
    )
    flash(
        "Nastavení logování bylo uloženo."
        if result.returncode == 0
        else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="logs"))


@APP.post("/system/logs/clear")
@authenticated
def system_logs_clear():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    if request.form.get("confirmation", "") != "VYMAZAT":
        flash("Vymazání logů vyžaduje přesné zadání textu VYMAZAT.", "error")
        return redirect(url_for("system_page", section="logs"))
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "logs",
        "clear",
        input_text="VYMAZAT\n",
    )
    flash(
        "Logy byly vymazány."
        if result.returncode == 0
        else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page", section="logs"))


@APP.post("/system/updates/check")
@authenticated
def system_updates_check():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "updates", "check"
    )
    flash(
        "Kontrola aktualizací byla spuštěna na pozadí."
        if result.returncode == 0
        else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page"))


@APP.post("/system/updates/upgrade")
@authenticated
def system_updates_upgrade():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    if request.form.get("confirmation", "") != "AKTUALIZOVAT":
        flash(
            "Instalace aktualizací vyžaduje přesné zadání textu AKTUALIZOVAT.",
            "error",
        )
        return redirect(url_for("system_page"))
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "updates",
        "upgrade",
        input_text="AKTUALIZOVAT\n",
    )
    flash(
        "Instalace aktualizací byla spuštěna na pozadí."
        if result.returncode == 0
        else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("system_page"))


@APP.post("/system/release/upload")
@authenticated
def system_release_upload():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    upload = request.files.get("package")
    if not upload or not upload.filename.lower().endswith(".cpiupdate"):
        flash("Vyberte aktualizační soubor ConsolePi ve formátu .cpiupdate.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    content = upload.stream.read(RELEASE_MAX_BYTES + 1)
    if len(content) > RELEASE_MAX_BYTES:
        flash("Aktualizační balíček je příliš velký.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    RELEASE_UPLOAD_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.cpiupdate"
    package = RELEASE_UPLOAD_DIR / filename
    package.write_bytes(content)
    os.chmod(package, 0o600)
    result = command("sudo", RELEASE, "inspect", str(package), timeout=25)
    if result.returncode:
        package.unlink(missing_ok=True)
        flash(result.stderr.strip() or "Podpis aktualizačního balíčku nelze ověřit.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        package.unlink(missing_ok=True)
        flash("Aktualizační balíček vrátil neplatný stav.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    previous = str(session.get("release_candidate", ""))
    if RELEASE_FILE_RE.fullmatch(previous):
        previous_package = RELEASE_UPLOAD_DIR / previous
        previous_package.unlink(missing_ok=True)
        previous_package.with_suffix(".json").unlink(missing_ok=True)
    info_path = package.with_suffix(".json")
    temporary_info = info_path.with_suffix(".json.new")
    temporary_info.write_text(json.dumps(info, ensure_ascii=False) + "\n")
    os.chmod(temporary_info, 0o600)
    temporary_info.replace(info_path)
    session["release_candidate"] = filename
    flash(f"Balíček ConsolePi {info['version']} byl ověřen. Před instalací zkontrolujte novinky.", "success")
    return redirect(url_for("system_page", section="maintenance"))


@APP.post("/system/release/install")
@authenticated
def system_release_install():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    if request.form.get("confirmation", "") != "INSTALOVAT":
        flash("Instalace vyžaduje přesné zadání textu INSTALOVAT.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    filename = str(session.get("release_candidate", ""))
    if not RELEASE_FILE_RE.fullmatch(filename):
        flash("Nejdříve nahrajte a ověřte aktualizační balíček.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    package = RELEASE_UPLOAD_DIR / filename
    try:
        result = command("sudo", RELEASE_RUNNER, "start", str(package), timeout=8)
    except subprocess.TimeoutExpired:
        # The runner is detached, but keep the user on the progress screen even
        # if a future system is slow to acknowledge its launch.
        return render_template(
            "release_install.html",
            status={"status": "verifying", "message": "Připravuji instalaci aktualizace…"},
        )
    if result.returncode:
        flash(result.stderr.strip() or "Instalaci aktualizace se nepodařilo spustit.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    session.pop("release_candidate", None)
    package.with_suffix(".json").unlink(missing_ok=True)
    return render_template("release_install.html", status=release_update_status())


@APP.get("/api/release-update")
@authenticated
def api_release_update():
    return jsonify(release_update_status())


@APP.get("/system/logs")
@authenticated
def system_logs_page():
    return render_template(
        "logs.html",
        logs=log_records(),
        csrf=session["csrf"],
        network=network_status(),
    )


@APP.get("/system/logs/view")
@authenticated
def system_log_view():
    path = request.args.get("path", "")
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "logs",
        "read",
        input_text=json.dumps({"path": path}),
    )
    if result.returncode:
        flash(result.stderr.strip() or "Log nelze otevřít.", "error")
        return redirect(url_for("system_logs_page"))
    record = json.loads(result.stdout)
    record["size_human"] = human_bytes(record["size"])
    record["modified_human"] = datetime.fromtimestamp(
        record["modified"]
    ).strftime("%d.%m.%Y %H:%M:%S")
    return render_template(
        "log_view.html",
        log=record,
        csrf=session["csrf"],
        network=network_status(),
    )


@APP.get("/api/system")
@authenticated
def api_system():
    return jsonify(system_status())


@APP.get("/api/firewall-drops")
@authenticated
def api_firewall_drops():
    result = command("sudo", "/usr/local/sbin/consolepi-control", "firewall", "drops")
    if result.returncode:
        return jsonify({"error": result.stderr.strip() or "Firewallový log není dostupný."}), 500
    try:
        return jsonify(json.loads(result.stdout))
    except json.JSONDecodeError:
        return jsonify({"error": "Firewallový log má neplatný formát."}), 500


@APP.get("/api/updates")
@authenticated
def api_updates():
    return jsonify(update_status())


@APP.post("/system/power/<action>")
@authenticated
def system_power(action):
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    if action != "reboot":
        return "Nepovolená systémová akce.", 400
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "system", action
    )
    if result.returncode:
        flash(result.stderr.strip() or "Systémovou akci se nepodařilo naplánovat.", "error")
        return redirect(url_for("system_page", section="maintenance"))
    return render_template(
        "system_action.html",
        action=action,
        delay=json.loads(result.stdout).get("delay", 8),
    )


@APP.route("/serial/<port>", methods=["GET", "POST"])
@authenticated
def serial_page(port):
    ports = {row["port"]: row for row in load_ports()}
    if port not in ports:
        return "Neznámý konzolový port.", 404
    row = ports[port]
    if request.method == "POST":
        if not csrf_valid():
            return "Neplatný CSRF token.", 403
        if row["busy"]:
            flash("Konzole je obsazena; nastavení nyní nelze změnit.", "error")
            return redirect(url_for("serial_page", port=port))
        values = [
            request.form.get("baud", ""),
            request.form.get("databits", ""),
            request.form.get("parity", ""),
            request.form.get("stopbits", ""),
            request.form.get("flow", ""),
            request.form.get("local_echo", ""),
        ]
        result = command(
            "sudo",
            "/usr/local/sbin/consolepi-control",
            "serial",
            "set",
            port,
            *values,
        )
        flash(
            "Sériové parametry byly uloženy a použijí se při příštím připojení."
            if result.returncode == 0
            else result.stderr.strip(),
            "success" if result.returncode == 0 else "error",
        )
        return redirect(url_for("serial_page", port=port))
    return render_template(
        "serial.html",
        row=row,
        csrf=session["csrf"],
        hostname=command("hostname").stdout.strip(),
        network=network_status(),
    )


@APP.post("/ports/assign")
@authenticated
def port_assign():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    port = request.form.get("port", "")
    if port not in {row["port"] for row in load_ports()}:
        return "Neznámý konzolový port.", 404
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "ports", "assign",
        port, request.form.get("device", ""),
    )
    flash(
        f"USB kabel byl přiřazen na SSH port {port}."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard"))


@APP.post("/ports/<port>/unassign")
@authenticated
def port_unassign(port):
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "ports", "unassign", port
    )
    flash(
        f"Kabel byl z SSH portu {port} odebrán; lze jej znovu přiřadit v přehledu."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard"))


@APP.post("/serial/<port>/label")
@authenticated
def serial_label(port):
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    if port not in {row["port"] for row in load_ports()}:
        return "Neznámý konzolový port.", 404
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "label", "set", port,
        input_text=request.form.get("label", ""),
    )
    flash(
        "Popisek portu byl uložen."
        if result.returncode == 0 else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("serial_page", port=port))


@APP.post("/serial/<port>/reset")
@authenticated
def serial_reset(port):
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "serial",
        "reset",
        port,
    )
    flash(
        "Byl obnoven profil Cisco 9600 8N1 bez flow control."
        if result.returncode == 0
        else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("serial_page", port=port))


@APP.post("/keys/create")
@authenticated
def key_create():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    label = request.form.get("label", "").strip()
    passphrase = request.form.get("passphrase", "")
    confirmation = request.form.get("passphrase_confirmation", "")
    if not re.fullmatch(r"[A-Za-z0-9À-ž._ -]{2,50}", label):
        flash("Název klíče musí mít 2–50 běžných znaků.", "error")
        return redirect(url_for("keys_page"))
    if passphrase != confirmation:
        flash("Ochranné fráze se neshodují.", "error")
        return redirect(url_for("keys_page"))
    if passphrase and len(passphrase) < 8:
        flash("Ochranná fráze musí mít alespoň 8 znaků.", "error")
        return redirect(url_for("keys_page"))

    key = Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    private_data = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=encryption,
    )
    public_data = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-")[:40] or "access"
    public_line = f"{public_data} consolepi-web:{slug}"
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "keys", "add", public_line
    )
    if result.returncode:
        flash(result.stderr.strip() or "Klíč se nepodařilo přidat.", "error")
        return redirect(url_for("keys_page"))

    response = send_file(
        BytesIO(private_data),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f"consolepi-{slug}",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return response


@APP.post("/keys/delete")
@authenticated
def key_delete():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "keys",
        "delete",
        request.form.get("fingerprint", ""),
    )
    flash(
        "Přístupový klíč byl odebrán."
        if result.returncode == 0
        else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(
        url_for("authentication_page")
        if request.form.get("return_to") == "authentication"
        else url_for("keys_page")
    )


@APP.get("/api/status")
@authenticated
def api_status():
    ports = load_ports()
    return jsonify(
        {
            "ports": ports,
            "connected": sum(1 for row in ports if row["connected"]),
            "offline": sum(1 for row in ports if not row["connected"]),
            "unassigned_usb_cables": unassigned_usb_cables(),
        }
    )


@APP.get("/api/public-status")
def api_public_status():
    """Neprivilegovaný, živý stav pro veřejný přehled.

    Záměrně nevrací cesty k zařízením, stabilní USB ID ani konfiguraci.
    """
    ports = load_ports()
    return jsonify(
        {
            "ports": [
                {
                    "port": row["port"],
                    "display_name": row["display_name"],
                    "connected": row["connected"],
                    "busy": row["busy"],
                    "serial_summary": row["serial_summary"],
                }
                for row in ports
            ],
            "connected": sum(1 for row in ports if row["connected"]),
        }
    )


@APP.post("/network/apply")
@authenticated
def network_apply():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    mode = request.form.get("mode", "")
    args = ["sudo", "/usr/local/sbin/consolepi-control", "network", "apply", mode]
    if mode == "static":
        args.extend(
            [
                request.form.get("address", ""),
                request.form.get("prefix", ""),
                request.form.get("gateway", ""),
                request.form.get("dns", ""),
            ]
        )
    result = command(*args)
    if result.returncode:
        flash(result.stderr.strip() or "Změna sítě selhala.", "error")
        return redirect(url_for("admin_dashboard", tab="network"))
    data = json.loads(result.stdout)
    return render_template("network_pending.html", **data)


@APP.post("/network/confirm")
@authenticated
def network_confirm():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = command(
        "sudo",
        "/usr/local/sbin/consolepi-control",
        "network",
        "confirm",
        request.form.get("token", ""),
    )
    flash(
        "Nové síťové nastavení bylo potvrzeno."
        if result.returncode == 0
        else result.stderr.strip(),
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard", tab="network"))


@APP.post("/network/access-sources/add")
@authenticated
def network_access_source_add():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "access", "add",
        request.form.get("label", ""),
        request.form.get("network", ""),
        request.form.get("confirmation", ""),
    )
    flash(
        "Zdroj přístupu byl povolen."
        if result.returncode == 0
        else result.stderr.strip() or "Uložení zdroje přístupu selhalo.",
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard", tab="network"))


@APP.post("/network/access-sources/update")
@authenticated
def network_access_source_update():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    source_id = request.form.get("source_id", "")
    if request.form.get("operation") == "delete":
        result = command(
            "sudo", "/usr/local/sbin/consolepi-control", "access", "delete", source_id
        )
        success = "Zdroj přístupu byl odebrán."
    else:
        result = command(
            "sudo", "/usr/local/sbin/consolepi-control", "access", "update",
            source_id,
            request.form.get("label", ""),
            request.form.get("network", ""),
            request.form.get("confirmation", ""),
        )
        success = "Zdroj přístupu byl upraven."
    flash(
        success if result.returncode == 0 else result.stderr.strip() or "Úprava zdroje přístupu selhala.",
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard", tab="network"))


@APP.post("/network/proxy")
@authenticated
def network_proxy():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    payload = {
        "enabled": request.form.get("enabled") == "yes",
        "scheme": request.form.get("scheme", "http"),
        "host": request.form.get("host", ""),
        "port": request.form.get("port", "8080"),
        "username": request.form.get("username", ""),
        "password": request.form.get("password", ""),
        "keep_password": request.form.get("keep_password") == "yes",
        "no_proxy": request.form.get("no_proxy", ""),
    }
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "proxy", "configure",
        input_text=json.dumps(payload),
    )
    flash(
        "Nastavení proxy bylo uloženo a použije se při příští kontrole aktualizací."
        if result.returncode == 0
        else result.stderr.strip() or "Nastavení proxy selhalo.",
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard", tab="network"))


@APP.post("/network/discovery")
@authenticated
def network_discovery():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "discovery", "configure",
        input_text=json.dumps({
            "lldp": request.form.get("lldp") == "yes",
            "cdp": request.form.get("cdp") == "yes",
        }),
    )
    flash(
        "Nastavení CDP/LLDP bylo uloženo. Informace o sousedovi se objeví po přijetí první reklamy."
        if result.returncode == 0 else result.stderr.strip() or "Nastavení CDP/LLDP selhalo.",
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard", tab="network"))


@APP.post("/network/snmp")
@authenticated
def network_snmp():
    if not csrf_valid():
        return "Neplatný CSRF token.", 403
    enabled = request.form.get("enabled") == "yes"
    result = command(
        "sudo", "/usr/local/sbin/consolepi-control", "snmp", "configure",
        input_text=json.dumps({
            "enabled": enabled,
            "username": request.form.get("username", ""),
            "auth_password": request.form.get("auth_password", ""),
            "privacy_password": request.form.get("privacy_password", ""),
        }), timeout=35,
    )
    flash(
        "SNMPv3 je aktivní na UDP portu 161; přístup je omezen stejným seznamem povolených zdrojů jako ConsolePi."
        if result.returncode == 0 and enabled else
        "SNMPv3 byl vypnut a UDP port 161 byl odebrán z firewallu."
        if result.returncode == 0 else result.stderr.strip() or "Nastavení SNMPv3 selhalo.",
        "success" if result.returncode == 0 else "error",
    )
    return redirect(url_for("admin_dashboard", tab="network"))


@APP.get("/downloads/CONSOLEPI-MIB.txt")
@authenticated
def download_snmp_mib():
    if not SNMP_MIB_FILE.exists():
        return "MIB soubor zatím není nainstalován.", 404
    return send_file(SNMP_MIB_FILE, as_attachment=True, download_name="CONSOLEPI-MIB.txt", mimetype="text/plain")


if __name__ == "__main__":
    APP.run(host="127.0.0.1", port=8080)
