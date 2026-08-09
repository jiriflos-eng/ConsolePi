#!/usr/bin/python3
import importlib
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "usr/local/lib"))
import consolepi_firstboot_security as security
import consolepi_imager_security as imager_security
def expect_failure(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except (security.ClaimError, imager_security.ImagerImportError, FileNotFoundError):
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


def test_token(root):
    token_path, metadata = root / "token", root / "claim.json"
    sessions = root / "sessions"
    token = security.create_token(token_path, metadata, now=100)
    expect_failure(security.consume_token, "invalid", token_path, metadata, sessions, 101)
    session_id = security.consume_token(token, token_path, metadata, sessions, now=101)
    assert token != session_id and not token_path.exists()
    assert security.validate_session(session_id, sessions, now=102)
    expect_failure(security.consume_token, token, token_path, metadata, sessions, 102)
    importlib.reload(security)
    expect_failure(security.consume_token, token, token_path, metadata, sessions, 103)
    security.consume_session(session_id, sessions)
    expect_failure(security.validate_session, session_id, sessions, 104)
    expired_token = security.create_token(token_path, metadata, now=200)
    expect_failure(
        security.consume_token, expired_token, token_path, metadata, sessions,
        200 + security.TOKEN_TTL + 1,
    )
    app_source = (ROOT / "opt/consolepi-web/app.py").read_text()
    assert 'session["setup_ownership_token"]' not in app_source
    assert 'request.args' not in app_source[app_source.index("def setup():"):app_source.index("def setup_storage_expand")]


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
    for state in ("pending", "claim_pending", "key_generation_pending", "complete"):
        assert security.validate_generic_access(state, passwd, shadow, home, uid, gid) == ed25519
    expect_failure(security.validate_generic_access, "claim_pending", passwd, "consolepi:$6$hash:1::::::\n", home, uid, gid)
    keys.write_text(ed25519 + "\n" + ed25519 + "\n")
    expect_failure(security.validate_generic_access, "claim_pending", passwd, shadow, home, uid, gid)
    keys.write_text("invalid\n"); expect_failure(
        security.validate_generic_access, "key_generation_pending", passwd, shadow, home, uid, gid)
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

    source = (ROOT / "usr/local/sbin/consolepi-generic-image-firstboot").read_text()
    assert source.index("validate_generic_access") < source.index("case \"$state\" in claim_pending")


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


def test_imager_key_and_firstrun(root):
    key = make_key(root).strip()
    fixture = imager_security.expected_imager_2010_payload(key).encode()
    assert imager_security.parse_imager_2010_payload(fixture) == key
    home = root / "home/consolepi"
    home.mkdir(parents=True)
    imager_security.install_authorized_key(home, os.getuid(), os.getgid(), key)
    authorized = home / ".ssh/authorized_keys"
    assert security.validate_authorized_key(authorized, os.getuid()).startswith("ssh-ed25519 ")
    sanitizer = (ROOT / "usr/local/sbin/consolepi-prepare-generic-image").read_text()
    bridge = (ROOT / "usr/local/libexec/consolepi-imager-firstrun").read_text()
    assert 'mv -f /boot/.firstrun.sh.consolepi-new /boot/firstrun.sh' in sanitizer
    assert 'consolepi-imager-import "$boot_mount"' in bridge
    assert '/bin/sh "$payload"' not in bridge and '/bin/bash' not in bridge
    assert 'ln -s "$boot_relative/cmdline.txt" /boot/cmdline.txt' in sanitizer

    rejected = [
        fixture.replace(b"'pi' ''", b"'pi' '$6$passwordhash'"),
        fixture.replace(b"'pi' ''", b"'other' ''"),
        fixture.replace(b"set +e\n", b"set +e\nhostname evil\n"),
        fixture.replace(b"set +e\n", b"set +e\nimager_custom set_wlan evil hash CZ\n"),
        fixture.replace(b"set +e\n", b"set +e\nrpi-connect signin token\n"),
        fixture.replace(b"set +e\n", b"set +e\necho extra\n"),
        fixture.replace(b"exit 0\n", b"echo extra\nexit 0\n"),
        fixture + b"echo trailing\n",
        fixture[:-20],
        b"",
    ]
    second_root = root / "second"; second_root.mkdir()
    second = make_key(second_root).strip()
    rejected.append(fixture.replace(key.encode(), (key + "\n" + second).encode(), 1))
    rsa = make_key(root, "rsa").strip()
    rejected.append(imager_security.expected_imager_2010_payload(rsa).encode())
    rejected.append(imager_security.expected_imager_2010_payload("no-port-forwarding " + key).encode())
    rejected.append(fixture.replace(key.encode(), (key + ";touch /tmp/pwned").encode()))
    for payload in rejected:
        expect_failure(imager_security.parse_imager_2010_payload, payload)

    flow = root / "flow"; flow.mkdir()
    flow_home = flow / "home/consolepi"; flow_home.mkdir(parents=True)
    flow_boot = flow / "boot"; flow_boot.mkdir()
    (flow_boot / "firstrun.sh").write_bytes(fixture)
    (flow_boot / "cmdline.txt").write_text("rootwait systemd.run=/boot/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target\n")
    failure, success = flow / "failed", flow / "imported"
    imager_security.import_key_only_customization(
        flow_boot, flow_home, os.getuid(), os.getgid(), failure, success
    )
    assert success.exists() and not failure.exists()
    assert not (flow_boot / "firstrun.sh").exists()
    assert "systemd.run" not in (flow_boot / "cmdline.txt").read_text()
    assert security.validate_authorized_key(flow_home / ".ssh/authorized_keys", os.getuid()) == key

    reject = root / "reject"; reject.mkdir()
    reject_home = reject / "home/consolepi"; reject_home.mkdir(parents=True)
    reject_boot = reject / "boot"; reject_boot.mkdir()
    (reject_boot / "firstrun.sh").write_bytes(rejected[0])
    (reject_boot / "cmdline.txt").write_text("rootwait systemd.run=/boot/firstrun.sh\n")
    reject_failure, reject_success = reject / "failed", reject / "imported"
    expect_failure(imager_security.import_key_only_customization,
                   reject_boot, reject_home, os.getuid(), os.getgid(), reject_failure, reject_success)
    assert reject_failure.exists() and not reject_success.exists()
    assert not (reject_boot / "firstrun.sh").exists()
    firstboot_source = (ROOT / "usr/local/sbin/consolepi-generic-image-firstboot").read_text()
    assert 'generic-imager-customization-failed' in firstboot_source
    assert 'validate_imager_markers' in firstboot_source

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

    failed = root / "failed-cleanup"; failed.mkdir()
    failed_home = failed / "home/consolepi"; failed_home.mkdir(parents=True)
    failed_boot = failed / "boot"; failed_boot.mkdir()
    (failed_boot / "firstrun.sh").write_bytes(fixture)
    (failed_boot / "cmdline.txt").mkdir()
    failed_marker, failed_success = failed / "failed", failed / "imported"
    expect_failure(imager_security.import_key_only_customization,
                   failed_boot, failed_home, os.getuid(), os.getgid(), failed_marker, failed_success)
    assert failed_marker.exists() and not failed_success.exists()


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        state_root = root / "states"; state_root.mkdir(); test_states(state_root)
        token_root = root / "tokens"; token_root.mkdir(); test_token(token_root)
        key_root = root / "keys"; key_root.mkdir(); test_keys(key_root)
        imager_root = root / "imager"; imager_root.mkdir(); test_imager_key_and_firstrun(imager_root)
        invariant_root = root / "invariants"; invariant_root.mkdir(); test_active_state_and_markers(invariant_root)
        machine_id_root = root / "machine-id"; machine_id_root.mkdir(); test_machine_id_sanitization(machine_id_root)
    test_accounts()
    test_standard_isolation()
    print("OK: generic image behavioral security tests")


if __name__ == "__main__":
    main()
