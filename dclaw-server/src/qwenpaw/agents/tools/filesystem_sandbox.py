"""Fail-closed Linux Landlock sandbox for Agent subprocess tools."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Callable

_CREATE_RULESET = 444
_ADD_RULE = 445
_RESTRICT_SELF = 446
_RULE_PATH_BENEATH = 1
_CREATE_VERSION = 1
_PR_SET_NO_NEW_PRIVS = 38

_EXECUTE = 1 << 0
_WRITE_FILE = 1 << 1
_READ_FILE = 1 << 2
_READ_DIR = 1 << 3
_REMOVE_DIR = 1 << 4
_REMOVE_FILE = 1 << 5
_MAKE_CHAR = 1 << 6
_MAKE_DIR = 1 << 7
_MAKE_REG = 1 << 8
_MAKE_SOCK = 1 << 9
_MAKE_FIFO = 1 << 10
_MAKE_BLOCK = 1 << 11
_MAKE_SYM = 1 << 12
_REFER = 1 << 13
_TRUNCATE = 1 << 14

_READ_ONLY = _EXECUTE | _READ_FILE | _READ_DIR
_READ_WRITE = (
    _READ_ONLY
    | _WRITE_FILE
    | _REMOVE_DIR
    | _REMOVE_FILE
    | _MAKE_CHAR
    | _MAKE_DIR
    | _MAKE_REG
    | _MAKE_SOCK
    | _MAKE_FIFO
    | _MAKE_BLOCK
    | _MAKE_SYM
    | _REFER
    | _TRUNCATE
)
_WORKSPACE_ACCESS = _READ_WRITE & ~(
    _MAKE_CHAR | _MAKE_BLOCK | _MAKE_SOCK | _MAKE_SYM
)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
        ("reserved", ctypes.c_uint32),
    ]


def _libc() -> ctypes.CDLL:
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    return library


def landlock_abi_version() -> int:
    """Return the supported Landlock ABI, or zero off supported Linux."""
    if sys.platform != "linux":
        return 0
    result = _libc().syscall(
        _CREATE_RULESET,
        ctypes.c_void_p(),
        0,
        _CREATE_VERSION,
    )
    return int(result) if result > 0 else 0


def _handled_access(abi: int) -> int:
    access = _READ_WRITE
    if abi < 2:
        access &= ~_REFER
    if abi < 3:
        access &= ~_TRUNCATE
    return access


def ensure_landlock_available() -> None:
    """Raise before execution when containment cannot be guaranteed."""
    if landlock_abi_version() < 1:
        raise RuntimeError(
            "Secure filesystem sandbox is unavailable for this runtime",
        )


def _allow_path(
    library: ctypes.CDLL,
    ruleset_fd: int,
    path: Path,
    access: int,
) -> None:
    if not path.exists():
        return
    parent_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        attr = _PathBeneathAttr(
            allowed_access=access,
            parent_fd=parent_fd,
            reserved=0,
        )
        result = library.syscall(
            _ADD_RULE,
            ruleset_fd,
            _RULE_PATH_BENEATH,
            ctypes.byref(attr),
            0,
        )
        if result != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(parent_fd)


def _apply_landlock(workspace_root: Path) -> None:
    abi = landlock_abi_version()
    if abi < 1:
        raise RuntimeError("Landlock filesystem sandbox is unavailable")
    handled = _handled_access(abi)
    library = _libc()
    attr = _RulesetAttr(handled_access_fs=handled)
    ruleset_fd = library.syscall(
        _CREATE_RULESET,
        ctypes.byref(attr),
        ctypes.sizeof(attr),
        0,
    )
    if ruleset_fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    try:
        _allow_path(
            library,
            ruleset_fd,
            workspace_root.resolve(),
            handled & _WORKSPACE_ACCESS,
        )

        python_roots = {
            Path(sys.executable).parent.parent,
            Path(sys.executable).resolve().parent.parent,
            Path(sys.prefix),
            Path(sys.base_prefix),
        }
        for path in (
            Path("/bin"),
            Path("/usr"),
            Path("/lib"),
            Path("/lib64"),
            Path("/etc"),
            *python_roots,
        ):
            _allow_path(library, ruleset_fd, path, handled & _READ_ONLY)
        for path in (Path("/dev/null"), Path("/dev/urandom")):
            _allow_path(
                library,
                ruleset_fd,
                path,
                handled & (_READ_FILE | _WRITE_FILE),
            )

        if library.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        if library.syscall(_RESTRICT_SELF, ruleset_fd, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(ruleset_fd)


def landlock_preexec(workspace_root: Path) -> Callable[[], None]:
    """Build the child-only hook used by subprocess APIs."""
    root = Path(workspace_root).resolve()

    def apply() -> None:
        _apply_landlock(root)

    return apply
