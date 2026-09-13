"""Linux stand-in for the parts of ``pymem`` that ``ProcessMemory`` relies on.

``pymem`` opens a Windows process handle and reads through
``ReadProcessMemory``.  On Linux the same three facts come from ``/proc``:

* the process id, by matching the configured executable name against
  ``/proc/<pid>/comm`` and the basename of ``/proc/<pid>/cmdline``;
* the module base, from the first mapping of that file in ``/proc/<pid>/maps``
  (an ELF ``.so`` or, for a game running under Proton, a PE ``.dll`` -- Wine
  maps the image file, so the path shows up there like any other library);
* the bytes, through ``process_vm_readv`` with ``/proc/<pid>/mem`` as the
  fallback.

Reading another process's memory needs ptrace permission.  With the default
``kernel.yama.ptrace_scope = 1`` a non-root process may only read its
descendants, so the interpreter needs ``CAP_SYS_PTRACE`` (``setcap
cap_sys_ptrace=ep .venv/bin/python3``) or the scope must be 0.  A permission
failure raises with that explanation instead of a bare ``EPERM``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

COMM_LENGTH = 15  # the kernel truncates /proc/<pid>/comm to 15 bytes


class ProcessNotFound(Exception):
    """No running process matches the configured executable name."""


class CouldNotOpenProcess(Exception):
    """The process exists but its memory cannot be read."""


class ModuleNotFound(Exception):
    """The module is not mapped in the target process."""


@dataclass(frozen=True)
class ModuleInfo:
    """Mirror of the pymem module object: only ``lpBaseOfDll`` is read."""

    name: str
    path: str
    lpBaseOfDll: int
    SizeOfImage: int


PTRACE_HINT = (
    "Reading the game's memory was denied. On Linux the scanner needs ptrace "
    "permission: run `sudo setcap cap_sys_ptrace=ep <path to .venv/bin/python3>` "
    "(start.sh offers this), or set kernel.yama.ptrace_scope=0."
)


def _module_name_variants(module_name: str) -> tuple[str, ...]:
    """``GameAssembly.dll`` also matches ``GameAssembly.so`` and vice versa.

    The memory clients default to the Windows module name.  A native Linux
    build ships the same IL2CPP image as an ELF shared object, so accept either
    spelling; the type-info offsets are chosen per binary elsewhere.
    """

    name = os.path.basename(module_name.strip())
    stem, ext = os.path.splitext(name)
    variants = [name]
    if ext.lower() == ".dll":
        variants.append(stem + ".so")
    elif ext.lower() == ".so":
        variants.append(stem + ".dll")
    return tuple(dict.fromkeys(v.lower() for v in variants))


def _process_names(pid: int) -> tuple[str, str]:
    """Return ``(comm, argv0 basename)`` for a pid, empty strings when unreadable."""

    proc = Path("/proc") / str(pid)
    try:
        comm = (proc / "comm").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        comm = ""
    try:
        raw = (proc / "cmdline").read_bytes()
    except OSError:
        raw = b""
    argv0 = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace") if raw else ""
    # Wine passes Windows paths through unchanged, so split on both separators.
    argv0 = argv0.replace("\\", "/").rsplit("/", 1)[-1]
    return comm, argv0


def process_name_matches(target: str, comm: str, argv0: str) -> bool:
    wanted = target.strip().lower()
    if not wanted:
        return False
    if argv0 and argv0.lower() == wanted:
        return True
    if comm:
        comm_lower = comm.lower()
        if comm_lower == wanted:
            return True
        # comm is truncated; a long executable name matches on its prefix.
        if len(wanted) > COMM_LENGTH and comm_lower == wanted[:COMM_LENGTH]:
            return True
    return False


def process_name_candidates(process_name: str) -> tuple[str, ...]:
    """The configured name first, then its native-Linux spelling.

    ``config.json`` ships with the Windows executable name.  A Unity game's
    Linux build is ``<name>.x86_64``, so ``Megabonk.exe`` also finds
    ``Megabonk.x86_64`` without editing the config; a game under Proton still
    matches the ``.exe`` first.
    """

    name = process_name.strip()
    candidates = [name]
    stem, ext = os.path.splitext(name)
    if ext.lower() == ".exe" and stem:
        candidates.append(stem + ".x86_64")
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def find_process_ids(process_name: str, *, proc_root: str | os.PathLike[str] = "/proc") -> list[int]:
    """Every pid whose executable name matches, ascending, excluding ourselves."""

    matches: list[int] = []
    own_pid = os.getpid()
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return matches
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == own_pid:
            continue
        comm, argv0 = _process_names(pid) if proc_root == "/proc" else _process_names_at(proc_root, pid)
        if process_name_matches(process_name, comm, argv0):
            matches.append(pid)
    return sorted(matches)


def _process_names_at(proc_root: str | os.PathLike[str], pid: int) -> tuple[str, str]:
    proc = Path(proc_root) / str(pid)
    try:
        comm = (proc / "comm").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        comm = ""
    try:
        raw = (proc / "cmdline").read_bytes()
    except OSError:
        raw = b""
    argv0 = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace") if raw else ""
    argv0 = argv0.replace("\\", "/").rsplit("/", 1)[-1]
    return comm, argv0


def parse_maps(lines: Iterable[str]) -> list[tuple[int, int, str]]:
    """``(start, end, path)`` for every file-backed mapping in ``/proc/<pid>/maps``."""

    mappings: list[tuple[int, int, str]] = []
    for line in lines:
        parts = line.split(maxsplit=5)
        if len(parts) < 6:
            continue
        path = parts[5].strip()
        if not path or path.startswith("["):
            continue
        start_text, end_text = parts[0].split("-", 1)
        try:
            mappings.append((int(start_text, 16), int(end_text, 16), path))
        except ValueError:
            continue
    return mappings


def module_from_maps(mappings: Iterable[tuple[int, int, str]], module_name: str) -> ModuleInfo | None:
    """Lowest mapping of a module by file basename, with the image span."""

    variants = _module_name_variants(module_name)
    best: ModuleInfo | None = None
    for start, end, path in mappings:
        basename = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if basename not in variants:
            continue
        if best is None or start < best.lpBaseOfDll:
            best = ModuleInfo(name=basename, path=path, lpBaseOfDll=start, SizeOfImage=end - start)
        elif path == best.path:
            best = ModuleInfo(best.name, best.path, best.lpBaseOfDll, max(best.SizeOfImage, end - best.lpBaseOfDll))
    return best


def module_from_name(process_handle: int, module_name: str) -> ModuleInfo:
    """Same signature as ``pymem.process.module_from_name``; the handle is the pid."""

    pid = int(process_handle)
    try:
        with open(f"/proc/{pid}/maps", "r", encoding="utf-8", errors="replace") as handle:
            module = module_from_maps(parse_maps(handle), module_name)
    except OSError as exc:
        raise ModuleNotFound(f"Cannot read /proc/{pid}/maps: {exc}") from exc
    if module is None:
        raise ModuleNotFound(f"Module '{module_name}' is not mapped in process {pid}.")
    return module


class _IoVec(ctypes.Structure):
    _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]


def _load_process_vm_readv():
    libc_name = ctypes.util.find_library("c") or "libc.so.6"
    try:
        libc = ctypes.CDLL(libc_name, use_errno=True)
        fn = libc.process_vm_readv
    except (OSError, AttributeError):
        return None
    fn.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(_IoVec),
        ctypes.c_ulong,
        ctypes.POINTER(_IoVec),
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    fn.restype = ctypes.c_ssize_t
    return fn


class LinuxProcess:
    """The ``pymem.Pymem`` surface ``ProcessMemory`` uses, backed by ``/proc``.

    ``process_handle`` is the pid: ``ProcessMemory`` keys its module-base cache
    on it, and a pid is the natural identity of a Linux process for that
    purpose.
    """

    def __init__(self, process_name: str) -> None:
        self.process_name = process_name
        pids: list[int] = []
        for candidate in process_name_candidates(process_name):
            pids = find_process_ids(candidate)
            if pids:
                self.process_name = candidate
                break
        if not pids:
            raise ProcessNotFound(f"No running process named '{process_name}'.")
        self.process_id = pids[0]
        self.process_handle = self.process_id
        self._mem_fd: int | None = None
        self._readv = _load_process_vm_readv()
        self._readv_broken = self._readv is None
        self._probe_access()

    def _probe_access(self) -> None:
        """Read one word from the first mapping so a permission problem fails now.

        Without this, every later read would raise the same hint one at a time;
        with it, ``ProcessMemory`` reports "could not open process" up front,
        which is where the Windows build reports the equivalent failure.
        """

        try:
            with open(f"/proc/{self.process_id}/maps", "r", encoding="utf-8", errors="replace") as handle:
                mappings = parse_maps(handle)
        except OSError as exc:
            raise CouldNotOpenProcess(f"Cannot read /proc/{self.process_id}/maps: {exc}") from exc
        if not mappings:
            return
        self.read_bytes(mappings[0][0], 8)

    def close_process(self) -> None:
        if self._mem_fd is not None:
            try:
                os.close(self._mem_fd)
            except OSError:
                pass
            self._mem_fd = None

    close = close_process

    def read_bytes(self, address: int, size: int) -> bytes:
        size = int(size)
        if size <= 0:
            return b""
        if not self._readv_broken:
            data = self._read_via_readv(int(address), size)
            if data is not None:
                return data
        return self._read_via_mem(int(address), size)

    # -- internals -----------------------------------------------------------

    def _read_via_readv(self, address: int, size: int) -> bytes | None:
        assert self._readv is not None
        buffer = ctypes.create_string_buffer(size)
        local = _IoVec(ctypes.cast(buffer, ctypes.c_void_p), size)
        remote = _IoVec(ctypes.c_void_p(address), size)
        read = self._readv(self.process_id, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
        if read < 0:
            code = ctypes.get_errno()
            if code == errno.EPERM:
                raise CouldNotOpenProcess(PTRACE_HINT)
            if code == errno.ESRCH:
                raise CouldNotOpenProcess(f"Process {self.process_id} has exited.")
            if code in (errno.ENOSYS, errno.EINVAL):
                self._readv_broken = True
                return None
            raise OSError(code, f"process_vm_readv failed at 0x{address:X}: {os.strerror(code)}")
        return buffer.raw[:read]

    def _read_via_mem(self, address: int, size: int) -> bytes:
        if self._mem_fd is None:
            try:
                self._mem_fd = os.open(f"/proc/{self.process_id}/mem", os.O_RDONLY)
            except PermissionError as exc:
                raise CouldNotOpenProcess(PTRACE_HINT) from exc
            except FileNotFoundError as exc:
                raise CouldNotOpenProcess(f"Process {self.process_id} has exited.") from exc
        try:
            return os.pread(self._mem_fd, size, address)
        except PermissionError as exc:
            raise CouldNotOpenProcess(PTRACE_HINT) from exc
        except OSError as exc:
            if exc.errno == errno.EIO:
                return b""  # unmapped page: ProcessMemory reports the short read
            raise


def ptrace_permission_hint() -> str | None:
    """A sentence for the log when memory access is likely to be refused, else None."""

    if os.geteuid() == 0:
        return None
    try:
        scope = Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip()
    except OSError:
        return None
    if scope == "0":
        return None
    if _has_cap_sys_ptrace():
        return None
    return PTRACE_HINT


def _has_cap_sys_ptrace() -> bool:
    """True when the effective capability set of this process includes CAP_SYS_PTRACE (bit 19)."""

    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("CapEff:"):
                return bool(int(line.split()[1], 16) & (1 << 19))
    except (OSError, ValueError, IndexError):
        pass
    return False


__all__ = [
    "COMM_LENGTH",
    "CouldNotOpenProcess",
    "LinuxProcess",
    "ModuleInfo",
    "ModuleNotFound",
    "PTRACE_HINT",
    "ProcessNotFound",
    "find_process_ids",
    "module_from_maps",
    "module_from_name",
    "parse_maps",
    "process_name_matches",
    "ptrace_permission_hint",
]
