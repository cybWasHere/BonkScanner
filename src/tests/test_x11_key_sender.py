from __future__ import annotations

import src

import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if sys.platform == "win32":  # pragma: no cover - Linux-only backend
    raise unittest.SkipTest("X11 key sender is Linux-only.")

try:
    from infra import x11_key_sender
    from Xlib.protocol import event as xevent
except ImportError:  # pragma: no cover - python-xlib / evdev missing
    raise unittest.SkipTest("python-xlib and evdev are required.")

import gui_run_control

GAME_WINDOW = 0x3200008
KEY_R_X_KEYCODE = 19 + 8  # evdev KEY_R + 8


class FakeWindow:
    def __init__(self, window_id: int, sent: list) -> None:
        self.id = window_id
        self._sent = sent

    def __resource__(self) -> int:
        # python-xlib packs events eagerly and asks window fields for their id.
        return self.id

    __window__ = __resource__

    def send_event(self, event, propagate=False, event_mask=0) -> None:
        self._sent.append((self.id, event))


class FakeDisplay:
    def __init__(self, focus_id: int) -> None:
        self.focus_id = focus_id
        self.sent: list = []

    def create_resource_object(self, kind: str, window_id: int) -> FakeWindow:
        return FakeWindow(window_id, self.sent)

    def screen(self) -> SimpleNamespace:
        return SimpleNamespace(root=FakeWindow(1, self.sent))

    def get_input_focus(self) -> SimpleNamespace:
        return SimpleNamespace(focus=SimpleNamespace(id=self.focus_id))

    def flush(self) -> None:
        pass


class FakeConnection:
    def __init__(self, focus_id: int) -> None:
        self.lock = threading.RLock()
        self._display = FakeDisplay(focus_id)

    def display(self) -> FakeDisplay:
        return self._display

    def reset(self) -> None:
        pass


def event_kinds(connection: FakeConnection) -> list[type]:
    return [type(event) for _, event in connection.display().sent]


class X11WindowKeySenderTests(unittest.TestCase):
    def make_sender(self, *, focus_id: int, window=GAME_WINDOW):
        connection = FakeConnection(focus_id)
        sleeps: list[float] = []
        sender = x11_key_sender.X11WindowKeySender(
            lambda: window,
            focus_settle_seconds=0.4,
            sleep=sleeps.append,
            connection=connection,
        )
        return sender, connection, sleeps

    def test_unfocused_press_is_wrapped_in_fake_focus(self) -> None:
        sender, connection, sleeps = self.make_sender(focus_id=0x200000)

        sender.press("r")
        sender.release("r")

        self.assertEqual(
            event_kinds(connection),
            [xevent.FocusIn, xevent.KeyPress, xevent.KeyRelease, xevent.FocusOut],
        )
        self.assertEqual(sleeps, [0.4])
        targets = {window_id for window_id, _ in connection.display().sent}
        self.assertEqual(targets, {GAME_WINDOW})
        key_press = connection.display().sent[1][1]
        self.assertEqual(key_press.detail, KEY_R_X_KEYCODE)

    def test_really_focused_window_gets_no_fake_focus(self) -> None:
        sender, connection, sleeps = self.make_sender(focus_id=GAME_WINDOW)

        sender.press_and_release("esc", hold_seconds=0.05)

        self.assertEqual(event_kinds(connection), [xevent.KeyPress, xevent.KeyRelease])
        self.assertEqual(sleeps, [0.05])

    def test_focus_out_is_skipped_when_the_game_gained_real_focus_during_the_hold(self) -> None:
        sender, connection, _ = self.make_sender(focus_id=0x200000)

        sender.press("r")
        connection.display().focus_id = GAME_WINDOW
        sender.release("r")

        self.assertEqual(event_kinds(connection), [xevent.FocusIn, xevent.KeyPress, xevent.KeyRelease])

    def test_missing_window_raises(self) -> None:
        sender, connection, _ = self.make_sender(focus_id=0x200000, window=None)

        with self.assertRaises(x11_key_sender.X11KeySendError):
            sender.press("r")
        self.assertEqual(connection.display().sent, [])

    def test_release_without_press_sends_nothing(self) -> None:
        sender, connection, _ = self.make_sender(focus_id=0x200000)

        sender.release("r")

        self.assertEqual(connection.display().sent, [])


class RecordingKeyboard:
    def __init__(self, name: str, log: list) -> None:
        self._name = name
        self._log = log

    def press(self, key) -> None:
        self._log.append((self._name, "press", key))

    def release(self, key) -> None:
        self._log.append((self._name, "release", key))


class FocusAwareKeyboardTests(unittest.TestCase):
    def test_routes_by_focus_and_release_follows_its_press(self) -> None:
        log: list = []
        active = {"value": False}
        keyboard = x11_key_sender.FocusAwareKeyboard(
            RecordingKeyboard("uinput", log),
            RecordingKeyboard("x11", log),
            is_game_window_active=lambda: active["value"],
        )

        keyboard.press("r")
        active["value"] = True  # focus arrives mid-hold
        keyboard.release("r")
        keyboard.press("r")
        keyboard.release("r")

        self.assertEqual(
            log,
            [
                ("x11", "press", "r"),
                ("x11", "release", "r"),
                ("uinput", "press", "r"),
                ("uinput", "release", "r"),
            ],
        )


class RunControlUnfocusedGateTests(unittest.TestCase):
    def make_run_control(self, logs: list) -> gui_run_control.RunControl:
        return gui_run_control.RunControl(
            log=lambda message, tag=None: logs.append(message),
            schedule=lambda delay_ms, callback: None,
            client=lambda: None,
            abort_requested=lambda: True,
            toggle_scan=lambda: None,
            player_movement=lambda: None,
            toggle_recording=lambda: None,
            toggle_overlay_edit=None,
        )

    def test_focus_wait_passes_when_the_unfocused_game_can_be_driven(self) -> None:
        logs: list = []
        run_control = self.make_run_control(logs)
        run_control._game_keyboard = object()  # a router, i.e. not the plain backend
        with patch.object(run_control, "is_game_window_active", return_value=False), \
                patch.object(run_control, "find_game_window", return_value=GAME_WINDOW), \
                patch.dict(gui_run_control.config.user_config, {"RESET_WHEN_UNFOCUSED": True}):
            self.assertTrue(run_control.wait_for_game_window_focus("Megabonk.x86_64"))
            self.assertTrue(run_control.wait_for_game_window_focus("Megabonk.x86_64"))
            self.assertTrue(run_control.can_drive_game("Megabonk.x86_64"))

        self.assertEqual(len([line for line in logs if "background" in line]), 1)

    def test_focus_wait_still_blocks_when_the_setting_is_off(self) -> None:
        logs: list = []
        run_control = self.make_run_control(logs)
        run_control._game_keyboard = object()
        with patch.object(run_control, "is_game_window_active", return_value=False), \
                patch.object(run_control, "find_game_window", return_value=GAME_WINDOW), \
                patch.dict(gui_run_control.config.user_config, {"RESET_WHEN_UNFOCUSED": False}):
            # abort_requested is True, so the wait gives up at once: False.
            self.assertFalse(run_control.wait_for_game_window_focus("Megabonk.x86_64"))
            self.assertFalse(run_control.can_drive_game("Megabonk.x86_64"))

    def test_plain_keyboard_backend_cannot_drive_an_unfocused_game(self) -> None:
        run_control = self.make_run_control([])
        run_control._game_keyboard = gui_run_control.keyboard
        with patch.object(run_control, "find_game_window", return_value=GAME_WINDOW):
            self.assertFalse(run_control.can_drive_unfocused_game("Megabonk.x86_64"))


if __name__ == "__main__":
    unittest.main()
