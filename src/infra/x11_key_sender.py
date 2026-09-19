"""Key injection into one X11 window that does not need the window focused.

``infra.linux_keyboard`` injects through uinput, which the compositor routes to
whichever window has focus.  That is why auto-reroll used to stop as soon as
the game lost focus: the reset key would have landed in the browser.

An X11 client can be handed key events directly with ``XSendEvent``, and the
native Unity player accepts them -- but only while it believes it is focused.
Unfocused, the events arrive and the game drops them.  Its idea of focus comes
from ``FocusIn``/``FocusOut``, which can be sent the same way, so a press here
is: ``FocusIn``, a short settle, ``KeyPress``; and a release is ``KeyRelease``
then ``FocusOut``.  The window manager never sees those events.

One catch: on a ``FocusIn`` the player asks the window manager to activate its
window, and a permissive focus-stealing-prevention level grants that, pulling
real focus away from whatever is in use.  The window manager has to refuse.  On
KDE that is a window rule forcing focus stealing prevention to Extreme for
window class ``Megabonk.x86_64`` (exact case -- KWin 6 does not lowercase it);
see the README.  Clicking or alt-tabbing to the game is unaffected.  Moving the
real X input focus instead is no way round this: KWin activates the window
within ~20 ms.

X keycodes on an evdev-backed server (Xorg and XWayland alike) are the evdev
code plus 8, so key names resolve through ``linux_keyboard.key_to_scan_codes``
and both backends accept exactly the same names.

``GameKeyboard`` is the piece run control uses: the ``press`` / ``release`` /
``press_and_release`` surface of the keyboard backend plus ``hold``, sent to the
game's window whether or not it is focused, with uinput as the fallback when
background rerolling is switched off.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from core.run_control import RunControlError
from infra import x11_windows
from infra.linux_keyboard import key_to_scan_codes

try:  # pragma: no cover - exercised on Linux only
    from Xlib import X
    from Xlib.protocol import event as xevent
except ImportError:  # pragma: no cover
    X = xevent = None


EVDEV_TO_X_KEYCODE_OFFSET = 8

# Gap between the FocusIn and the first key, so the player has processed the
# focus change before input arrives.  0.5 s and up worked in testing; shorter
# gaps are untested, so this errs long.  It is paid once per background reroll.
DEFAULT_FOCUS_SETTLE_SECONDS = 0.5

HOLD_FOCUS_POLL_SECONDS = 0.05
HOLD_RETRY_PAUSE_SECONDS = 0.15
HOLD_MAX_ATTEMPTS = 4


class X11KeySendError(RunControlError):
    """A ``RunControlError`` so a failed reset is logged, not raised through the scan loop."""


def is_available() -> bool:
    return X is not None and x11_windows.is_available()


class X11WindowKeySender:
    """Send key presses to one X11 window, focused or not."""

    def __init__(
        self,
        window_id: Callable[[], int | None],
        *,
        focus_settle_seconds: float = DEFAULT_FOCUS_SETTLE_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        connection: Any = None,
    ) -> None:
        self._window_id = window_id
        self._focus_settle_seconds = focus_settle_seconds
        self._sleep = sleep
        self._connection = connection or x11_windows._connection
        self._state_lock = threading.Lock()
        # Window we told "you are focused", and the keys held down in it.
        self._faked_focus_window: int | None = None
        self._held: dict[int, int] = {}

    def press(self, key: str | int) -> None:
        keycode = self._keycode(key)
        with self._state_lock:
            window_id = self._faked_focus_window or self._resolve_window()
            if self._faked_focus_window is None and not self._has_real_focus(window_id):
                self._send_focus(window_id, focused=True)
                self._faked_focus_window = window_id
                self._sleep(self._focus_settle_seconds)
            self._send_key(window_id, keycode, pressed=True)
            self._held[keycode] = window_id

    def release(self, key: str | int) -> None:
        keycode = self._keycode(key)
        with self._state_lock:
            window_id = self._held.pop(keycode, None)
            if window_id is None:
                return
            self._send_key(window_id, keycode, pressed=False)
            if not self._held and self._faked_focus_window is not None:
                faked = self._faked_focus_window
                self._faked_focus_window = None
                # If the game was really focused in the meantime, a FocusOut
                # now would make it deaf to the real keyboard.
                if not self._has_real_focus(faked):
                    self._send_focus(faked, focused=False)

    def press_and_release(self, key: str | int, *, hold_seconds: float = 0.05) -> None:
        self.press(key)
        try:
            self._sleep(hold_seconds)
        finally:
            self.release(key)

    def hold(self, key: str | int, seconds: float) -> None:
        """Keep ``key`` down for an uninterrupted ``seconds``.

        A real focus change in either direction makes the player forget the
        key (alt-tabbing away sends it a FocusOut; coming back makes it re-read
        the physical keyboard, where the key is up), which silently turns a
        hold-to-reset into nothing.  So the hold watches real focus and starts
        over when it moves instead of leaving the caller to time out.
        """
        for _ in range(HOLD_MAX_ATTEMPTS):
            window_id = self._faked_focus_window or self._resolve_window()
            focused_at_start = self._has_real_focus(window_id)
            interrupted = False
            self.press(key)
            try:
                remaining = seconds
                while remaining > 0:
                    step = min(HOLD_FOCUS_POLL_SECONDS, remaining)
                    self._sleep(step)
                    remaining -= step
                    if self._has_real_focus(window_id) != focused_at_start:
                        interrupted = True
                        break
            finally:
                self.release(key)
            if not interrupted:
                return
            # Let the real focus event land before faking the next one.
            self._sleep(HOLD_RETRY_PAUSE_SECONDS)
        raise X11KeySendError("Focus kept changing while the key was held.")

    @staticmethod
    def _keycode(key: str | int) -> int:
        return key_to_scan_codes(key)[0] + EVDEV_TO_X_KEYCODE_OFFSET

    def _resolve_window(self) -> int:
        window_id = self._window_id()
        if not window_id:
            raise X11KeySendError("The game window was not found.")
        return int(window_id)

    def _has_real_focus(self, window_id: int) -> bool:
        with self._connection.lock:
            try:
                focus = self._connection.display().get_input_focus().focus
                return int(getattr(focus, "id", 0) or 0) == int(window_id)
            except Exception:
                return False

    def _send_key(self, window_id: int, keycode: int, *, pressed: bool) -> None:
        kind = xevent.KeyPress if pressed else xevent.KeyRelease
        mask = X.KeyPressMask if pressed else X.KeyReleaseMask
        with self._connection.lock:
            try:
                display = self._connection.display()
                window = display.create_resource_object("window", window_id)
                window.send_event(
                    kind(
                        time=X.CurrentTime, root=display.screen().root, window=window,
                        same_screen=1, child=X.NONE, root_x=0, root_y=0,
                        event_x=1, event_y=1, state=0, detail=keycode,
                    ),
                    propagate=False,
                    event_mask=mask,
                )
                display.flush()
            except Exception as exc:
                self._connection.reset()
                raise X11KeySendError(f"Could not send the key to the game window: {exc}") from exc

    def _send_focus(self, window_id: int, *, focused: bool) -> None:
        kind = xevent.FocusIn if focused else xevent.FocusOut
        with self._connection.lock:
            try:
                display = self._connection.display()
                window = display.create_resource_object("window", window_id)
                window.send_event(
                    kind(window=window, detail=X.NotifyNonlinear, mode=X.NotifyNormal),
                    propagate=False,
                    event_mask=X.FocusChangeMask,
                )
                display.flush()
            except Exception as exc:
                self._connection.reset()
                raise X11KeySendError(f"Could not send the key to the game window: {exc}") from exc


class GameKeyboard:
    """The keyboard run control drives the game with.

    Every key goes to the game's window through ``sender`` while ``enabled()``
    says so, and through ``fallback`` (uinput) otherwise -- which still needs
    the game focused, as before.  Routing by focus instead was tried and is a
    trap: a hold that starts focused and is alt-tabbed away from finishes in
    whatever window came next.  A release follows the route of its press.
    """

    def __init__(self, sender: X11WindowKeySender, fallback: Any, *, enabled: Callable[[], bool]) -> None:
        self._sender = sender
        self._fallback = fallback
        self._enabled = enabled
        self._routes: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _route(self) -> Any:
        return self._sender if self._enabled() else self._fallback

    def press(self, key: str | int) -> None:
        route = self._route()
        with self._lock:
            self._routes[str(key)] = route
        route.press(key)

    def release(self, key: str | int) -> None:
        with self._lock:
            route = self._routes.pop(str(key), None)
        (route or self._route()).release(key)

    def press_and_release(self, key: str | int, *, hold_seconds: float = 0.05) -> None:
        self.press(key)
        try:
            time.sleep(hold_seconds)
        finally:
            self.release(key)

    def hold(self, key: str | int, seconds: float) -> None:
        route = self._route()
        if route is self._sender:
            self._sender.hold(key, seconds)
            return
        route.press(key)
        try:
            time.sleep(seconds)
        finally:
            route.release(key)
