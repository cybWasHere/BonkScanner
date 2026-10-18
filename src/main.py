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
    if keyboard is not None:
        from infra.windows_keyboard import install_windows_keyboard_runtime

        install_windows_keyboard_runtime(keyboard)
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


def _show_startup_storage_error(message: str) -> None:
    text = f"BonkScanner could not open its data folder.\n\n{message}"
    print(f"[CRITICAL ERROR] {text}", file=sys.stderr)
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, "BonkScanner", 0x10)
    except Exception:
        pass


def main():
    from infra.app_restart import launch_restart, wait_for_previous_instance
    from infra.data_storage import (
        StorageError,
        initialize_storage,
        release_storage_lock,
    )

    try:
        wait_for_previous_instance()
        initialize_storage()
    except (StorageError, OSError) as exc:
        _show_startup_storage_error(str(exc))
        return
    install_crash_journal()
    _prepare_linux_environment()
    restart_requested = False
    try:
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
            restart_requested = getattr(app, "_restart_requested", False) is True
    finally:
        release_storage_lock()
    if restart_requested:
        try:
            launch_restart()
        except OSError as exc:
            _show_startup_storage_error(
                f"Automatic restart failed: {exc}\n\n"
                "Start BonkScanner manually to perform the scheduled migration."
            )

if __name__ == "__main__":
    main()
