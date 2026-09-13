"""Check the IL2CPP type-info table against the running game (Linux).

For every class in ``infra.memory.offsets`` the game's ``GameAssembly`` slot
is read from the live process, the ``Il2CppClass`` it points at is followed
to its name string, and the two names are compared.  A slot that still holds
a tagged metadata token (``0x2xxxxxxx``) is a class the game has not touched
yet -- start a run and re-check -- not a wrong address.

Usage (from the project root, with the game running)::

    .venv/bin/python3 tools/verify_type_info.py [--process Megabonk.x86_64] [--module GameAssembly.so]

With ``--script-json path/to/script.json`` (Il2CppDumper output for the same
binary) it also prints the slot address the dump has for each class, which is
how a new game build's column is filled in.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from infra.memory import linux_process, offsets  # noqa: E402

CLASS_NAME_POINTER_OFFSET = 0x10
DELEGATE_TARGET_OFFSET = 0x40
CLASS_STATIC_FIELDS_OFFSET = 0xB8

# The table key -> the IL2CPP class name the slot must resolve to.  The
# player-stats root is a static delegate, so its check is different.
EXPECTED_NAMES = {key: key for key in offsets.LINUX if key != "PlayerStatsRoot"}
EXPECTED_NAMES["PlayerStatsRoot"] = "ItemInventory"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--process", default="Megabonk.x86_64")
    parser.add_argument("--module", default="GameAssembly.so")
    parser.add_argument("--script-json", type=Path, default=None)
    args = parser.parse_args()

    try:
        process = linux_process.LinuxProcess(args.process)
    except (linux_process.ProcessNotFound, linux_process.CouldNotOpenProcess) as exc:
        print(f"cannot attach: {exc}")
        return 2
    module = linux_process.module_from_name(process.process_id, args.module)
    base = module.lpBaseOfDll
    table = offsets.table_for_module(module.name)
    print(f"pid {process.process_id}, {module.name} at 0x{base:X}, table '{offsets.table_name_for_module(module.name)}'")

    dumped: dict[str, int] = {}
    if args.script_json:
        data = json.loads(args.script_json.read_text())
        for entry in data.get("ScriptMetadata", []):
            name = entry.get("Name", "")
            if name.endswith("_TypeInfo"):
                dumped[name[:-9].rsplit(".", 1)[-1]] = int(entry["Address"])

    def read_ptr(address: int) -> int:
        raw = process.read_bytes(address, 8)
        return struct.unpack("<Q", raw)[0] if len(raw) == 8 else 0

    def read_cstring(address: int, limit: int = 96) -> str:
        raw = process.read_bytes(address, limit)
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace") if raw else ""

    def class_name(klass: int) -> str:
        try:
            return read_cstring(read_ptr(klass + CLASS_NAME_POINTER_OFFSET))
        except Exception:
            return ""

    problems = 0
    for key, slot in table.items():
        try:
            klass = read_ptr(base + slot)
        except Exception as exc:
            print(f"  {key:26s} slot 0x{slot:X}: read failed ({exc})")
            problems += 1
            continue
        expected = EXPECTED_NAMES[key]
        if klass and klass < 0x10000_0000:
            status = "not initialized yet (tagged token)"
        else:
            live = class_name(klass) if klass else ""
            if key == "PlayerStatsRoot" and live == expected:
                static_fields = read_ptr(klass + CLASS_STATIC_FIELDS_OFFSET)
                delegate = read_ptr(static_fields) if static_fields else 0
                target = read_ptr(delegate + DELEGATE_TARGET_OFFSET) if delegate else 0
                bound = class_name(read_ptr(target)) if target else ""
                status = f"ok ({live}; delegate target {bound or 'unbound: no run active'})"
            elif live == expected:
                status = f"ok ({live})"
            else:
                status = f"MISMATCH: live '{live}', expected '{expected}'"
                problems += 1
        dump_note = f"  dump 0x{dumped[expected]:X}" if expected in dumped else ""
        print(f"  {key:26s} slot 0x{slot:X}: {status}{dump_note}")

    print("problems:", problems)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
