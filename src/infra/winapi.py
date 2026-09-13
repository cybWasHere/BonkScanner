"""``win32gui`` and ``win32process`` for the current platform.

On Windows these are the pywin32 modules.  On Linux they are
``infra.x11_windows``, which implements the same function names on top of X11.
Both may be ``None`` when nothing usable is installed; call sites already
treat that as "no window system", so they keep working headless.
"""

from __future__ import annotations

from infra.platform import IS_WINDOWS

win32gui = None
win32process = None

if IS_WINDOWS:
    try:
        import win32gui as _win32gui
        import win32process as _win32process
    except ImportError:  # pragma: no cover - pywin32 missing
        _win32gui = None
        _win32process = None
    win32gui = _win32gui
    win32process = _win32process
else:
    try:
        from infra import x11_windows as _x11_windows
    except ImportError:  # pragma: no cover - python-xlib missing
        _x11_windows = None
    if _x11_windows is not None and _x11_windows.is_available():
        win32gui = _x11_windows
        win32process = _x11_windows


__all__ = ["win32gui", "win32process"]
