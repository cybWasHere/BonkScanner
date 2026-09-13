"""One place that says which operating system BonkScanner is running on.

The Windows build is the reference; the Linux build swaps four backends
(process memory, keyboard, window system, credential store) behind the same
call sites.  Modules ask here instead of sprinkling ``sys.platform`` checks.
"""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def platform_name() -> str:
    if IS_WINDOWS:
        return "windows"
    if IS_LINUX:
        return "linux"
    return sys.platform


__all__ = ["IS_LINUX", "IS_WINDOWS", "platform_name"]
