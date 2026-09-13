"""Minimal process bootstrap for BonkScanner.

Qt and optional dependencies are loaded only after the crash journal is active.
"""

from __future__ import annotations

import os
import sys

from infra.crash_journal import (
    install_crash_journal,
    log_runtime_event,
    mark_clean_exit,
)


_UNLOADED = object()
keyboard = _UNLOADED
MegabonkApp = _UNLOADED
_config_initialized = False


def _load_keyboard_dependency():
    global keyboard
    if keyboard is not _UNLOADED:
        return keyboard
    from infra.keyboard_backend import load_keyboard

    keyboard = load_keyboard()
    return keyboard


def _prepare_linux_environment() -> None:
    """Pick the X11 Qt platform on Linux unless the user chose otherwise.

    The in-game overlay places a transparent window over the game's client
    area.  Wayland gives clients no say in where their windows go, X11 does,
    and both the native game and a Proton game are X11 windows (through
    XWayland in a Wayland session), so the overlay can only follow them from
    an X11 window of its own.
    """

    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


def _load_gui_application():
    global MegabonkApp
    if MegabonkApp is _UNLOADED:
        _initialize_configuration()
        from gui_app import MegabonkApp as loaded_app

        MegabonkApp = loaded_app
    return MegabonkApp


def _initialize_configuration() -> None:
    global _config_initialized
    if _config_initialized:
        return
    from app.config import initialize_config

    initialize_config()
    _config_initialized = True


def _terminate_process(exit_code: int) -> None:
    os._exit(int(exit_code))


def main():
    install_crash_journal()
    _prepare_linux_environment()
    _initialize_configuration()
    if _load_keyboard_dependency() is None:
        from infra.keyboard_backend import keyboard_dependency_hint

        mark_clean_exit()
        print("[CRITICAL ERROR] Missing dependency: keyboard.")
        print("Install it with: pip install keyboard")
        if not sys.platform == "win32":
            print(keyboard_dependency_hint())
        return

    app_type = _load_gui_application()
    log_runtime_event("application.constructing")
    app = app_type(terminate_process=_terminate_process)
    event_loop_failed = False
    try:
        app.protocol("WM_DELETE_WINDOW", app.on_closing)
        app.start()
        log_runtime_event("application.mainloop_enter")
        app.mainloop()
    except BaseException:
        event_loop_failed = True
        raise
    finally:
        # A normal window close already runs this through ``closeEvent``.  The
        # idempotent second call also covers QApplication.quit(), event-loop
        # termination by the OS, and an exception escaping ``exec()``.
        clean_shutdown = app.on_closing()
    log_runtime_event("application.mainloop_return")
    if not event_loop_failed and clean_shutdown is not False:
        mark_clean_exit()

if __name__ == "__main__":
    main()
