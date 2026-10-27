"""
Skill scanning/constants for the Skills step: class + per-skill values +
spell list, written into an NPC_'s CNAM/DNAM/SPCT+SPLO subrecords.

SKILL_NAMES order and DONOR_SKILL_DEFAULTS are confirmed by directly
decoding the donor Player record's own DNAM subrecord in the user's real
Skyrim.esm: the first 18 bytes are skill values, and the specific numbers
(20 for One-Handed, 25 for Two-Handed, 20 for Light Armor, etc. -- a Nord's
vanilla racial skill bonuses layered over the universal base of 15) line up
exactly with this standard, well-documented skill order used throughout
Skyrim's data and every modding tool for it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core import esp_reader, mo2_reader
from core.esp_format import cstring

SKILL_NAMES = [
    "One-Handed", "Two-Handed", "Archery", "Block", "Smithing",
    "Heavy Armor", "Light Armor", "Pickpocket", "Lockpicking", "Sneak",
    "Alchemy", "Speechcraft", "Alteration", "Conjuration", "Destruction",
    "Illusion", "Restoration", "Enchanting",
]

# Plugin-filename keywords for well-known spell-adding mods -- used to scope
# "Scan Load Order for Spells" to actual magic mods instead of every active
# plugin (most plugins define a SPEL record or two incidentally -- quest
# items, scripted effects, follower abilities -- and scanning literally
# everything buried real spell mods under that noise and made the scan slow
# for no benefit). This is a convenience filter, not a restriction: a magic
# mod this list doesn't know about is still findable by name in the search
# box after an "include everything" scan.
MAGIC_MOD_KEYWORDS = [
    "apocalypse", "odin", "mysticism", "triumvirate", "summermyst",
    "phenderix", "forgotten magic", "forgottenmagic", "sacrosanct",
    "path of sorcery", "pathofsorcery", "thunderchild", "obscure",
    "arcanum", "elemental destruction", "spell research",
    "spellsword", "ordinator", "magic of skyrim", "spell knowledge",
    "spells", "spell pack", "magevolution", "wraithguard",
]

# The donor Player record's own values -- shown as the Skills tab's starting
# point so "touch nothing" reproduces exactly what building always used to do.
DONOR_SKILL_DEFAULTS = [20, 25, 15, 20, 20, 15, 20, 15, 15, 15, 15, 20, 15, 15, 15, 15, 15, 15]


@dataclass
class ScannedRecord:
    edid: str
    full_name: str | None
    plugin: str
    form_id_hex: str  # local form id within its OWN plugin, 8 hex chars


def _plugin_matches_keywords(plugin_name: str, keywords: list[str]) -> bool:
    lower = plugin_name.lower()
    return any(k in lower for k in keywords)


def _scan_group_across_load_order(instance, group_label: bytes, game_data_dir=None, plugin_filter=None) -> list[ScannedRecord]:
    """
    Resolving each of the load order's ~1000+ plugins one at a time through
    mo2_reader.resolve_file() is what made this scan time out (that function
    does its own O(active_mods) scan on every call -- multiplied across the
    whole load order that's well over a million directory checks on a big
    instance). Instead, build the plugin -> path map ONCE up front
    (mo2_reader.resolve_plugin_paths, a single pass over the active mods),
    plus a Data-folder fallback for vanilla masters like Skyrim.esm that
    normally live in the game install rather than inside any MO2 mod.
    """
    results: list[ScannedRecord] = []
    if instance is None:
        return results

    plugin_map = mo2_reader.resolve_plugin_paths(instance)

    plugin_names = instance.plugin_order
    if plugin_filter is not None:
        plugin_names = [p for p in plugin_names if plugin_filter(p)]

    for plugin_name in plugin_names:
        resolved = plugin_map.get(plugin_name.lower())
        if resolved is None and game_data_dir is not None:
            candidate = Path(game_data_dir) / plugin_name
            if candidate.exists():
                resolved = candidate
        if resolved is None:
            continue
        try:
            for record in esp_reader.iter_records_in_group(resolved, group_label):
                raw_edid = record.get(b"EDID")
                if raw_edid is None:
                    continue
                raw_full = record.get(b"FULL")
                results.append(ScannedRecord(
                    edid=cstring(raw_edid),
                    full_name=cstring(raw_full) if raw_full else None,
                    plugin=plugin_name,
                    form_id_hex=f"{record.form_id:08X}",
                ))
        except Exception:
            # A plugin this reader can't fully parse shouldn't kill the rest
            # of the scan -- just skip it.
            continue
    return results


def scan_classes(instance, game_data_dir=None) -> list[ScannedRecord]:
    """Every CLAS record across the active load order. Cheap -- plugins
    typically have few classes."""
    return _scan_group_across_load_order(instance, b"CLAS", game_data_dir)


def scan_spells(instance, game_data_dir=None, magic_mods_only: bool = True) -> list[ScannedRecord]:
    """SPEL records across the active load order. By default, scoped to
    plugins whose name matches a known magic-mod keyword (MAGIC_MOD_KEYWORDS)
    -- otherwise almost every plugin in a big load order contributes a
    stray SPEL record or two (quest effects, follower abilities) that bury
    the mods you actually meant to find. Pass magic_mods_only=False to scan
    every active plugin instead (slower, much noisier)."""
    plugin_filter = (lambda name: _plugin_matches_keywords(name, MAGIC_MOD_KEYWORDS)) if magic_mods_only else None
    return _scan_group_across_load_order(instance, b"SPEL", game_data_dir, plugin_filter=plugin_filter)


def scan_armors(instance, game_data_dir=None) -> list[ScannedRecord]:
    """ARMO records across the active load order -- candidates for a
    follower's default outfit (see core/outfit_builder.py). No keyword
    filter here, unlike scan_spells: armor/clothing mods are too varied to
    scope by plugin-name keyword the way magic mods can be, and ARMO is
    common enough across a big load order that this scan can take a real
    few seconds (same cost class as scan_spells with magic_mods_only=False)
    -- still fine since it already runs off the GUI thread."""
    return _scan_group_across_load_order(instance, b"ARMO", game_data_dir)
