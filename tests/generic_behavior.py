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


def expect_failure(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except (security.ClaimError, FileNotFoundError):
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


def test_standard_isolation():
    installer = (ROOT / "install.sh").read_text()
    standard_ssh = (ROOT / "etc/ssh/sshd_config.d/40-consolepi.conf").read_bytes()
    baseline = subprocess.check_output(
        ["git", "show", "HEAD:etc/ssh/sshd_config.d/40-consolepi.conf"], cwd=ROOT
    )
    assert standard_ssh == baseline
    assert "systemctl enable consolepi-generic-image-firstboot" not in installer
    assert "service.d/consolepi-generic-image.conf" not in installer


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        state_root = root / "states"; state_root.mkdir(); test_states(state_root)
        token_root = root / "tokens"; token_root.mkdir(); test_token(token_root)
        key_root = root / "keys"; key_root.mkdir(); test_keys(key_root)
    test_accounts()
    test_standard_isolation()
    print("OK: generic image behavioral security tests")


if __name__ == "__main__":
    main()
