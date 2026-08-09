#!/usr/bin/python3
"""Strict Raspberry Pi Imager 2.0.10 importer and FAT sanitizer."""
import base64
import binascii
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

FAILURE_MARKER = Path("/etc/consolepi/generic-imager-customization-failed")
SUCCESS_MARKER = Path("/etc/consolepi/generic-imager-customization-imported")
SUCCESS_CONTENT = b"imager-2.0.10-ed25519-imported\n"
KEY_RE = re.compile(r"ssh-ed25519 ([A-Za-z0-9+/]+={0,2})(?: ([A-Za-z0-9._@+-]{1,128}))?")
ALLOWED_ROOT = (
    re.compile(r"bcm[0-9A-Za-z._+-]*\.dtb"), re.compile(r"kernel[0-9A-Za-z._+-]*\.img"),
    re.compile(r"initramfs[0-9A-Za-z._+-]*"), re.compile(r"start[0-9A-Za-z._+-]*\.elf"),
    re.compile(r"fixup[0-9A-Za-z._+-]*\.dat"), re.compile(r"System\.map-[0-9A-Za-z._+-]+"),
    re.compile(r"config-[0-9A-Za-z._+-]+"), re.compile(r"vmlinuz-[0-9A-Za-z._+-]+"),
)
ALLOWED_EXACT = {"bootcode.bin", "cmdline.txt", "config.txt", "COPYING.linux", "LICENCE.broadcom", "issue.txt"}
STRONG_SECRET = re.compile(rb"BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY|ssh-(?:ed25519|rsa) [A-Za-z0-9+/]{20,}")
TEXT_SECRET = re.compile(r"(?im)(?:^\s*(?:password|passwd|psk|token|secret|instance-id|ssh_authorized_keys)\s*[:=]\s*\S+|\$(?:1|2[aby]?|5|6|y)\$[^\s:]{8,})")


class ImagerImportError(ValueError):
    pass


def _safe_directory(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ImagerImportError(f"unsafe directory: {path}")
    return path


def _lexists(path):
    try:
        Path(path).lstat()
        return True
    except FileNotFoundError:
        return False


def _atomic_write(path, data, mode=0o600):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data if isinstance(data, bytes) else data.encode())
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass


def mark_failure(marker=FAILURE_MARKER, reason="invalid Imager customization"):
    _atomic_write(marker, reason.rstrip() + "\n", 0o600)


def validate_imager_markers(failure_marker=FAILURE_MARKER, success_marker=SUCCESS_MARKER,
                            expected_uid=0, expected_gid=0):
    failure_marker, success_marker = Path(failure_marker), Path(success_marker)
    try:
        failure_marker.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ImagerImportError("failure marker cannot be inspected") from exc
    else:
        raise ImagerImportError("Imager customization failure marker is present")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(success_marker, flags)
    except OSError as exc:
        raise ImagerImportError("success marker is missing or unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or
                info.st_gid != expected_gid or stat.S_IMODE(info.st_mode) != 0o600 or
                info.st_nlink != 1):
            raise ImagerImportError("success marker metadata is invalid")
        content = os.read(descriptor, len(SUCCESS_CONTENT) + 1)
        if content != SUCCESS_CONTENT:
            raise ImagerImportError("success marker content is invalid")
    finally:
        os.close(descriptor)
    return True


def validate_ed25519_key(key):
    match = KEY_RE.fullmatch(key)
    if not match:
        raise ImagerImportError("expected exactly one unoptioned Ed25519 key")
    try:
        blob = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImagerImportError("invalid Ed25519 key encoding") from exc
    if len(blob) != 51 or blob[:4] != b"\x00\x00\x00\x0b" or blob[4:15] != b"ssh-ed25519" or blob[15:19] != b"\x00\x00\x00\x20":
        raise ImagerImportError("invalid Ed25519 wire-format key")
    return key


def expected_imager_2010_payload(key):
    """Exact key-only systemd script emitted by upstream Imager v2.0.10."""
    return f'''#!/bin/sh

set +e

FIRSTUSER=$(getent passwd 1000 | cut -d: -f1)
FIRSTUSERHOME=$(getent passwd 1000 | cut -d: -f6)
if [ -f /usr/lib/raspberrypi-sys-mods/imager_custom ]; then
   /usr/lib/raspberrypi-sys-mods/imager_custom enable_ssh -k '{key}'
else
   install -o "$FIRSTUSER" -m 700 -d "$FIRSTUSERHOME/.ssh"
cat > "$FIRSTUSERHOME/.ssh/authorized_keys" <<'EOF'
{key}
EOF
   chown "$FIRSTUSER:$FIRSTUSER" "$FIRSTUSERHOME/.ssh/authorized_keys"
   chmod 600 "$FIRSTUSERHOME/.ssh/authorized_keys"
   echo 'PasswordAuthentication no' >>/etc/ssh/sshd_config
   systemctl enable ssh
fi
if [ -f /usr/lib/userconf-pi/userconf ]; then
   /usr/lib/userconf-pi/userconf 'pi' ''
else
   if [ "$FIRSTUSER" != "pi" ]; then
      usermod -l "pi" "$FIRSTUSER"
      usermod -m -d "/home/pi" "pi"
      groupmod -n "pi" "$FIRSTUSER"
      if grep -q "^autologin-user=" /etc/lightdm/lightdm.conf ; then
         sed /etc/lightdm/lightdm.conf -i -e "s/^autologin-user=.*/autologin-user=pi/"
      fi
      if [ -f /etc/systemd/system/getty@tty1.service.d/autologin.conf ]; then
         sed /etc/systemd/system/getty@tty1.service.d/autologin.conf -i -e "s/$FIRSTUSER/pi/"
      fi
      if [ -f /etc/sudoers.d/010_pi-nopasswd ]; then
         sed -i "s/^$FIRSTUSER /pi /" /etc/sudoers.d/010_pi-nopasswd
      fi
   fi
fi
rm -f /boot/firstrun.sh
sed -i 's| systemd.run.*||g' /boot/cmdline.txt
exit 0
'''


def parse_imager_2010_payload(data):
    if len(data) > 65536 or b"\x00" in data or b"\r" in data:
        raise ImagerImportError("oversized or non-canonical Imager payload")
    try: text = data.decode("utf-8")
    except UnicodeDecodeError as exc: raise ImagerImportError("payload is not UTF-8") from exc
    prefix = "   /usr/lib/raspberrypi-sys-mods/imager_custom enable_ssh -k '"
    candidates = [line for line in text.splitlines() if line.startswith(prefix)]
    if len(candidates) != 1 or not candidates[0].endswith("'"):
        raise ImagerImportError("missing or multiple key-only Imager operations")
    key = validate_ed25519_key(candidates[0][len(prefix):-1])
    if text != expected_imager_2010_payload(key):
        raise ImagerImportError("payload differs from the upstream v2.0.10 key-only template")
    return key


def parse_or_mark_failure(data, marker=FAILURE_MARKER):
    try:
        return parse_imager_2010_payload(data)
    except Exception as exc:
        mark_failure(marker, str(exc))
        raise


def install_authorized_key(home, uid, gid, key):
    home = _safe_directory(home)
    if home.stat().st_uid != uid:
        raise ImagerImportError("consolepi home has an unexpected owner")
    home_fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        home_info = os.fstat(home_fd)
        if home_info.st_uid != uid or not stat.S_ISDIR(home_info.st_mode):
            raise ImagerImportError("consolepi home changed during import")
        created = False
        try:
            os.mkdir(".ssh", 0o700, dir_fd=home_fd)
            created = True
        except FileExistsError: pass
        ssh_fd = os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=home_fd)
        try:
            if created:
                os.fchown(ssh_fd, uid, gid)
            info = os.fstat(ssh_fd)
            if info.st_uid != uid:
                raise ImagerImportError(".ssh has an unexpected owner")
            os.fchmod(ssh_fd, 0o700)
            try: os.stat("authorized_keys", dir_fd=ssh_fd, follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise ImagerImportError("authorized_keys already exists")
            name = f".authorized_keys.{os.getpid()}.new"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(name, flags, 0o600, dir_fd=ssh_fd)
            try:
                os.write(descriptor, (key + "\n").encode()); os.fsync(descriptor)
                os.fchmod(descriptor, 0o600); os.fchown(descriptor, uid, gid)
            finally: os.close(descriptor)
            os.rename(name, "authorized_keys", src_dir_fd=ssh_fd, dst_dir_fd=ssh_fd)
            os.fsync(ssh_fd)
        finally: os.close(ssh_fd)
    finally: os.close(home_fd)


def cleanup_imager_payload(boot_mount):
    root = _safe_directory(boot_mount)
    payload = root / "firstrun.sh"
    payload.unlink(missing_ok=True)
    if payload.exists() or payload.is_symlink():
        raise ImagerImportError("cannot remove Imager payload")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)
    cmdline = root / "cmdline.txt"
    if cmdline.is_symlink() or not cmdline.is_file():
        raise ImagerImportError("missing or unsafe cmdline.txt")
    lines = cmdline.read_text().splitlines()
    if len(lines) != 1: raise ImagerImportError("cmdline.txt is malformed")
    denied = ("systemd.run=", "systemd.run_success_action=", "systemd.run_failure_action=", "ds=nocloud")
    tokens = [x for x in lines[0].split() if not x.startswith(denied) and x != "systemd.unit=kernel-command-line.target"]
    _atomic_write(cmdline, " ".join(tokens) + "\n", 0o644)


def import_key_only_customization(boot_mount, home, uid, gid, failure_marker=FAILURE_MARKER, success_marker=SUCCESS_MARKER):
    boot = Path(boot_mount)
    failure_marker, success_marker = Path(failure_marker), Path(success_marker)
    try:
        if _lexists(failure_marker) or _lexists(success_marker):
            raise ImagerImportError("Imager customization was already processed")
        payload = boot / "firstrun.sh"
        if payload.is_symlink() or not payload.is_file():
            raise ImagerImportError("Imager payload is missing")
        key = parse_imager_2010_payload(payload.read_bytes())
        install_authorized_key(home, uid, gid, key)
        cleanup_imager_payload(boot)
        _atomic_write(success_marker, SUCCESS_CONTENT, 0o600)
        return key
    except Exception as exc:
        try: mark_failure(failure_marker, str(exc))
        except Exception: pass
        try: cleanup_imager_payload(boot)
        except Exception: pass
        raise


def clear_directory(path):
    root = _safe_directory(path)
    for entry in os.scandir(root):
        candidate = Path(entry.path)
        shutil.rmtree(candidate) if entry.is_dir(follow_symlinks=False) else candidate.unlink()


def _allowed_boot_entry(path):
    if path.name in ALLOWED_EXACT: return True
    if path.name == "overlays" and path.is_dir() and not path.is_symlink(): return True
    return any(pattern.fullmatch(path.name) for pattern in ALLOWED_ROOT)


def scan_boot_partition(path):
    root = _safe_directory(path)
    for candidate in root.rglob("*"):
        if candidate.is_symlink(): raise ImagerImportError(f"boot symlink is not allowed: {candidate.name}")
        if not candidate.is_file(): continue
        data = candidate.read_bytes()
        if STRONG_SECRET.search(data): raise ImagerImportError(f"credential material remains in {candidate.name}")
        if len(data) <= 1024 * 1024 and b"\x00" not in data:
            try: text = data.decode("utf-8")
            except UnicodeDecodeError: continue
            if TEXT_SECRET.search(text): raise ImagerImportError(f"provisioning data remains in {candidate.name}")


def sanitize_boot_partition(path):
    root = _safe_directory(path)
    for entry in list(root.iterdir()):
        if not _allowed_boot_entry(entry):
            shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
    overlays = root / "overlays"
    if overlays.exists():
        for entry in list(overlays.iterdir()):
            if entry.is_symlink() or not (entry.is_file() and (entry.suffix in {".dtbo", ".dtb"} or entry.name == "README")):
                shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
    for required in (root / "config.txt", root / "cmdline.txt"):
        if required.is_symlink() or not required.is_file(): raise ImagerImportError(f"required boot file missing: {required.name}")
    cleanup_imager_payload(root)
    scan_boot_partition(root)
