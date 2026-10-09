"""Fail-closed host IO and public-only Ed25519 verification primitives."""

import math
import os
import selectors
import stat
import time
from pathlib import Path


class Denied(ValueError):
    pass


MAX_BYTES = 65536


def finite_number(value):
    return type(value) in (int, float) and 0 <= value <= 1e12 and math.isfinite(value)


def verify_public(key, domain, encoded, signature):
    if (
        type(key) is not bytes
        or len(key) != 32
        or type(signature) is not str
        or len(signature) != 128
    ):
        raise Denied("invalid public verification material")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as error:
        raise Denied(
            "cryptography Ed25519 dependency unavailable; authentication closed"
        ) from error
    try:
        raw = bytes.fromhex(signature)
        if raw.hex() != signature:
            raise Denied("noncanonical signature")
        Ed25519PublicKey.from_public_bytes(key).verify(
            raw, domain.encode() + b"\x00" + encoded
        )
    except (ValueError, InvalidSignature) as error:
        raise Denied("authentication failed") from error


def protected_parent(path, private=False):
    """Walk no-follow directory FDs; never normalize away a supplied link/.. ."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise Denied("absolute protected path required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
                raise Denied("unprotected path ancestor")
        info = os.fstat(fd)
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise Denied("ledger directory must be service-private")
        return fd, path.name
    except BaseException:
        os.close(fd)
        raise


def check_file(fd, bounded=True):
    return check_file_stat(os.fstat(fd), bounded)


def check_file_stat(info, bounded=True):
    """Validate a single metadata snapshot without relaxing owner/link rules."""
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        raise Denied("host file must be regular, owner-only, single-link")
    if bounded and info.st_size > MAX_BYTES:
        raise Denied("host file too large")
    return info

def stat_entry(parent, name):
    """One no-follow snapshot of a directory entry; None when the name is gone."""
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None

def validate_sidecar(first, second_lookup):
    """Validate one SQLite sidecar snapshot without a removed-file false denial.

    SQLite may unlink a sidecar on last close between the directory lookup and
    the metadata snapshot, yielding a zero-link entry. Only a zero-link first
    snapshot justifies exactly one recheck of the same name; the skip is
    permitted solely when the name is gone. Any surviving or replaced entry
    must pass every original check (regular, owner-only, single-link).
    """
    if first is None:
        return
    try:
        check_file_stat(first, bounded=False)
    except Denied:
        if first.st_nlink != 0:
            raise
        second = second_lookup()
        if second is None:
            return
        check_file_stat(second, bounded=False)

def check_sidecar(parent, name):
    """Real-filesystem sidecar validation against one protected parent FD."""
    validate_sidecar(stat_entry(parent, name), lambda: stat_entry(parent, name))


def read_private_fd(fd):
    check_file(fd)
    chunks = bytearray()
    while len(chunks) <= MAX_BYTES:
        chunk = os.read(fd, min(8192, MAX_BYTES + 1 - len(chunks)))
        if not chunk:
            break
        chunks.extend(chunk)
    if len(chunks) > MAX_BYTES:
        raise Denied("host file too large")
    return bytes(chunks)


def read_frame(fd, timeout=2):
    """One EOF-delimited JSON frame, bounded bytes AND wall time."""
    deadline = time.monotonic() + timeout
    info = os.fstat(fd)
    if stat.S_ISREG(info.st_mode):
        if info.st_size > MAX_BYTES:
            raise Denied("input too large")
        return os.read(fd, MAX_BYTES + 1)
    if not stat.S_ISFIFO(info.st_mode) and not stat.S_ISSOCK(info.st_mode):
        raise Denied("stdin must be a pipe or bounded regular file")
    result = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while len(result) <= MAX_BYTES:
            left = deadline - time.monotonic()
            if left <= 0 or not selector.select(left):
                raise Denied("input deadline exceeded")
            chunk = os.read(fd, min(8192, MAX_BYTES + 1 - len(result)))
            if not chunk:
                return bytes(result)
            result.extend(chunk)
    raise Denied("input too large")
