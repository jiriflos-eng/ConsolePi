#!/usr/bin/python3
"""One-shot, physical-console-only recovery activation for generic images."""
import os
import stat
from pathlib import Path

from consolepi_imager_security import _atomic_write, _lexists


class RecoveryError(ValueError):
    pass


def _pending_state(path, expected_uid=0, expected_gid=0):
    path = Path(path)
    try:
        info = path.lstat()
        content = path.read_bytes()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
            info.st_uid == expected_uid and info.st_gid == expected_gid and
            info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600 and
            content == b'{"state":"pending"}\n')


def activate_recovery(generic_state, failure_marker, boot_marker, active_marker,
                      expected_uid=0, expected_gid=0):
    """Consume a safe empty boot marker and persist one active recovery session."""
    if not (_pending_state(generic_state, expected_uid, expected_gid) or
            _lexists(failure_marker)):
        return False
    boot_marker = Path(boot_marker)
    parent_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(boot_marker.parent, parent_flags)
    except OSError as exc:
        raise RecoveryError("recovery boot directory is unavailable") from exc
    descriptor = None
    try:
        try:
            before = os.stat(boot_marker.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or
                before.st_uid != expected_uid or before.st_gid != expected_gid or
                before.st_nlink != 1 or stat.S_IMODE(before.st_mode) & 0o022 or
                before.st_size != 0):
            raise RecoveryError("recovery boot marker is unsafe")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(boot_marker.name, flags, dir_fd=parent_fd)
        current = os.fstat(descriptor)
        if ((current.st_dev, current.st_ino) != (before.st_dev, before.st_ino) or
                not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or
                os.read(descriptor, 1) != b""):
            raise RecoveryError("recovery boot marker changed during validation")
        final = os.stat(boot_marker.name, dir_fd=parent_fd, follow_symlinks=False)
        if (final.st_dev, final.st_ino) != (before.st_dev, before.st_ino):
            raise RecoveryError("recovery boot marker changed before consumption")
        os.unlink(boot_marker.name, dir_fd=parent_fd)
        try:
            os.stat(boot_marker.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryError("recovery boot marker was not removed")
        os.fsync(parent_fd)
    except OSError as exc:
        raise RecoveryError("recovery boot marker cannot be consumed safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)
    _atomic_write(active_marker, b"physical-console-recovery-v1\n", 0o600)
    info = Path(active_marker).lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or
            info.st_uid != expected_uid or info.st_gid != expected_gid or
            info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise RecoveryError("recovery active marker metadata is unsafe")
    return True
