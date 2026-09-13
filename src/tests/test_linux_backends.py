"""Unit tests for the Linux backends: /proc process access, key names, input glue.

Everything here runs on any platform: the modules are imported, but the
system calls they wrap are replaced with fakes or fed canned input.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from infra.memory import linux_process
from infra.memory.reader import ProcessMemory


class ProcessNameMatchingTests(unittest.TestCase):
    def test_exact_argv0_basename_matches_case_insensitively(self) -> None:
        self.assertTrue(linux_process.process_name_matches("Megabonk.x86_64", "Megabonk.x86_6", "megabonk.x86_64"))

    def test_wine_argv0_matches_on_basename(self) -> None:
        self.assertTrue(linux_process.process_name_matches("Megabonk.exe", "Megabonk.exe", "Megabonk.exe"))

    def test_truncated_comm_matches_long_names_on_prefix(self) -> None:
        # comm holds 15 bytes; a 16-character name still has to match.
        self.assertTrue(linux_process.process_name_matches("SomeLongGameName.x86_64", "SomeLongGameNam", ""))
        self.assertFalse(linux_process.process_name_matches("Other.x86_64", "SomeLongGameNam", ""))

    def test_empty_target_never_matches(self) -> None:
        self.assertFalse(linux_process.process_name_matches("", "anything", "anything"))

    def test_find_process_ids_reads_comm_and_cmdline_from_a_proc_tree(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for pid, comm, argv0 in (
                (41, "bash", "/bin/bash"),
                (42, "Megabonk.x86_64", "/games/Megabonk.x86_64"),
                (43, "wine", r"Z:\games\Megabonk.exe"),
            ):
                proc = Path(root) / str(pid)
                proc.mkdir()
                (proc / "comm").write_text(comm + "\n")
                (proc / "cmdline").write_bytes(argv0.encode() + b"\0-arg\0")
            (Path(root) / "self").mkdir()
            self.assertEqual([42], linux_process.find_process_ids("Megabonk.x86_64", proc_root=root))
            self.assertEqual([43], linux_process.find_process_ids("megabonk.exe", proc_root=root))
            self.assertEqual([], linux_process.find_process_ids("Nope.exe", proc_root=root))


MAPS = """\
7f3274600000-7f3276335000 r--p 00000000 00:ae 171701   /mnt/games/Megabonk/GameAssembly.so
7f3276335000-7f3278000000 r-xp 01d35000 00:ae 171701   /mnt/games/Megabonk/GameAssembly.so
7f3278000000-7f3278100000 rw-p 00000000 00:00 0
7ffd1c000000-7ffd1c021000 rw-p 00000000 00:00 0        [stack]
6ffff6d10000-6ffff6d11000 r--p 00000000 00:ae 138756   /mnt/games/Megabonk/UnityPlayer.dll
"""


class MapsParsingTests(unittest.TestCase):
    def test_file_backed_mappings_are_parsed_with_paths(self) -> None:
        mappings = linux_process.parse_maps(MAPS.splitlines())
        self.assertEqual(3, len(mappings))
        self.assertEqual((0x7F3274600000, 0x7F3276335000, "/mnt/games/Megabonk/GameAssembly.so"), mappings[0])

    def test_module_base_is_the_lowest_mapping_and_size_spans_the_image(self) -> None:
        module = linux_process.module_from_maps(linux_process.parse_maps(MAPS.splitlines()), "GameAssembly.so")
        assert module is not None
        self.assertEqual(0x7F3274600000, module.lpBaseOfDll)
        self.assertEqual(0x7F3278000000 - 0x7F3274600000, module.SizeOfImage)

    def test_dll_name_finds_the_so_and_vice_versa(self) -> None:
        mappings = linux_process.parse_maps(MAPS.splitlines())
        self.assertEqual(0x7F3274600000, linux_process.module_from_maps(mappings, "GameAssembly.dll").lpBaseOfDll)
        self.assertEqual(0x6FFFF6D10000, linux_process.module_from_maps(mappings, "UnityPlayer.so").lpBaseOfDll)

    def test_unknown_module_is_none(self) -> None:
        self.assertIsNone(linux_process.module_from_maps(linux_process.parse_maps(MAPS.splitlines()), "Other.dll"))


class FakeLinuxProcess:
    def __init__(self) -> None:
        self.process_id = 4242
        self.process_handle = 4242
        self.reads: list[tuple[int, int]] = []

    def read_bytes(self, address: int, size: int) -> bytes:
        self.reads.append((address, size))
        return bytes(range(size))

    def close_process(self) -> None:
        pass


class ReaderIntegrationTests(unittest.TestCase):
    def test_reader_uses_the_injected_process_and_module_lookup(self) -> None:
        fake = FakeLinuxProcess()

        def lookup(handle, name):
            return linux_process.ModuleInfo(name, "/x/" + name, 0x1000, 0x100)

        reader = ProcessMemory("Megabonk.x86_64", _pm=fake, _module_from_name=lookup)
        self.assertEqual(0x1010, reader.module_offset("GameAssembly.so", 0x10))
        self.assertEqual(b"\x00\x01\x02\x03", reader.read_bytes(0x1010, 4))
        self.assertEqual([(0x1010, 4)], fake.reads)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process backend")
    def test_missing_process_raises_process_not_found(self) -> None:
        from infra.memory.reader import ProcessNotFoundError

        with self.assertRaises(ProcessNotFoundError):
            ProcessMemory("definitely-not-a-running-process-name.exe")


class KeyNameTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            from infra import linux_keyboard
        except ImportError:  # pragma: no cover
            self.skipTest("python-evdev not installed")
        if linux_keyboard.ecodes is None:
            self.skipTest("python-evdev not installed")
        self.kb = linux_keyboard

    def test_letters_digits_and_function_keys(self) -> None:
        from evdev import ecodes

        self.assertEqual((ecodes.KEY_R,), self.kb.key_to_scan_codes("r"))
        self.assertEqual((ecodes.KEY_6,), self.kb.key_to_scan_codes("6"))
        self.assertEqual((ecodes.KEY_F6,), self.kb.key_to_scan_codes("F6"))
        self.assertEqual((ecodes.KEY_HOME,), self.kb.key_to_scan_codes("home"))

    def test_modifiers_expand_to_both_sides(self) -> None:
        from evdev import ecodes

        self.assertEqual((ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT), self.kb.key_to_scan_codes("shift"))
        self.assertEqual((ecodes.KEY_LEFTSHIFT,), self.kb.key_to_scan_codes("left shift"))

    def test_mouse_buttons_are_named_like_the_map_marker_bindings(self) -> None:
        from evdev import ecodes

        self.assertEqual((ecodes.BTN_MIDDLE,), self.kb.key_to_scan_codes("mouse_middle"))
        self.assertEqual((ecodes.BTN_SIDE,), self.kb.key_to_scan_codes("mouse4"))

    def test_parse_hotkey_has_the_keyboard_package_shape(self) -> None:
        from evdev import ecodes

        parsed = self.kb.parse_hotkey("ctrl+f6, r")
        self.assertEqual(2, len(parsed))
        self.assertEqual(((ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL), (ecodes.KEY_F6,)), parsed[0])
        self.assertEqual(((ecodes.KEY_R,),), parsed[1])

    def test_unknown_name_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            self.kb.key_to_scan_codes("no such key")

    def test_hotkey_dispatch_requires_every_key_and_fires_on_the_trigger(self) -> None:
        from evdev import ecodes

        keyboard = self.kb.LinuxKeyboard(device_filter=lambda _device: False)
        fired: list[str] = []
        events: list[tuple[str, int]] = []
        with keyboard._lock:
            keyboard._hooks.append(lambda event: events.append((event.event_type, event.scan_code)))
            keyboard._hotkeys.append((self.kb.parse_hotkey("ctrl+f6"), lambda: fired.append("hotkey")))
        keyboard._dispatch(ecodes.KEY_F6, "down")
        self.assertEqual([], fired)
        keyboard._dispatch(ecodes.KEY_F6, "up")
        keyboard._dispatch(ecodes.KEY_LEFTCTRL, "down")
        keyboard._dispatch(ecodes.KEY_F6, "down")
        self.assertEqual(["hotkey"], fired)
        self.assertEqual(("down", ecodes.KEY_F6), events[-1])
        self.assertTrue(keyboard.is_pressed("ctrl"))


class MapMarkerInputTests(unittest.TestCase):
    def test_linux_input_reads_modifiers_and_cursor_from_its_collaborators(self) -> None:
        from infra.map_marker_input import LinuxMapMarkerInput

        class FakeKeyboard:
            pressed = {"left ctrl", "mouse_middle"}

            def is_pressed(self, name: str) -> bool:
                if name == "no such key":
                    raise ValueError(name)
                return name in self.pressed

        reader = LinuxMapMarkerInput(keyboard=FakeKeyboard(), cursor=lambda: (12, 34))
        self.assertTrue(reader.is_pressed("ctrl+mouse_middle"))
        self.assertFalse(reader.is_pressed("shift+mouse_middle"))
        self.assertFalse(reader.is_pressed("no such key"))
        self.assertEqual((12, 34), reader.cursor_position())

    def test_linux_input_degrades_to_inert_when_collaborators_fail(self) -> None:
        from infra.map_marker_input import LinuxMapMarkerInput

        def broken_cursor():
            raise OSError("no display")

        reader = LinuxMapMarkerInput(keyboard=object(), cursor=broken_cursor)
        reader._keyboard = None
        self.assertFalse(reader.is_pressed("f9"))
        self.assertEqual((0, 0), reader.cursor_position())


class PtraceHintTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc/self/status")
    def test_hint_is_none_or_text(self) -> None:
        hint = linux_process.ptrace_permission_hint()
        self.assertTrue(hint is None or "ptrace" in hint)
        if os.geteuid() == 0:
            self.assertIsNone(hint)


if __name__ == "__main__":
    unittest.main()


class OffsetTableTests(unittest.TestCase):
    def test_table_is_chosen_by_module_extension(self) -> None:
        from infra.memory import offsets

        self.assertEqual("windows", offsets.table_name_for_module("GameAssembly.dll"))
        self.assertEqual("linux", offsets.table_name_for_module("GameAssembly.so"))
        self.assertEqual("linux", offsets.table_name_for_module("gameassembly.SO"))

    def test_both_tables_name_the_same_classes(self) -> None:
        from infra.memory import offsets

        self.assertEqual(set(offsets.WINDOWS), set(offsets.LINUX))
        self.assertTrue(all(isinstance(v, int) and v > 0 for v in offsets.LINUX.values()))

    def test_apply_overrides_instance_attributes_from_the_resolved_module(self) -> None:
        from infra.memory import offsets

        class Client:
            TYPE_INFO_CLASSES = {"GAME_MANAGER_TYPE_INFO_OFFSET": "GameManager"}
            GAME_MANAGER_TYPE_INFO_OFFSET = offsets.WINDOWS["GameManager"]

        class LinuxMemory:
            def resolved_module_name(self, name: str) -> str:
                return "gameassembly.so"

        client = Client()
        self.assertEqual("linux", offsets.apply_type_info_offsets(client, LinuxMemory(), "GameAssembly.dll"))
        self.assertEqual(offsets.LINUX["GameManager"], client.GAME_MANAGER_TYPE_INFO_OFFSET)
        self.assertEqual(offsets.WINDOWS["GameManager"], Client.GAME_MANAGER_TYPE_INFO_OFFSET)

    def test_memory_without_a_resolver_keeps_the_windows_table(self) -> None:
        from infra.memory import offsets

        class Client:
            TYPE_INFO_CLASSES = {"TYPE_INFO_OFFSET": "InteractablesStatus"}
            TYPE_INFO_OFFSET = 0

        client = Client()
        self.assertEqual("windows", offsets.apply_type_info_offsets(client, object(), "GameAssembly.dll"))
        self.assertEqual(offsets.WINDOWS["InteractablesStatus"], client.TYPE_INFO_OFFSET)

    def test_every_client_constant_is_covered_by_its_mapping(self) -> None:
        from infra.memory import offsets
        from infra.memory.game_data_client import GameDataClient
        from infra.memory.map_marker_client import MapMarkerMemoryClient as MapMarkerClient
        from infra.memory.player_stats_client import PlayerStatsClient

        for client_type in (GameDataClient, MapMarkerClient, PlayerStatsClient):
            constants = {n for n in vars(client_type) if n.endswith("TYPE_INFO_OFFSET")}
            mapping = client_type.TYPE_INFO_CLASSES
            self.assertEqual(constants, set(mapping), client_type.__name__)
            for attribute, key in mapping.items():
                self.assertEqual(offsets.WINDOWS[key], getattr(client_type, attribute), f"{client_type.__name__}.{attribute}")


class GameConfigPathTests(unittest.TestCase):
    @unittest.skipUnless(os.name != "nt", "Linux path resolution")
    def test_native_unity_path_is_first_and_used_when_present(self) -> None:
        from app import config as app_config
        from unittest import mock

        with tempfile.TemporaryDirectory() as home:
            native = Path(home) / ".config" / "unity3d" / "Ved" / "Megabonk" / "Saves" / "LocalDir" / "config.json"
            native.parent.mkdir(parents=True)
            native.write_text("{}")
            with mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": ""}):
                candidates = app_config.linux_game_config_candidates()
                self.assertEqual(str(native), candidates[0])
                self.assertEqual(str(native), app_config.get_game_config_path())

    @unittest.skipUnless(os.name != "nt", "Linux path resolution")
    def test_newest_existing_candidate_wins(self) -> None:
        from app import config as app_config
        from unittest import mock

        with tempfile.TemporaryDirectory() as home:
            native = Path(home) / ".config" / "unity3d" / app_config.GAME_CONFIG_RELATIVE_PATH
            proton = (Path(home) / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / app_config.MEGABONK_STEAM_APP_ID
                      / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "LocalLow" / app_config.GAME_CONFIG_RELATIVE_PATH)
            for path in (native, proton):
                path.parent.mkdir(parents=True)
                path.write_text("{}")
            os.utime(native, (1_000_000, 1_000_000))
            os.utime(proton, (2_000_000, 2_000_000))
            with mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": ""}):
                self.assertEqual(str(proton), app_config.get_game_config_path())

    @unittest.skipUnless(os.name != "nt", "Linux path resolution")
    def test_missing_files_fall_back_to_the_native_path(self) -> None:
        from app import config as app_config
        from unittest import mock

        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": ""}):
                path = app_config.get_game_config_path()
                self.assertTrue(path and path.startswith(os.path.join(home, ".config", "unity3d")))


class ProcessNameVariantTests(unittest.TestCase):
    def test_variants_include_the_native_linux_spelling(self) -> None:
        from infra import process

        variants = process.process_name_variants("Megabonk.exe")
        self.assertIn("megabonk.exe", variants)
        if os.name != "nt":
            self.assertIn("megabonk.x86_64", variants)

    def test_empty_name_has_no_variants(self) -> None:
        from infra import process

        self.assertEqual(frozenset(), process.process_name_variants(""))
