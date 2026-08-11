#!/usr/bin/python3
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "usr/local/lib"))
import consolepi_firstboot_security as security
import consolepi_imager_security as imager_security
import consolepi_generic_recovery as recovery_security
def expect_failure(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except (security.ClaimError, imager_security.ImagerImportError,
            recovery_security.RecoveryError, FileNotFoundError):
        return
    raise AssertionError(f"Expected failure: {function.__name__}")


def test_states(root):
    firstboot = root / "firstboot.json"
    generic = root / "generic.json"
    firstboot.write_text('{"state":"pending","reason":"generic_image"}\n')
    security.write_generic_state(generic, "pending")
    assert security.generic_state(firstboot, generic) == "pending"
    for content in (None, "", "{", '{"state":"unknown"}', '{}'):
        generic.unlink(missing_ok=True)
        if content is not None:
            generic.write_text(content)
        assert security.claim_required(firstboot, generic)
        assert security.generic_state(firstboot, generic) == "claim_required"
    firstboot.write_text('{"state":"pending","reason":"factory_reset"}\n')
    assert not security.claim_required(firstboot, generic)



def make_key(directory, kind="ed25519"):
    private = directory / kind
    subprocess.run(
        ["ssh-keygen", "-q", "-t", kind, "-N", "", "-f", str(private)],
        check=True,
    )
    return (directory / f"{kind}.pub").read_text()


def test_keys(root):
    home = root / "home"
    ssh = home / ".ssh"
    ssh.mkdir(parents=True, mode=0o700)
    os.chmod(ssh, 0o700)
    keys = ssh / "authorized_keys"
    ed25519 = make_key(root)
    keys.write_text(ed25519)
    os.chmod(keys, 0o600)
    assert security.validate_authorized_key(keys, os.getuid()).startswith("ssh-ed25519 ")
    keys.write_text(ed25519 + ed25519)
    expect_failure(security.validate_authorized_key, keys, os.getuid())
    rsa = make_key(root, "rsa")
    keys.write_text(rsa)
    expect_failure(security.validate_authorized_key, keys, os.getuid())
    keys.write_text("no-port-forwarding " + ed25519)
    expect_failure(security.validate_authorized_key, keys, os.getuid())
    keys.write_text(ed25519)
    os.chmod(keys, 0o644)
    expect_failure(security.validate_authorized_key, keys, os.getuid())
    os.chmod(keys, 0o600)
    hardlink = ssh / "second-link"
    os.link(keys, hardlink)
    expect_failure(security.validate_authorized_key, keys, os.getuid())
    hardlink.unlink()
    expect_failure(security.validate_authorized_key, keys, os.getuid() + 1)
    keys.unlink()
    target = root / "target"
    target.write_text(ed25519)
    keys.symlink_to(target)
    expect_failure(security.validate_authorized_key, keys, os.getuid())
    keys.unlink()
    ssh.rmdir()
    real_ssh = root / "real-ssh"
    real_ssh.mkdir(mode=0o700)
    ssh.symlink_to(real_ssh, target_is_directory=True)
    (real_ssh / "authorized_keys").write_text(ed25519)
    os.chmod(real_ssh / "authorized_keys", 0o600)
    expect_failure(security.validate_authorized_key, ssh / "authorized_keys", os.getuid())


def test_accounts():
    passwd = "root:x:0:0::/root:/bin/bash\nconsolepi:x:1000:1000::/home/consolepi:/bin/bash\nservice:x:110:110::/nonexistent:/usr/sbin/nologin\n"
    assert security.unexpected_login_accounts(passwd) == []
    assert security.unexpected_login_accounts(passwd + "intruder:x:1001:1001::/home/intruder:/bin/sh\n") == ["intruder"]


def test_active_state_and_markers(root):
    uid, gid = os.getuid(), os.getgid()
    home = root / "home/consolepi"
    ssh = home / ".ssh"
    ssh.mkdir(parents=True, mode=0o700)
    os.chmod(home, 0o755); os.chmod(ssh, 0o700)
    key_root = root / "key"; key_root.mkdir()
    ed25519 = make_key(key_root).strip()
    keys = ssh / "authorized_keys"
    keys.write_text(ed25519 + "\n"); os.chmod(keys, 0o600)
    passwd = f"consolepi:x:{uid}:{gid}::${{HOME}}:/bin/bash\n".replace("${HOME}", str(home))
    shadow = "consolepi:!:1::::::\n"
    for state in ("pending", "claim_pending", "complete"):
        assert security.validate_generic_access(state, passwd, shadow, home, uid, gid) == ed25519
    expect_failure(security.validate_generic_access, "claim_pending", passwd, "consolepi:$6$hash:1::::::\n", home, uid, gid)
    keys.write_text(ed25519 + "\n" + ed25519 + "\n")
    expect_failure(security.validate_generic_access, "claim_pending", passwd, shadow, home, uid, gid)
    keys.write_text("invalid\n"); expect_failure(
        security.validate_generic_access, "claim_pending", passwd, shadow, home, uid, gid)
    keys.write_text(ed25519 + "\n")
    changed_uid = passwd.replace(f":{uid}:{gid}:", f":{uid + 1}:{gid}:")
    expect_failure(security.validate_generic_access, "complete", changed_uid, shadow, home, uid, gid)
    rsa_root = root / "rsa-key"; rsa_root.mkdir()
    keys.write_text(make_key(rsa_root, "rsa")); expect_failure(
        security.validate_generic_access, "complete", passwd, shadow, home, uid, gid)
    keys.unlink(); ssh.rmdir()
    real_ssh = root / "real-ssh"; real_ssh.mkdir(mode=0o700)
    (real_ssh / "authorized_keys").write_text(ed25519 + "\n")
    os.chmod(real_ssh / "authorized_keys", 0o600)
    ssh.symlink_to(real_ssh, target_is_directory=True)
    expect_failure(security.validate_generic_access, "complete", passwd, shadow, home, uid, gid)

    def valid_success(directory):
        marker = directory / "success"
        marker.write_bytes(imager_security.SUCCESS_CONTENT); os.chmod(marker, 0o600)
        return marker

    marker_root = root / "markers"; marker_root.mkdir()
    failure, success = marker_root / "failure", valid_success(marker_root)
    assert imager_security.validate_imager_markers(failure, success, uid, gid)
    for kind in ("file", "dangling", "directory", "fifo"):
        case = marker_root / f"failure-{kind}"
        if kind == "file": case.write_text("failed\n")
        elif kind == "dangling": case.symlink_to(marker_root / "missing")
        elif kind == "directory": case.mkdir()
        else: os.mkfifo(case)
        expect_failure(imager_security.validate_imager_markers, case, success, uid, gid)

    cases = marker_root / "success-cases"; cases.mkdir()
    good = valid_success(cases)
    target = cases / "target"; target.write_bytes(imager_security.SUCCESS_CONTENT); os.chmod(target, 0o600)
    symlink = cases / "symlink"; symlink.symlink_to(target)
    dangling = cases / "dangling"; dangling.symlink_to(cases / "missing")
    wrong_mode = cases / "wrong-mode"; wrong_mode.write_bytes(imager_security.SUCCESS_CONTENT); os.chmod(wrong_mode, 0o644)
    hardlink = cases / "hardlink"; os.link(good, hardlink)
    wrong = cases / "wrong"; wrong.write_text("wrong\n"); os.chmod(wrong, 0o600)
    extra = cases / "extra"; extra.write_bytes(imager_security.SUCCESS_CONTENT + b"extra\n"); os.chmod(extra, 0o600)
    for candidate in (symlink, dangling, wrong_mode, good, wrong, extra):
        expect_failure(imager_security.validate_imager_markers, cases / "no-failure", candidate, uid, gid)
    owner = cases / "owner"; owner.write_bytes(imager_security.SUCCESS_CONTENT); os.chmod(owner, 0o600)
    expect_failure(imager_security.validate_imager_markers, cases / "no-failure", owner, uid + 1, gid)
    both_failure = cases / "both-failure"; both_failure.write_text("failed\n")
    expect_failure(imager_security.validate_imager_markers, both_failure, owner, uid, gid)

    write_once = root / "write-once"; write_once.mkdir()
    first_failure = write_once / "failure"
    assert imager_security.mark_failure_once(first_failure, "first reason", uid, gid)
    assert not imager_security.mark_failure_once(first_failure, "second reason", uid, gid)
    assert first_failure.read_text() == "first reason\n"
    for kind in ("dangling", "directory", "fifo"):
        occupied = write_once / kind
        if kind == "dangling": occupied.symlink_to(write_once / "missing")
        elif kind == "directory": occupied.mkdir()
        else: os.mkfifo(occupied)
        assert not imager_security.mark_failure_once(occupied, "must not replace", uid, gid)
        assert occupied.is_symlink() if kind == "dangling" else occupied.exists()
    expect_failure(imager_security.ensure_transaction_open, first_failure,
                   write_once / "no-success", uid, gid)
    assert first_failure.read_text() == "first reason\n"

    unexpected_success = write_once / "unexpected-success"
    unexpected_success.write_bytes(imager_security.SUCCESS_CONTENT); os.chmod(unexpected_success, 0o600)
    generated_failure = write_once / "generated-failure"
    expect_failure(imager_security.ensure_transaction_open, generated_failure,
                   unexpected_success, uid, gid)
    assert generated_failure.read_text() == "unexpected Imager success marker is already present\n"

    optional = root / "optional-user"; optional.mkdir()
    user_marker = optional / "user"
    assert not imager_security.validate_optional_marker(
        user_marker, imager_security.USER_OPERATION_CONTENT, uid, gid)
    user_marker.write_bytes(imager_security.USER_OPERATION_CONTENT); os.chmod(user_marker, 0o600)
    assert imager_security.validate_optional_marker(
        user_marker, imager_security.USER_OPERATION_CONTENT, uid, gid)
    user_marker.write_text("malformed\n"); os.chmod(user_marker, 0o600)
    expect_failure(imager_security.validate_optional_marker, user_marker,
                   imager_security.USER_OPERATION_CONTENT, uid, gid)
    user_marker.unlink(); user_marker.symlink_to(optional / "missing")
    expect_failure(imager_security.validate_optional_marker, user_marker,
                   imager_security.USER_OPERATION_CONTENT, uid, gid)

    audit_root = root / "audit"; audit_root.mkdir()
    audit = audit_root / "events.jsonl"
    key_secret = "ssh-ed25519 AAAAC3Nza-secret-key-material"
    password_secret = "$6$secret-password-hash"
    hostname_secret = "private-hostname"
    ssid_secret = "private-ssid"
    assert imager_security.guard_operation_label("ssh", ["enable_ssh", "-k", key_secret]) == "enable_ssh"
    assert imager_security.guard_operation_label("user", ["consolepi", password_secret]) == "user_config"
    imager_security.append_guard_audit("imager_custom", "enable_ssh", 3, "accepted", audit, uid, gid)
    imager_security.append_guard_audit("userconf", "user_config", 2, "rejected", audit, uid, gid)
    events = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [event["seq"] for event in events] == [1, 2]
    assert events[0] == {"seq": 1, "guard": "imager_custom", "operation": "enable_ssh",
                         "argc": 3, "result": "accepted"}
    audit_text = audit.read_text()
    for secret in (key_secret, password_secret, hostname_secret, ssid_secret, "consolepi"):
        assert secret not in audit_text
    for kind in ("directory", "dangling", "fifo", "wrong-mode"):
        unsafe = audit_root / kind
        if kind == "directory": unsafe.mkdir()
        elif kind == "dangling": unsafe.symlink_to(audit_root / "missing")
        elif kind == "fifo": os.mkfifo(unsafe)
        else: unsafe.write_text(""); os.chmod(unsafe, 0o644)
        expect_failure(imager_security.append_guard_audit, "imager_custom", "unknown", 1,
                       "rejected", unsafe, uid, gid)

    source = (ROOT / "usr/local/sbin/consolepi-generic-image-firstboot").read_text()
    assert source.index("validate_generic_access") < source.index("case \"$state\" in claim_pending")

    # A completed Imager post-validation must be restart-safe.  If firstboot
    # fails later, an existing valid success marker must not cause
    # postvalidate to be executed as a new Imager transaction.
    assert 'if [ "$state" = pending ] && [ ! -e "$IMAGER_SUCCESS" ]; then' in source

    # Generic firstboot runs before ssh.service.  Authentication-file sync
    # must validate sshd configuration but reload ssh only when the systemd
    # service is already active.
    control = (ROOT / "usr/local/sbin/consolepi-control").read_text()
    auth_start = control.index("def apply_authentication_files")
    auth_end = control.index("\ndef auth_status", auth_start)
    auth_block = control[auth_start:auth_end]
    assert 'run("sshd", "-t")' in auth_block
    assert 'run("systemctl", "is-active", "ssh", check=False)' in auth_block
    assert 'if ssh_active:' in auth_block
    assert auth_block.index('run("sshd", "-t")') < auth_block.index(
        'run("systemctl", "is-active", "ssh", check=False)'
    )
    assert auth_block.index('if ssh_active:') < auth_block.index(
        'run("systemctl", "reload", "ssh")'
    )


def test_standard_isolation():
    installer = (ROOT / "install.sh").read_text()
    standard_ssh = (ROOT / "etc/ssh/sshd_config.d/40-consolepi.conf").read_bytes()
    baseline = subprocess.check_output(
        ["git", "show", "HEAD:etc/ssh/sshd_config.d/40-consolepi.conf"], cwd=ROOT
    )
    assert standard_ssh == baseline
    assert "systemctl enable consolepi-generic-image-firstboot" not in installer
    assert "service.d/consolepi-generic-image.conf" not in installer
    assert "imager-systemd-compat" not in installer
    assert "generic-imager-audit.jsonl" not in installer
    assert "systemctl enable consolepi-generic-recovery" not in installer


def test_physical_recovery(root):
    uid, gid = os.getuid(), os.getgid()
    generic = root / "generic-image.json"
    failure = root / "failure"
    boot = root / "boot"; boot.mkdir()
    marker = boot / "consolepi-recovery-enable"
    active = root / "generic-recovery-active"
    success = root / "success"
    audit = root / "audit"
    operation = root / "operation"
    authorized = root / "authorized_keys"
    generic.write_text('{"state":"pending"}\n'); os.chmod(generic, 0o600)

    assert not recovery_security.activate_recovery(generic, failure, marker, active, uid, gid)
    marker.write_bytes(b""); os.chmod(marker, 0o644)
    audit.write_bytes(b'{"seq":1}\n')
    operation.write_bytes(b"operation-marker\n")
    authorized.write_bytes(b"ssh-ed25519 test-placeholder\n")
    audit_before, operation_before, authorized_before = (
        audit.read_bytes(), operation.read_bytes(), authorized.read_bytes())
    assert recovery_security.activate_recovery(generic, failure, marker, active, uid, gid)
    assert not marker.exists() and not success.exists()
    assert not failure.exists() and audit.read_bytes() == audit_before
    assert operation.read_bytes() == operation_before and authorized.read_bytes() == authorized_before
    info = active.lstat()
    assert info.st_uid == uid and info.st_gid == gid and stat.S_IMODE(info.st_mode) == 0o600
    assert not recovery_security.activate_recovery(generic, failure, marker, active, uid, gid)

    # A failure object independently permits recovery even without pending state.
    generic.write_text('{"state":"complete"}\n'); os.chmod(generic, 0o600)
    failure.write_bytes(b"original failure\n")
    failure_before, audit_before = failure.read_bytes(), audit.read_bytes()
    marker.write_bytes(b""); os.chmod(marker, 0o644)
    assert recovery_security.activate_recovery(generic, failure, marker, active, uid, gid)
    assert failure.read_bytes() == failure_before and audit.read_bytes() == audit_before

    for kind in ("content", "symlink", "fifo", "directory"):
        marker.unlink(missing_ok=True)
        if kind == "content": marker.write_text("not-empty\n"); os.chmod(marker, 0o644)
        elif kind == "symlink": marker.symlink_to(boot / "missing")
        elif kind == "fifo": os.mkfifo(marker)
        else: marker.mkdir()
        expect_failure(recovery_security.activate_recovery, generic, failure, marker, active, uid, gid)
        if marker.is_dir() and not marker.is_symlink(): marker.rmdir()
        else: marker.unlink(missing_ok=True)

    script = (ROOT / "usr/local/sbin/consolepi-generic-recovery").read_text()
    unit = (ROOT / "etc/systemd/system/consolepi-generic-recovery.service").read_text()
    sanitizer = (ROOT / "usr/local/sbin/consolepi-prepare-generic-image").read_text()
    assert '$(tty 2>/dev/null)" = /dev/tty1' in script
    assert "ConsolePi GENERIC IMAGE RECOVERY" in script
    assert "Provisioning remains FAIL-CLOSED." in script
    assert "Restart=" not in unit and "Before=getty@tty1.service" in unit
    assert "ssh.service" not in unit and "nginx.service" not in unit and "network-online.target" not in unit
    assert '"$STATE_DIR/generic-recovery-active"' in sanitizer
    assert "consolepi-recovery-enable" not in sanitizer


def test_machine_id_sanitization(root):
    sanitizer = (ROOT / "usr/local/sbin/consolepi-prepare-generic-image").read_text()
    preparation = "printf '%s\\n' uninitialized >\"$prep_dir/machine-id\""
    assert preparation in sanitizer
    assert "install -o root -g root -m 0444 \"$prep_dir/machine-id\" /etc/.machine-id.consolepi-new" in sanitizer
    assert "mv -f /etc/.machine-id.consolepi-new /etc/machine-id" in sanitizer
    assert "rm -f /var/lib/systemd/random-seed /var/lib/dbus/machine-id" in sanitizer
    assert "truncate -s 0 /etc/machine-id" not in sanitizer
    old_identity = b"0123456789abcdef0123456789abcdef\n"
    candidate = root / "machine-id"
    candidate.write_bytes(old_identity)
    subprocess.run(
        ["sh", "-c", "prep_dir=$1\n" + preparation, "sh", str(root)], check=True
    )
    assert candidate.read_bytes() == b"uninitialized\n"
    assert candidate.read_bytes() and candidate.read_bytes() != old_identity


def test_legacy_cmdline_placeholder(root):
    uid, gid = os.getuid(), os.getgid()
    cmdline = root / "cmdline.txt"
    assert imager_security.validate_legacy_cmdline(cmdline, uid, gid)
    cmdline.write_bytes(imager_security.LEGACY_CMDLINE_PLACEHOLDER)
    os.chmod(cmdline, 0o644)
    assert imager_security.validate_legacy_cmdline(cmdline, uid, gid)
    assert imager_security.remove_legacy_cmdline_placeholder(cmdline, uid, gid)
    assert not cmdline.exists()
    cmdline.write_text("different cmdline\n")
    os.chmod(cmdline, 0o644)
    expect_failure(imager_security.validate_legacy_cmdline, cmdline, uid, gid)
    cmdline.unlink()
    target = root / "target"
    target.write_bytes(imager_security.LEGACY_CMDLINE_PLACEHOLDER)
    cmdline.symlink_to(target)
    expect_failure(imager_security.validate_legacy_cmdline, cmdline, uid, gid)
    cmdline.unlink()
    cmdline.write_bytes(imager_security.LEGACY_CMDLINE_PLACEHOLDER.rstrip(b"\n"))
    os.chmod(cmdline, 0o644)
    expect_failure(imager_security.validate_legacy_cmdline, cmdline, uid, gid)

    sanitizer = (ROOT / "usr/local/sbin/consolepi-prepare-generic-image").read_text()
    assert "validate_legacy_cmdline(sys.argv[1])" in sanitizer
    assert "remove_legacy_cmdline_placeholder(sys.argv[1])" in sanitizer
    assert "[ ! -e /boot/firstrun.sh ] && [ ! -L /boot/firstrun.sh ]" in sanitizer


def test_imager_key_and_firstrun(root):
    key = make_key(root).strip()
    assert imager_security.validate_ssh_request(["enable_ssh", "-k", key]) == key
    assert imager_security.validate_userconf_request(["consolepi", ""])
    home = root / "home/consolepi"
    home.mkdir(parents=True)
    imager_security.install_authorized_key(home, os.getuid(), os.getgid(), key)
    authorized = home / ".ssh/authorized_keys"
    assert security.validate_authorized_key(authorized, os.getuid()).startswith("ssh-ed25519 ")
    sanitizer = (ROOT / "usr/local/sbin/consolepi-prepare-generic-image").read_text()
    guard = (ROOT / "usr/local/libexec/consolepi-imager-guard").read_text()
    assert 'mv "$VENDOR_CUSTOM" "$VENDOR_CUSTOM.consolepi-vendor"' in sanitizer
    assert 'mv "$VENDOR_USERCONF" "$VENDOR_USERCONF.consolepi-vendor"' in sanitizer
    assert "os.execv(VENDORS[mode]" in guard
    activation = root / "activation"
    assert not imager_security.generic_guard_active(activation)
    activation.write_text("generic-image-systemd-v2\n")
    assert imager_security.generic_guard_active(activation)
    restore = root / "restore"; restore.mkdir()
    wrapper, active, vendor = restore / "wrapper", restore / "active", restore / "active.consolepi-vendor"
    wrapper.write_text("guard\n"); active.write_text("guard\n"); vendor.write_text("vendor\n")
    for path in (wrapper, active, vendor): os.chmod(path, 0o755)
    imager_security.restore_vendor_entrypoint(active, vendor, wrapper, os.getuid(), os.getgid())
    assert active.read_text() == "vendor\n" and not vendor.exists()
    assert 'ln -s "$boot_relative/cmdline.txt" /boot/cmdline.txt' in sanitizer

    # Raspberry Pi Imager requires a username/password customization entry.
    # The password/hash is accepted syntactically but is never applied by the
    # generic guard; consolepi must remain locked.
    assert imager_security.validate_userconf_request(
        ["consolepi", "$6$dummy-password-hash"]
    )
    assert imager_security.validate_userconf_request(
        ["consolepi", "temporary-imager-password"]
    )

    for arguments in (["pi", ""], ["consolepi"],
                      ["consolepi", "", "extra"],
                      ["consolepi", "bad\nvalue"]):
        expect_failure(imager_security.validate_userconf_request, arguments)

    assert imager_security.validate_safe_imager_noop(
        ["set_hostname", "consolepi"]
    )
    assert imager_security.validate_safe_imager_noop(
        ["set_keymap", "cz"]
    )
    assert imager_security.validate_safe_imager_noop(
        ["set_timezone", "Europe/Prague"]
    )

    for arguments in (
        ["set_wlan", "ssid"],
        ["set_hostname", ""],
        ["set_hostname", "-invalid"],
        ["set_keymap", "bad value"],
        ["set_timezone", "../bad timezone"],
        ["unknown", "value"],
    ):
        expect_failure(imager_security.validate_safe_imager_noop, arguments)

    rejected = (["set_wlan", "ssid", "psk", "CZ"], ["set_hostname", "evil"],
                ["enable_ssh"], ["enable_ssh", "-p", key],
                ["enable_ssh", "-k", key, "extra"])
    for arguments in rejected:
        expect_failure(imager_security.validate_ssh_request, arguments)
    second_root = root / "second"; second_root.mkdir()
    second = make_key(second_root).strip()
    expect_failure(imager_security.validate_ssh_request, ["enable_ssh", "-k", key + "\n" + second])
    rsa = make_key(root, "rsa").strip()
    for invalid in (rsa, "no-port-forwarding " + key, key + ";touch /tmp/pwned", "invalid"):
        expect_failure(imager_security.validate_ssh_request, ["enable_ssh", "-k", invalid])

    operations = root / "operations"; operations.mkdir()
    ssh_operation = operations / "ssh"
    user_operation = operations / "user"
    imager_security.record_operation(ssh_operation, (key + "\n").encode())
    imager_security.record_operation(user_operation, imager_security.USER_OPERATION_CONTENT)
    assert imager_security.read_strict_marker(ssh_operation, (key + "\n").encode(), os.getuid(), os.getgid())
    assert imager_security.read_strict_marker(user_operation, imager_security.USER_OPERATION_CONTENT, os.getuid(), os.getgid())
    expect_failure(imager_security.record_operation, user_operation, b"again\n")
    firstboot_source = (ROOT / "usr/local/sbin/consolepi-generic-image-firstboot").read_text()
    assert 'generic-imager-customization-failed' in firstboot_source
    assert 'validate_imager_markers' in firstboot_source
    assert "if ! python3 - \"$IMAGER_FAILURE\" \"$IMAGER_SUCCESS\" <<'PY'" in firstboot_source
    assert "<<'PY' ||\n" not in firstboot_source
    marker_block = firstboot_source[firstboot_source.index("if ! python3 - \"$IMAGER_FAILURE\""):
                                    firstboot_source.index("\nfi", firstboot_source.index("if ! python3 - \"$IMAGER_FAILURE\"")) + 3]
    marker_block = marker_block.replace('/usr/local/lib', str(ROOT / "usr/local/lib"))
    runtime = "fail() { exit 23; }\nIMAGER_FAILURE=$1\nIMAGER_SUCCESS=$2\n" + marker_block
    executed = subprocess.run(["sh", "-c", runtime, "sh", str(root / "missing-failure"),
                               str(root / "missing-success")], text=True, capture_output=True)
    assert executed.returncode == 23 and "IndentationError" not in executed.stderr

    boot = root / "boot"
    boot.mkdir()
    (boot / "config.txt").write_text("arm_64bit=1\n")
    (boot / "cmdline.txt").write_text("console=tty1 ds=nocloud;i=old rootwait\n")
    (boot / "kernel8.img").write_bytes(b"kernel")
    overlays = boot / "overlays"; overlays.mkdir(); (overlays / "test.dtbo").write_bytes(b"dtbo")
    for name in ("user-data", "meta-data", "network-config"):
        (boot / name).write_text("password: stale-hash\n")
    nested = boot / "nocloud"
    nested.mkdir()
    (nested / "instance-id").write_text("old-device\n")
    cloud = root / "var/lib/cloud/instances/old-device"
    cloud.mkdir(parents=True)
    (cloud / "obj.pkl").write_text("cached identity\n")
    imager_security.sanitize_boot_partition(boot)
    imager_security.clear_directory(root / "var/lib/cloud")
    assert not any((boot / name).exists() for name in ("user-data", "meta-data", "network-config"))
    assert not nested.exists()
    assert "ds=nocloud" not in (boot / "cmdline.txt").read_text()
    assert list((root / "var/lib/cloud").iterdir()) == []
    assert (boot / "kernel8.img").exists() and (overlays / "test.dtbo").exists()

    unsafe_boot = root / "unsafe-boot"; unsafe_boot.mkdir()
    (unsafe_boot / "config.txt").write_text("password=not-allowed\n")
    (unsafe_boot / "cmdline.txt").write_text("rootwait\n")
    expect_failure(imager_security.scan_boot_partition, unsafe_boot)


    hostkeys = root / "hostkeys"; hostkeys.mkdir()
    assert imager_security.require_no_host_keys(hostkeys)
    (hostkeys / "ssh_host_ed25519_key").write_text("existing")
    expect_failure(imager_security.require_no_host_keys, hostkeys)
    (hostkeys / "ssh_host_ed25519_key").unlink()
    expect_failure(imager_security.validate_host_keys, hostkeys, os.getuid(), os.getgid())
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f",
                    str(hostkeys / "ssh_host_ed25519_key")], check=True)
    os.chmod(hostkeys / "ssh_host_ed25519_key", 0o600)
    os.chmod(hostkeys / "ssh_host_ed25519_key.pub", 0o644)
    assert imager_security.validate_host_keys(hostkeys, os.getuid(), os.getgid())

    class Result:
        def __init__(self, returncode): self.returncode = returncode

    empty = root / "hostkeys-keygen-fail"; empty.mkdir()
    expect_failure(imager_security.provision_host_keys, empty, os.getuid(), os.getgid(),
                   lambda *args, **kwargs: Result(1))

    generated = root / "hostkeys-sshd-fail"; generated.mkdir()
    def fail_sshd(command, **kwargs):
        if command[0] == "ssh-keygen":
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f",
                            str(generated / "ssh_host_ed25519_key")], check=True)
            os.chmod(generated / "ssh_host_ed25519_key", 0o600)
            os.chmod(generated / "ssh_host_ed25519_key.pub", 0o644)
            return Result(0)
        return Result(1)
    expect_failure(imager_security.provision_host_keys, generated, os.getuid(), os.getgid(), fail_sshd)


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        state_root = root / "states"; state_root.mkdir(); test_states(state_root)
        key_root = root / "keys"; key_root.mkdir(); test_keys(key_root)
        imager_root = root / "imager"; imager_root.mkdir(); test_imager_key_and_firstrun(imager_root)
        invariant_root = root / "invariants"; invariant_root.mkdir(); test_active_state_and_markers(invariant_root)
        machine_id_root = root / "machine-id"; machine_id_root.mkdir(); test_machine_id_sanitization(machine_id_root)
        cmdline_root = root / "cmdline"; cmdline_root.mkdir(); test_legacy_cmdline_placeholder(cmdline_root)
        recovery_root = root / "recovery"; recovery_root.mkdir(); test_physical_recovery(recovery_root)
    test_accounts()
    test_standard_isolation()
    print("OK: generic image behavioral security tests")


if __name__ == "__main__":
    main()
