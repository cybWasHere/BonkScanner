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


class X11WindowKeySenderHoldTests(unittest.TestCase):
    def make_sender(self, *, focus_id: int, on_sleep=None):
        connection = FakeConnection(focus_id)
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if on_sleep is not None:
                on_sleep(connection, sleeps)

        sender = x11_key_sender.X11WindowKeySender(
            lambda: GAME_WINDOW, focus_settle_seconds=0.4, sleep=sleep, connection=connection,
        )
        return sender, connection, sleeps

    def test_uninterrupted_hold_is_one_press_for_the_full_duration(self) -> None:
        sender, connection, sleeps = self.make_sender(focus_id=0x200000)

        sender.hold("r", 0.2)

        self.assertEqual(
            event_kinds(connection),
            [xevent.FocusIn, xevent.KeyPress, xevent.KeyRelease, xevent.FocusOut],
        )
        self.assertAlmostEqual(sum(sleeps) - 0.4, 0.2)

    def test_alt_tabbing_away_mid_hold_restarts_the_hold_with_fake_focus(self) -> None:
        def lose_focus_once(connection, sleeps):
            if len(sleeps) == 2:  # second poll slice of the first attempt
                connection.display().focus_id = 0x200000

        sender, connection, _ = self.make_sender(focus_id=GAME_WINDOW, on_sleep=lose_focus_once)

        sender.hold("r", 0.2)

        self.assertEqual(
            event_kinds(connection),
            [
                xevent.KeyPress, xevent.KeyRelease,                                  # interrupted, really focused
                xevent.FocusIn, xevent.KeyPress, xevent.KeyRelease, xevent.FocusOut,  # redone unfocused
            ],
        )

    def test_focus_that_never_settles_is_an_error_not_a_silent_miss(self) -> None:
        def flip_focus(connection, sleeps):
            display = connection.display()
            display.focus_id = 0x200000 if display.focus_id == GAME_WINDOW else GAME_WINDOW

        sender, _, _ = self.make_sender(focus_id=GAME_WINDOW, on_sleep=flip_focus)

        with self.assertRaises(x11_key_sender.X11KeySendError):
            sender.hold("r", 0.2)


class RecordingKeyboard:
    def __init__(self, name: str, log: list) -> None:
        self._name = name
        self._log = log

    def press(self, key) -> None:
        self._log.append((self._name, "press", key))

    def release(self, key) -> None:
        self._log.append((self._name, "release", key))


class RecordingSender(RecordingKeyboard):
    def hold(self, key, seconds) -> None:
        self._log.append((self._name, "hold", key, seconds))


class GameKeyboardTests(unittest.TestCase):
    def test_everything_goes_to_the_window_sender_while_enabled(self) -> None:
        log: list = []
        keyboard = x11_key_sender.GameKeyboard(
            RecordingSender("x11", log), RecordingKeyboard("uinput", log), enabled=lambda: True,
        )

        keyboard.hold("r", 1.05)
        keyboard.press("esc")
        keyboard.release("esc")

        self.assertEqual(
            log, [("x11", "hold", "r", 1.05), ("x11", "press", "esc"), ("x11", "release", "esc")],
        )

    def test_disabled_falls_back_to_uinput_and_release_follows_its_press(self) -> None:
        log: list = []
        enabled = {"value": False}
        keyboard = x11_key_sender.GameKeyboard(
            RecordingSender("x11", log), RecordingKeyboard("uinput", log), enabled=lambda: enabled["value"],
        )

        keyboard.press("r")
        enabled["value"] = True  # setting flipped mid-hold
        keyboard.release("r")

        self.assertEqual(log, [("uinput", "press", "r"), ("uinput", "release", "r")])


class KeyboardRunControlProviderHoldTests(unittest.TestCase):
    def test_restart_run_uses_the_backend_hold_when_there_is_one(self) -> None:
        from infra.keyboard_run_control import KeyboardRunControlProvider

        log: list = []
        provider = KeyboardRunControlProvider(
            RecordingSender("x11", log), reset_hotkey="r", reset_hold_duration=1.05,
            sleep=lambda seconds: log.append(("slept", seconds)),
        )

        provider.restart_run()

        self.assertEqual(log, [("x11", "hold", "r", 1.05)])

    def test_restart_run_still_presses_and_releases_a_plain_backend(self) -> None:
        from infra.keyboard_run_control import KeyboardRunControlProvider

        log: list = []
        provider = KeyboardRunControlProvider(
            RecordingKeyboard("uinput", log), reset_hotkey="r", reset_hold_duration=1.05,
            sleep=lambda seconds: log.append(("slept", seconds)),
        )

        provider.restart_run()

        self.assertEqual(log, [("uinput", "press", "r"), ("slept", 1.05), ("uinput", "release", "r")])


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
