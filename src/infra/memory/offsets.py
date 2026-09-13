"""IL2CPP type-info addresses for each build of the game.

Every memory client starts from ``GameAssembly + <TypeInfo slot>``: the slot
holds the ``Il2CppClass*`` of a game class, and from the class the static
fields follow.  The slot addresses are per binary.  The Windows build
(``GameAssembly.dll``, also what runs under Proton) and the native Linux build
(``GameAssembly.so``) are compiled from the same IL2CPP output, so the
*field* offsets used further down the chains are shared; only these entry
addresses differ.

The clients keep their Windows constants as class attributes (tests and the
recovery inventory read them there).  ``apply_type_info_offsets`` overrides
them on the instance once the process is open and the module's real name is
known, so a client attached to the ``.so`` walks the Linux table.

Regenerating the Linux column: run Il2CppDumper on ``GameAssembly.so`` with
``Megabonk_Data/il2cpp_data/Metadata/global-metadata.dat`` and read the
``<Class>_TypeInfo`` entries in ``script.json``; ``tools/verify_type_info.py``
checks a table against the running game.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

# Keys are the game classes as named in the IL2CPP dump (namespace dropped).
WINDOWS: dict[str, int] = {
    "InteractablesStatus": 0x2FB5E68,
    "GameManager": 0x2F9C1C0,
    "LoadingScreen": 0x2F55E20,
    "MapController": 0x2F58E08,
    "MapGenerationController": 0x2F59000,
    "MusicController": 0x2F617C8,
    "MyTime": 0x2F62398,
    "PlayerMovement": 0x2F6D670,
    "MyPlayer": 0x2F620F8,
    "UiManager": 0x2F9A528,
    "FullMapUi": 0x2F9AF30,
    "MoneyUtility": 0x02F5E0B0,
    "RunStats": 0x02F7A170,
    "RunUnlockables": 0x02F7A210,
    "DataManager": 0x02F85790,
    "Potato": 0x02F6FC78,
    "RsgController": 0x02F79E50,
    "AchievementTracker": 0x02F69FE8,
    "ShrineLogs": 0x02F81B18,
    # The player-stats client does not start from a game singleton but from a
    # static ``Action<EStat>`` event whose bound target is the live
    # ``PlayerStatsNew``; offset 0x40 of an IL2CPP delegate is that target.
    "PlayerStatsRoot": 0x02F6A4B8,
}

# Native Linux build, Steam build 21750826 (verified against the running game
# on 2026-09-13: every slot resolved to an Il2CppClass whose name matched).
LINUX: dict[str, int] = {
    "InteractablesStatus": 0x515A300,
    "GameManager": 0x5158F98,
    "LoadingScreen": 0x515ADC8,
    "MapController": 0x515AFC0,
    "MapGenerationController": 0x515AFD8,
    "MusicController": 0x515B578,
    "MyTime": 0x515B608,
    "PlayerMovement": 0x515BE48,
    "MyPlayer": 0x515B5E8,
    "UiManager": 0x515E038,
    "FullMapUi": 0x5158EB8,
    "MoneyUtility": 0x515B3B0,
    "RunStats": 0x515C7D0,
    "RunUnlockables": 0x515C7D8,
    "DataManager": 0x5157EC8,
    "Potato": 0x515C018,
    "RsgController": 0x515C7A8,
    "AchievementTracker": 0x51569C8,
    "ShrineLogs": 0x515CD68,
    # ItemInventory.A_StatsChanged.  StatInventory.A_StatsChanged (0x515D1C8),
    # PassiveAbility.A_StatModified (0x515BBF0) and
    # PlayerStatusEffects.A_StatusModifiedStat (0x515BE78) bind the same
    # target and would serve equally.
    "PlayerStatsRoot": 0x515A610,
}

TABLES: dict[str, Mapping[str, int]] = {"windows": WINDOWS, "linux": LINUX}


def table_name_for_module(module_name: str) -> str:
    """``GameAssembly.so`` -> ``linux``; anything else is the Windows image."""

    return "linux" if os.path.splitext(module_name.strip())[1].lower() == ".so" else "windows"


def table_for_module(module_name: str) -> Mapping[str, int]:
    return TABLES[table_name_for_module(module_name)]


def resolved_module_name(memory: Any, module_name: str) -> str:
    """The module's real file name in the target, when the reader can tell."""

    resolver = getattr(memory, "resolved_module_name", None)
    if not callable(resolver):
        return module_name
    try:
        resolved = resolver(module_name)
    except Exception:
        return module_name
    return str(resolved) if resolved else module_name


def apply_type_info_offsets(client: Any, memory: Any, module_name: str) -> str:
    """Override a client's ``*_TYPE_INFO_OFFSET`` attributes for the attached binary.

    ``client.TYPE_INFO_CLASSES`` maps attribute names to table keys.  Returns
    the table name that was applied, for the log.
    """

    mapping = getattr(client, "TYPE_INFO_CLASSES", None) or {}
    name = table_name_for_module(resolved_module_name(memory, module_name))
    table = TABLES[name]
    for attribute, class_key in mapping.items():
        setattr(client, attribute, table[class_key])
    return name


__all__ = [
    "LINUX",
    "TABLES",
    "WINDOWS",
    "apply_type_info_offsets",
    "resolved_module_name",
    "table_for_module",
    "table_name_for_module",
]
