"""
Validates an existing follower-style plugin: are its masters all available,
does its NPC_ record have what a working follower actually needs, does every
cross-plugin FormID it carries (race, class, head parts, spells) point at a
master that's genuinely listed and active, and does a FaceGenData mesh/
texture exist where the game would actually look for one. Works on ANY
.esp/.esm -- one you built here, or one you downloaded -- not just this
app's own output.

Every issue is filed under exactly one of two buckets, because that's the
distinction that actually matters to someone looking at the report:
  - "broken"  -- something is there but wrong: a corrupt record, a FormID
                 pointing at a master index that doesn't exist, a spell
                 count that doesn't match its entries. Fixing this means
                 editing the plugin itself.
  - "missing" -- something isn't there at all: no race set, no voice type,
                 a master that isn't active, a FaceGenData file that was
                 never copied in. Fixing this usually means adding
                 something (enable a mod, copy a file, pick a value) rather
                 than repairing the plugin.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from core import esp_reader
from core.esp_format import RECORD_HEADER_SIZE, RawRecord, cstring, iter_subrecords

# Vanilla/Creation-Club masters live in the game's own Data folder, never
# inside an MO2 mod -- checked against game_data_dir instead of the active
# mod list.
_VANILLA_PREFIXES = ("skyrim.esm", "update.esm", "dawnguard.esm", "hearthfires.esm", "dragonborn.esm", "cc")


@dataclass
class Issue:
    category: str   # "broken" | "missing" | "info"
    field: str      # short label, e.g. "Race", "FaceGenData mesh" -- for grouping/scanning
    message: str


@dataclass
class ValidationReport:
    plugin_name: str
    masters: list[str] = field(default_factory=list)
    npc_count: int = 0
    issues: list[Issue] = field(default_factory=list)

    def broken(self) -> list[Issue]:
        return [i for i in self.issues if i.category == "broken"]

    def missing(self) -> list[Issue]:
        return [i for i in self.issues if i.category == "missing"]

    def info(self) -> list[Issue]:
        return [i for i in self.issues if i.category == "info"]

    def is_clean(self) -> bool:
        return not self.broken() and not self.missing()


def read_masters(plugin_path: str | Path) -> list[str]:
    """Reads just the TES4 record's MAST list -- no group scanning needed."""
    with open(plugin_path, "rb") as f:
        header = f.read(RECORD_HEADER_SIZE)
        if len(header) < RECORD_HEADER_SIZE:
            raise ValueError("File is too short to be a valid plugin.")
        tag, data_size = struct.unpack_from("<4sI", header, 0)
        if tag != b"TES4":
            raise ValueError(f"Not a valid plugin (expected a TES4 header, found {tag!r}).")
        body = f.read(data_size)
    return [cstring(sub.data) for sub in iter_subrecords(body) if sub.type == b"MAST"]


def _is_vanilla_master(name: str) -> bool:
    return name.lower().startswith(_VANILLA_PREFIXES)


def _active_plugin_names(instance) -> set[str]:
    return {p.lower() for p in instance.plugin_order} if instance is not None else set()


def _resolve_master_name(formid: int, masters: list[str]) -> str | None:
    index = formid >> 24
    return masters[index] if index < len(masters) else None


def validate_plugin(plugin_path: str | Path, instance=None, game_data_dir=None) -> ValidationReport:
    plugin_path = Path(plugin_path)
    report = ValidationReport(plugin_name=plugin_path.name)

    try:
        report.masters = read_masters(plugin_path)
    except Exception as exc:
        report.issues.append(Issue("broken", "Plugin header", f"Couldn't read this plugin's header: {exc}"))
        return report

    active = _active_plugin_names(instance)
    for master in report.masters:
        if _is_vanilla_master(master):
            if game_data_dir and not (Path(game_data_dir) / master).exists():
                report.issues.append(Issue("missing", "Master", f"'{master}' isn't in your game's Data folder -- check your game install path."))
            continue
        if instance is None:
            report.issues.append(Issue("info", "Master", f"'{master}' -- couldn't check (no MO2 load order loaded)."))
        elif master.lower() not in active:
            report.issues.append(Issue("missing", "Master", f"'{master}' isn't active in your current MO2 profile -- this plugin won't load without it."))

    try:
        npc_records = list(esp_reader.iter_records_in_group(plugin_path, b"NPC_"))
    except Exception as exc:
        report.issues.append(Issue("broken", "NPC_ record", f"Couldn't read this plugin's NPC_ records: {exc}"))
        return report

    report.npc_count = len(npc_records)
    if not npc_records:
        report.issues.append(Issue("missing", "NPC_ record", "No NPC_ record found -- this doesn't look like a follower plugin."))
        return report

    for npc in npc_records:
        _validate_npc(npc, report, instance, game_data_dir, plugin_path)

    return report


def _validate_npc(npc: RawRecord, report: ValidationReport, instance, game_data_dir, plugin_path: Path):
    masters = report.masters
    edid_data = npc.get(b"EDID")
    edid_str = cstring(edid_data) if edid_data else None
    label = edid_str or f"{npc.form_id:08X}"

    if not edid_data:
        report.issues.append(Issue("missing", "EDID", f"NPC {npc.form_id:08X} has no EDID."))
    if not npc.get(b"FULL"):
        report.issues.append(Issue("missing", "Display name", f"'{label}' has no FULL (display name) -- shows blank or as its EDID in-game."))
    if not npc.get(b"ACBS"):
        report.issues.append(Issue("broken", "ACBS", f"'{label}' is missing ACBS -- this record is likely corrupt."))
    if not npc.get(b"OBND"):
        report.issues.append(Issue("broken", "OBND", f"'{label}' is missing OBND (object bounds) -- this record is likely corrupt."))

    rnam = npc.get(b"RNAM")
    if not rnam:
        report.issues.append(Issue("missing", "Race", f"'{label}' has no race set -- likely to crash or fail to spawn."))
    else:
        formid = struct.unpack("<I", rnam)[0]
        if _resolve_master_name(formid, masters) is None:
            report.issues.append(Issue("broken", "Race", f"'{label}' race points at master index {formid >> 24}, but only {len(masters)} master(s) are listed -- broken reference."))

    cnam = npc.get(b"CNAM")
    if cnam:
        formid = struct.unpack("<I", cnam)[0]
        if _resolve_master_name(formid, masters) is None:
            report.issues.append(Issue("broken", "Class", f"'{label}' class points at master index {formid >> 24}, but only {len(masters)} master(s) are listed -- broken reference."))

    if not npc.get(b"VTCK"):
        report.issues.append(Issue("missing", "Voice type", f"'{label}' has no voice type set -- dialogue may be silent or use a default voice."))

    doft = npc.get(b"DOFT")
    if not doft:
        report.issues.append(Issue("missing", "Default outfit", f"'{label}' has no default outfit (DOFT) set -- she'll spawn with nothing equipped."))
    else:
        formid = struct.unpack("<I", doft)[0]
        if _resolve_master_name(formid, masters) is None:
            report.issues.append(Issue("broken", "Default outfit", f"'{label}' default outfit points at master index {formid >> 24}, but only {len(masters)} master(s) are listed -- broken reference."))

    pnam_list = npc.get_all(b"PNAM")
    if not pnam_list:
        report.issues.append(Issue("missing", "Head parts", f"'{label}' has no head parts at all -- the head may render as a default/vanilla shape."))
    else:
        for data in pnam_list:
            formid = struct.unpack("<I", data)[0]
            master = _resolve_master_name(formid, masters)
            if master is None:
                report.issues.append(Issue("broken", "Head parts", f"'{label}' has a head part pointing at master index {formid >> 24}, but only {len(masters)} master(s) are listed -- broken reference."))
            elif instance is not None and not _is_vanilla_master(master) and master.lower() not in _active_plugin_names(instance):
                report.issues.append(Issue("missing", "Head parts", f"'{label}' has a head part from '{master}', which isn't active in your load order."))

    spct_data = npc.get(b"SPCT")
    splo_list = npc.get_all(b"SPLO")
    declared = struct.unpack("<I", spct_data)[0] if spct_data else 0
    if spct_data and declared != len(splo_list):
        report.issues.append(Issue("broken", "Spells", f"'{label}' declares {declared} spell(s) (SPCT) but has {len(splo_list)} SPLO entries -- mismatched, likely corrupt."))
    elif splo_list and not spct_data:
        report.issues.append(Issue("broken", "Spells", f"'{label}' has {len(splo_list)} SPLO spell entries but no SPCT count -- mismatched, likely corrupt."))
    for data in splo_list:
        formid = struct.unpack("<I", data)[0]
        if _resolve_master_name(formid, masters) is None:
            report.issues.append(Issue("broken", "Spells", f"'{label}' has a spell pointing at master index {formid >> 24}, but only {len(masters)} master(s) are listed -- broken reference."))

    # --- FaceGenData -- the single most common real-world "follower looks
    # wrong" cause: the baked mesh/texture either exists somewhere the game
    # would find it, or it doesn't. ---
    if pnam_list:
        formid_hex = f"{npc.form_id:08X}"
        plugin_name = plugin_path.name
        rel_nif = Path("meshes") / "actors" / "character" / "FaceGenData" / "FaceGeom" / plugin_name / f"{formid_hex}.nif"
        rel_dds = Path("textures") / "actors" / "character" / "FaceGenData" / "FaceTint" / plugin_name / f"{formid_hex}.dds"

        search_roots = [plugin_path.parent]
        if instance is not None:
            search_roots += [m.path for m in instance.active_mods]
        if game_data_dir:
            search_roots.append(Path(game_data_dir))

        nif_found = any((root / rel_nif).exists() for root in search_roots)
        dds_found = any((root / rel_dds).exists() for root in search_roots)

        if not nif_found:
            report.issues.append(Issue("missing", "FaceGenData mesh", f"No FaceGenData mesh found for '{label}' ({rel_nif}) -- the head will render as a default/invisible shape in-game."))
        if not dds_found:
            report.issues.append(Issue("missing", "FaceGenData texture", f"No FaceGenData texture found for '{label}' ({rel_dds}) -- the face may look wrong even if the mesh is there."))
