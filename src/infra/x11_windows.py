"""X11 implementation of the ``win32gui`` / ``win32process`` calls BonkScanner makes.

The run-control mixin, ``infra.process`` and the in-game overlay ask Windows
for a handful of facts about top-level windows: which ones exist, who owns
them, where they are, and which one is in front.  This module answers the same
questions from the X server through ``python-xlib`` and exposes them under the
``win32gui`` names so the call sites stay untouched:

``EnumWindows``, ``IsWindowVisible``, ``GetWindowRect``, ``GetClientRect``,
``ClientToScreen``, ``GetWindowText``, ``GetParent``, ``GetWindow``,
``GetWindowLong``, ``GetForegroundWindow``, ``SetForegroundWindow``,
``BringWindowToTop``, ``ShowWindow``, ``IsIconic`` and
``GetWindowThreadProcessId``.

A window "handle" is the X window id.  Process ids come from ``_NET_WM_PID``,
which Wine, SDL and Unity all set.  Games under Proton are X11 windows even in
a Wayland session (through XWayland), and a Qt overlay run with the ``xcb``
platform is one too, so this covers both the native and the Proton build.

The X connection is opened lazily and every call takes one lock: Xlib's
``Display`` is not thread-safe and the overlay ticks from more than one thread.
Any X error degrades to "no window" rather than an exception, matching how the
Windows call sites treat failures.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

try:  # pragma: no cover - exercised on Linux only
    from Xlib import X, Xatom, display as xdisplay, error as xerror
    from Xlib.protocol import event as xevent
except ImportError:  # pragma: no cover
    X = Xatom = xdisplay = xerror = xevent = None


GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GW_OWNER = 4
SW_SHOW = 5
SW_RESTORE = 9

_TOOL_WINDOW_TYPES = ("_NET_WM_WINDOW_TYPE_UTILITY", "_NET_WM_WINDOW_TYPE_TOOLBAR", "_NET_WM_WINDOW_TYPE_TOOLTIP",
                      "_NET_WM_WINDOW_TYPE_NOTIFICATION", "_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_SPLASH")


class _Connection:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._display: Any = None
        self._atoms: dict[str, int] = {}
        self._atom_names: dict[int, str] = {}

    def display(self) -> Any:
        if self._display is None:
            if xdisplay is None:
                raise RuntimeError("python-xlib is not installed.")
            if not os.environ.get("DISPLAY"):
                raise RuntimeError("DISPLAY is not set; the X11 window backend needs an X server (XWayland is fine).")
            self._display = xdisplay.Display()
        return self._display

    def reset(self) -> None:
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                pass
        self._display = None
        self._atoms.clear()
        self._atom_names.clear()

    def atom(self, name: str) -> int:
        atom = self._atoms.get(name)
        if atom is None:
            atom = self.display().intern_atom(name)
            self._atoms[name] = atom
        return atom

    def atom_name(self, atom: int) -> str:
        name = self._atom_names.get(atom)
        if name is None:
            try:
                name = self.display().get_atom_name(atom)
            except Exception:
                name = ""
            self._atom_names[atom] = name
        return name


_connection = _Connection()


def _guarded(default: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Run under the connection lock; any X failure returns ``default``."""

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _connection.lock:
                try:
                    return function(*args, **kwargs)
                except (RuntimeError, OSError):
                    return default
                except Exception:
                    if xerror is not None and isinstance(getattr(xerror, "XError", None), type):
                        pass
                    _connection.reset()
                    return default

        wrapper.__name__ = function.__name__
        wrapper.__doc__ = function.__doc__
        return wrapper

    return decorate


def _window(window_id: int) -> Any:
    return _connection.display().create_resource_object("window", int(window_id))


def _root() -> Any:
    return _connection.display().screen().root


def _property(window: Any, name: str, type_atom: int | None = None) -> Any:
    prop = window.get_full_property(_connection.atom(name), type_atom if type_atom is not None else X.AnyPropertyType)
    return None if prop is None else prop.value


def _client_list(stacking: bool = True) -> list[int]:
    name = "_NET_CLIENT_LIST_STACKING" if stacking else "_NET_CLIENT_LIST"
    value = _property(_root(), name, Xatom.WINDOW)
    return [int(w) for w in value] if value is not None else []


def _net_wm_states(window_id: int) -> set[str]:
    value = _property(_window(window_id), "_NET_WM_STATE", Xatom.ATOM)
    return {_connection.atom_name(int(atom)) for atom in value} if value is not None else set()


def _window_type_names(window_id: int) -> set[str]:
    value = _property(_window(window_id), "_NET_WM_WINDOW_TYPE", Xatom.ATOM)
    return {_connection.atom_name(int(atom)) for atom in value} if value is not None else set()


def _geometry_on_root(window_id: int) -> tuple[int, int, int, int] | None:
    window = _window(window_id)
    geometry = window.get_geometry()
    translated = window.translate_coords(_root(), 0, 0)
    # translate_coords(root, 0, 0) answers "where is my origin on root" with
    # negated signs, per the Xlib convention.
    left, top = -int(translated.x), -int(translated.y)
    return left, top, left + int(geometry.width), top + int(geometry.height)


# -- win32gui ---------------------------------------------------------------


@_guarded(None)
def EnumWindows(callback: Callable[[int, Any], Any], extra: Any = None) -> None:
    """Top-level windows, front-most first, like the Windows enumeration order."""

    for window_id in reversed(_client_list(stacking=True)):
        if callback(window_id, extra) is False:
            break


@_guarded(False)
def IsWindowVisible(window_id: int) -> bool:
    if not window_id:
        return False
    attributes = _window(window_id).get_attributes()
    if attributes.map_state != X.IsViewable:
        return False
    return "_NET_WM_STATE_HIDDEN" not in _net_wm_states(window_id)


@_guarded(None)
def GetWindowRect(window_id: int) -> tuple[int, int, int, int] | None:
    return _geometry_on_root(window_id)


@_guarded(None)
def GetClientRect(window_id: int) -> tuple[int, int, int, int] | None:
    geometry = _window(window_id).get_geometry()
    return 0, 0, int(geometry.width), int(geometry.height)


@_guarded(None)
def ClientToScreen(window_id: int, point: tuple[int, int]) -> tuple[int, int] | None:
    translated = _window(window_id).translate_coords(_root(), int(point[0]), int(point[1]))
    return -int(translated.x), -int(translated.y)


@_guarded("")
def GetWindowText(window_id: int) -> str:
    window = _window(window_id)
    value = _property(window, "_NET_WM_NAME", _connection.atom("UTF8_STRING"))
    if value is None:
        value = _property(window, "WM_NAME")
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


@_guarded(0)
def GetParent(window_id: int) -> int:
    return 0  # every enumerated window is top-level


@_guarded(0)
def GetWindow(window_id: int, relation: int) -> int:
    if relation != GW_OWNER:
        return 0
    value = _property(_window(window_id), "WM_TRANSIENT_FOR", Xatom.WINDOW)
    if value is None or len(value) == 0:
        return 0
    owner = int(value[0])
    return 0 if owner == int(_root().id) else owner


@_guarded(0)
def GetWindowLong(window_id: int, index: int) -> int:
    if index != GWL_EXSTYLE:
        return 0
    types = _window_type_names(window_id)
    return WS_EX_TOOLWINDOW if types & set(_TOOL_WINDOW_TYPES) else 0


@_guarded(0)
def GetForegroundWindow() -> int:
    value = _property(_root(), "_NET_ACTIVE_WINDOW", Xatom.WINDOW)
    if value is None or len(value) == 0:
        return 0
    return int(value[0])


@_guarded(False)
def SetForegroundWindow(window_id: int) -> bool:
    """Ask the window manager to activate the window (``_NET_ACTIVE_WINDOW``).

    Focus-stealing prevention may refuse; the caller re-checks the foreground
    window afterwards, exactly as it does on Windows.
    """

    display = _connection.display()
    message = xevent.ClientMessage(
        window=_window(window_id),
        client_type=_connection.atom("_NET_ACTIVE_WINDOW"),
        data=(32, [2, X.CurrentTime, 0, 0, 0]),
    )
    _root().send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    display.flush()
    return True


@_guarded(False)
def BringWindowToTop(window_id: int) -> bool:
    _window(window_id).configure(stack_mode=X.Above)
    _connection.display().flush()
    return True


@_guarded(False)
def ShowWindow(window_id: int, command: int) -> bool:
    display = _connection.display()
    window = _window(window_id)
    if command in (SW_SHOW, SW_RESTORE):
        window.map()
        if "_NET_WM_STATE_HIDDEN" in _net_wm_states(window_id):
            message = xevent.ClientMessage(
                window=window,
                client_type=_connection.atom("_NET_WM_STATE"),
                data=(32, [0, _connection.atom("_NET_WM_STATE_HIDDEN"), 0, 1, 0]),
            )
            _root().send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    display.flush()
    return True


@_guarded(False)
def IsIconic(window_id: int) -> bool:
    return "_NET_WM_STATE_HIDDEN" in _net_wm_states(window_id)


# -- win32process -----------------------------------------------------------


@_guarded((0, 0))
def GetWindowThreadProcessId(window_id: int) -> tuple[int, int]:
    value = _property(_window(window_id), "_NET_WM_PID", Xatom.CARDINAL)
    if value is None or len(value) == 0:
        return 0, 0
    return 0, int(value[0])


# -- extras used by the Linux glue -------------------------------------------


@_guarded((0, 0))
def GetCursorPos() -> tuple[int, int]:
    """Pointer position on the root window (physical pixels), like ``user32.GetCursorPos``."""

    pointer = _root().query_pointer()
    return int(pointer.root_x), int(pointer.root_y)



@_guarded(False)
def SetTransientFor(window_id: int, owner_id: int) -> bool:
    """Make ``window_id`` transient for ``owner_id``.

    KWin and other EWMH managers stack a transient above its owner even when
    the owner is an active fullscreen window, which is exactly where the
    in-game overlay has to sit.
    """

    _window(window_id).set_wm_transient_for(_window(owner_id))
    _connection.display().flush()
    return True


def is_available() -> bool:
    return xdisplay is not None and bool(os.environ.get("DISPLAY"))


__all__ = [
    "BringWindowToTop",
    "ClientToScreen",
    "EnumWindows",
    "GW_OWNER",
    "GWL_EXSTYLE",
    "GetClientRect",
    "GetForegroundWindow",
    "GetParent",
    "GetWindow",
    "GetWindowLong",
    "GetWindowRect",
    "GetWindowText",
    "GetWindowThreadProcessId",
    "IsIconic",
    "IsWindowVisible",
    "SetForegroundWindow",
    "SetTransientFor",
    "ShowWindow",
    "WS_EX_TOOLWINDOW",
    "is_available",
]
