#!/usr/bin/python3
"""Fail-closed generic-image claim state and one-time credentials."""
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import time
from pathlib import Path

TOKEN_TTL = 600
SESSION_TTL = 600
KNOWN_GENERIC_STATES = {"pending", "claim_pending", "key_generation_pending", "complete"}


class ClaimError(ValueError):
    pass


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data if isinstance(data, bytes) else data.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_json(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ClaimError("Stav není JSON objekt.")
    return value


def firstboot_reason(firstboot_path):
    try:
        value = read_json(firstboot_path)
    except (OSError, json.JSONDecodeError, ClaimError):
        return "missing_state"
    return str(value.get("reason", ""))


def generic_state(firstboot_path, generic_path):
    """Return state; generic first boot treats every corrupt value as claim_required."""
    if firstboot_reason(firstboot_path) != "generic_image":
        return "standard"
    try:
        value = read_json(generic_path)
        state = value.get("state")
        if state not in KNOWN_GENERIC_STATES:
            raise ClaimError("Neznámý generic-image stav.")
        return state
    except (OSError, json.JSONDecodeError, ClaimError):
        return "claim_required"


def claim_required(firstboot_path, generic_path):
    return generic_state(firstboot_path, generic_path) not in {"standard", "complete"}


def write_generic_state(path, state):
    if state not in KNOWN_GENERIC_STATES:
        raise ClaimError("Neznámý generic-image stav.")
    atomic_write(path, json.dumps({"state": state}, separators=(",", ":")) + "\n")


def create_token(token_path, metadata_path, now=None):
    now = int(time.time() if now is None else now)
    token = secrets.token_urlsafe(32)
    atomic_write(token_path, token + "\n", 0o400)
    metadata = {
        "version": 1,
        "digest": hashlib.sha256(token.encode()).hexdigest(),
        "created_at": now,
        "expires_at": now + TOKEN_TTL,
        "used": False,
    }
    atomic_write(metadata_path, json.dumps(metadata, separators=(",", ":")) + "\n")
    return token


def session_path(session_dir, session_id):
    digest = hashlib.sha256(session_id.encode()).hexdigest()
    return Path(session_dir) / f"{digest}.json"


def consume_token(token, token_path, metadata_path, session_dir, now=None):
    now = int(time.time() if now is None else now)
    metadata_path = Path(metadata_path)
    lock_path = metadata_path.with_suffix(metadata_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            metadata = read_json(metadata_path)
        except (OSError, json.JSONDecodeError, ClaimError) as exc:
            raise ClaimError("Autorizační token není dostupný.") from exc
        required = {"digest", "created_at", "expires_at", "used", "version"}
        if set(metadata) != required or metadata["version"] != 1:
            raise ClaimError("Autorizační token má poškozený stav.")
        if metadata["used"]:
            raise ClaimError("Autorizační token už byl použit.")
        if not isinstance(metadata["expires_at"], int) or now > metadata["expires_at"]:
            raise ClaimError("Autorizační token vypršel.")
        digest = hashlib.sha256(str(token).encode()).hexdigest()
        if not hmac.compare_digest(metadata["digest"], digest):
            raise ClaimError("Autorizační token není platný.")
        metadata["used"] = True
        metadata["used_at"] = now
        # Replace the schema atomically before returning any authorization.
        atomic_write(metadata_path, json.dumps(metadata, separators=(",", ":")) + "\n")
        Path(token_path).unlink(missing_ok=True)
        Path(session_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(session_dir, 0o700)
        session_id = secrets.token_urlsafe(32)
        session = {"version": 1, "created_at": now, "expires_at": now + SESSION_TTL}
        atomic_write(session_path(session_dir, session_id), json.dumps(session, separators=(",", ":")) + "\n")
        return session_id


def validate_session(session_id, session_dir, now=None):
    now = int(time.time() if now is None else now)
    if not isinstance(session_id, str) or len(session_id) < 32:
        raise ClaimError("Provisioning session není platná.")
    try:
        value = read_json(session_path(session_dir, session_id))
    except (OSError, json.JSONDecodeError, ClaimError) as exc:
        raise ClaimError("Provisioning session není dostupná.") from exc
    if set(value) != {"version", "created_at", "expires_at"} or value["version"] != 1:
        raise ClaimError("Provisioning session má poškozený stav.")
    if not isinstance(value["expires_at"], int) or now > value["expires_at"]:
        raise ClaimError("Provisioning session vypršela.")
    return True


def consume_session(session_id, session_dir):
    session_path(session_dir, session_id).unlink(missing_ok=True)


def validate_authorized_key(path, expected_uid, expected_gid=None):
    path = Path(path)
    directory = path.parent
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        directory_fd = os.open(directory, flags)
    except OSError as exc:
        raise ClaimError("Adresář .ssh není bezpečný adresář.") from exc
    try:
        directory_stat = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ClaimError("Adresář .ssh není bezpečný adresář.")
        if (directory_stat.st_uid != expected_uid or
                (expected_gid is not None and directory_stat.st_gid != expected_gid) or
                stat.S_IMODE(directory_stat.st_mode) != 0o700):
            raise ClaimError("Adresář .ssh má nesprávného vlastníka nebo mód.")
        file_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW
        try:
            file_fd = os.open(path.name, file_flags, dir_fd=directory_fd)
        except OSError as exc:
            raise ClaimError("authorized_keys není bezpečný běžný soubor.") from exc
        with os.fdopen(file_fd, "r", encoding="utf-8") as stream:
            file_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise ClaimError("authorized_keys není bezpečný běžný soubor.")
            if (file_stat.st_uid != expected_uid or
                    (expected_gid is not None and file_stat.st_gid != expected_gid) or
                    stat.S_IMODE(file_stat.st_mode) != 0o600):
                raise ClaimError("authorized_keys má nesprávného vlastníka nebo mód.")
            if file_stat.st_nlink != 1:
                raise ClaimError("authorized_keys má neočekávaný počet hardlinků.")
            content = stream.read(16385)
            if len(content) > 16384:
                raise ClaimError("authorized_keys je neočekávaně velký.")
    finally:
        os.close(directory_fd)
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(lines) != 1:
        raise ClaimError("authorized_keys musí obsahovat právě jeden klíč.")
    fields = lines[0].split(maxsplit=2)
    if len(fields) not in {2, 3} or fields[0] != "ssh-ed25519":
        raise ClaimError("Povolen je pouze jeden neomezený klíč ssh-ed25519.")
    checked = subprocess.run(
        ["ssh-keygen", "-lf", "-"], input=lines[0] + "\n", text=True,
        capture_output=True, check=False,
    )
    if checked.returncode:
        raise ClaimError("Veřejný SSH klíč není platný.")
    return lines[0]


def validate_generic_access(state, passwd_text, shadow_text, home_path,
                            expected_uid=1000, expected_gid=1000):
    active_states = {"pending", "claim_pending", "key_generation_pending", "complete"}
    if state not in active_states:
        raise ClaimError("Stav neumožňuje generic přístup.")
    accounts = [line.split(":") for line in passwd_text.splitlines() if line]
    matches = [fields for fields in accounts if len(fields) == 7 and fields[0] == "consolepi"]
    if len(matches) != 1:
        raise ClaimError("Účet consolepi chybí nebo není jednoznačný.")
    account = matches[0]
    if (account[2] != str(expected_uid) or account[3] != str(expected_gid) or
            account[5] != str(home_path)):
        raise ClaimError("Účet consolepi nemá očekávané UID, GID nebo home.")
    shadow = [line.split(":") for line in shadow_text.splitlines() if line]
    locked = [fields for fields in shadow if len(fields) >= 2 and fields[0] == "consolepi"]
    if len(locked) != 1 or not locked[0][1].startswith(("!", "*")):
        raise ClaimError("Heslo účtu consolepi není uzamčené.")
    home = Path(home_path)
    try:
        home_info = home.lstat()
    except OSError as exc:
        raise ClaimError("Home účtu consolepi není bezpečný.") from exc
    if (not stat.S_ISDIR(home_info.st_mode) or stat.S_ISLNK(home_info.st_mode) or
            home_info.st_uid != expected_uid or home_info.st_gid != expected_gid or
            stat.S_IMODE(home_info.st_mode) & 0o022):
        raise ClaimError("Home účtu consolepi není bezpečný.")
    return validate_authorized_key(home / ".ssh/authorized_keys", expected_uid, expected_gid)


def unexpected_login_accounts(passwd_text, allowed=("root", "consolepi", "console")):
    login_shells = {"sh", "bash", "dash", "zsh", "ksh", "fish"}
    unexpected = []
    for line in passwd_text.splitlines():
        fields = line.split(":")
        if len(fields) != 7:
            raise ClaimError("Neplatný formát passwd databáze.")
        name, shell = fields[0], Path(fields[6]).name
        if name not in allowed and shell in login_shells:
            unexpected.append(name)
    return unexpected
