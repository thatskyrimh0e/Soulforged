"""
Builds a follower NPC_ record and writes it into a brand new plugin --
directly, as bytes, with no xEdit or Creation Kit involved. This replaces
core/xedit_bridge.py's old "drive xEdit via a script + MO2 launch" approach
entirely (no external editor dependency at runtime).

What this can and can't do, honestly:
  - Clones a donor NPC_ record (by default, the Player's own base record --
    same safe, always-present template used before) and patches: EDID,
    FULL (name), RNAM (race), the ACBS sex flag, Head Parts (PNAM) from a
    .jslot, and Tint Layers (makeup/skin tint) from a .jslot.
  - Resolves a race by EDID: checks the donor plugin first (covers every
    vanilla race, since the donor is Skyrim.esm), and falls back to
    scanning the active load order's RACE records for a custom race mod.
  - Checks every head-part plugin a .jslot references against the active
    load order (core/mo2_reader) before adding it as a master -- a head
    part from a plugin that isn't active gets skipped with a warning
    instead of silently producing a broken master reference.
  - Sets weight (NAM7, confirmed by direct inspection against a real
    Skyrim.esm record -- decoded exactly to a plausible float value).
  - Does NOT set hair color (HCLF). That needs either a nearest-match
    lookup against Skyrim's ~200 vanilla hair-color FormIDs (data this app
    doesn't have authoritative access to) or a confirmed binary layout for
    a different field this app hasn't verified -- a wrong guess risks a
    genuinely corrupt record, so it's left as the donor's default. Adjust
    manually in xEdit/in-game if needed.
  - Does NOT (and can't) reproduce a .jslot's "morphs" (sculpt-tool vertex
    edits / extended SKEE sliders) -- see core/jslot_reader.py. That's the
    same limitation CK's own FaceGen bake has; core/facegen_copy.py's
    "copy an exported head" path is still the only way to get that part
    pixel-perfect.
  - Builds a default outfit (OTFT) and wires it onto DOFT if spec.outfit_items
    is given -- see core/outfit_builder.py. Before this, every built follower
    had no default outfit set at all (a real functional gap, not polish).
"""
from __future__ import annotations

import datetime
import struct
from dataclasses import dataclass, field
from pathlib import Path

from core import esp_reader, esp_writer, jslot_reader, mo2_reader, follower_placement, outfit_builder
from core.esp_format import RawRecord, Subrecord, pack_cstring

DEFAULT_DONOR_PLUGIN = "Skyrim.esm"
DEFAULT_DONOR_FORMID = 0x00000007  # Player
NEW_RECORD_LOCAL_FORMID = 0x800

ACBS_FEMALE_FLAG = 0x1

# High Poly Head's shape is captured once in the exported head mesh/texture
# (core/facegen_copy.py) -- the game renders a humanoid NPC from that baked
# file, not by re-deriving the shape from PNAM at runtime. So there's no
# need to keep a live reference to it, and every other reason this app used
# to care about ordering (bake-before-strip, via Creation Kit) goes away
# entirely: head parts from these plugins are just never written.
EXCLUDED_MASTER_PLUGINS = {"high poly head.esm", "high poly head.esp"}


@dataclass
class BuildSpec:
    output_plugin_path: str          # full path to write, e.g. "E:\\...\\Data\\MyFollower.esp"
    name: str
    race_edid: str = "NordRace"
    sex: str = "Female"
    donor_plugin_path: str = ""      # resolved absolute path to the donor plugin (e.g. Skyrim.esm)
    jslot_path: str | None = None
    exclude_hph_master: bool = True  # see EXCLUDED_MASTER_PLUGINS above
    class_edid: str | None = None    # CLAS EDID, e.g. "CombatMage" -- None leaves the donor's class
    skill_values: list[int] | None = None  # 18 ints, core.skill_data.SKILL_NAMES order -- None leaves the donor's
    spell_refs: list[tuple[str, str]] | None = None  # [(plugin_filename, local_form_id_hex), ...] -- None leaves the donor's spells; [] strips them to zero
    outfit_items: list[tuple[str, str]] | None = None  # [(plugin_filename, local_form_id_hex), ...] of ARMO pieces -- see core/outfit_builder.py; None/[] leaves her with no default outfit
    location_cell_edid: str | None = None  # see core/follower_placement.py -- None skips automatic placement entirely


@dataclass
class BuildResult:
    ok: bool
    message: str
    warnings: list[str] = field(default_factory=list)
    new_formid: str | None = None    # hex local form id, e.g. "00000800" -- for facegen_copy.py


def _patch_acbs_sex(acbs_data: bytes, female: bool) -> bytes:
    flags = struct.unpack_from("<I", acbs_data, 0)[0]
    flags = (flags | ACBS_FEMALE_FLAG) if female else (flags & ~ACBS_FEMALE_FLAG)
    return struct.pack("<I", flags) + acbs_data[4:]


def _resolve_race(donor_plugin_path: str, race_edid: str, instance: mo2_reader.MO2Instance | None, warnings: list[str]):
    """Returns (local_form_id, plugin_filename) or None."""
    race = esp_reader.find_race_by_edid(donor_plugin_path, race_edid)
    if race:
        return race.form_id, Path(donor_plugin_path).name

    if instance is None:
        warnings.append(f"Race '{race_edid}' not found in {Path(donor_plugin_path).name}, and no load order to search further -- leaving the donor's race.")
        return None

    donor_name_lower = Path(donor_plugin_path).name.lower()
    plugin_paths = mo2_reader.resolve_plugin_paths(instance)
    for plugin_name in instance.plugin_order:
        if plugin_name.lower() == donor_name_lower:
            continue
        resolved = plugin_paths.get(plugin_name.lower())
        if not resolved:
            continue
        try:
            race = esp_reader.find_race_by_edid(resolved, race_edid)
        except Exception:
            continue
        if race:
            return race.form_id, plugin_name

    warnings.append(f"Race '{race_edid}' wasn't found in your donor plugin or anywhere in your active load order -- leaving the donor's race unchanged.")
    return None


def _resolve_by_edid(donor_plugin_path: str, group_label: bytes, edid: str, instance, warnings: list[str], kind_label: str):
    """Same donor-first-then-active-load-order pattern as _resolve_race, for
    any EDID'd record type (used here for CLAS and SPEL). Returns
    (local_form_id, plugin_filename) or None.

    Resolves every plugin's path with ONE pass over the active mods
    (mo2_reader.resolve_plugin_paths) instead of calling resolve_file() once
    per plugin in the loop below -- that per-call version is O(active_mods)
    EACH time, so across ~1000+ plugins it used to take 60-90s+ and, since
    this whole function runs on the GUI thread during Export, froze the
    window solid for that long. See core/skill_data.py for the same fix
    applied to the Skills-tab scans.
    """
    record = esp_reader.find_record_by_edid(donor_plugin_path, group_label, edid)
    if record:
        return record.form_id, Path(donor_plugin_path).name

    if instance is None:
        warnings.append(f"{kind_label} '{edid}' not found in {Path(donor_plugin_path).name}, and no load order to search further.")
        return None

    donor_name_lower = Path(donor_plugin_path).name.lower()
    plugin_paths = mo2_reader.resolve_plugin_paths(instance)
    for plugin_name in instance.plugin_order:
        if plugin_name.lower() == donor_name_lower:
            continue
        resolved = plugin_paths.get(plugin_name.lower())
        if not resolved:
            continue
        try:
            record = esp_reader.find_record_by_edid(resolved, group_label, edid)
        except Exception:
            continue
        if record:
            return record.form_id, plugin_name

    warnings.append(f"{kind_label} '{edid}' wasn't found in your donor plugin or anywhere in your active load order.")
    return None


def build_follower(spec: BuildSpec, instance: mo2_reader.MO2Instance | None = None) -> BuildResult:
    warnings: list[str] = []

    donor_plugin_path = spec.donor_plugin_path
    if not donor_plugin_path or not Path(donor_plugin_path).exists():
        return BuildResult(False, f"Donor plugin not found at: {donor_plugin_path}")

    donor_record = esp_reader.find_record_by_local_formid(donor_plugin_path, b"NPC_", DEFAULT_DONOR_FORMID)
    if donor_record is None:
        return BuildResult(False, f"Couldn't find the donor NPC_ record ({DEFAULT_DONOR_FORMID:08X}) in {donor_plugin_path}.")

    donor_plugin_name = Path(donor_plugin_path).name
    masters = [donor_plugin_name]  # donor MUST be master index 0 -- see module docstring

    # Start from a full copy of the donor's subrecords, then drop the ones
    # we're about to fully replace (so we don't leave the donor's own head
    # parts/tints mixed in alongside the new ones).
    subrecords = [s for s in donor_record.subrecords if s.type not in (b"PNAM", b"TINI", b"TINC", b"TINV", b"TIAS")]

    def replace_first(sub_type: bytes, new_data: bytes):
        for i, s in enumerate(subrecords):
            if s.type == sub_type:
                subrecords[i] = Subrecord(sub_type, new_data)
                return
        subrecords.append(Subrecord(sub_type, new_data))

    npc_edid = spec.name.replace(" ", "") + "NPC"
    replace_first(b"EDID", pack_cstring(npc_edid))
    replace_first(b"FULL", pack_cstring(spec.name))

    acbs_data = donor_record.get(b"ACBS")
    if acbs_data and len(acbs_data) >= 4:
        replace_first(b"ACBS", _patch_acbs_sex(acbs_data, spec.sex.lower() == "female"))
    else:
        warnings.append("Donor record had no ACBS subrecord -- sex flag wasn't set.")

    race_result = _resolve_race(donor_plugin_path, spec.race_edid, instance, warnings)
    if race_result:
        race_formid, race_plugin = race_result
        if race_plugin not in masters:
            masters.append(race_plugin)
        race_master_index = masters.index(race_plugin)
        final_race_formid = (race_master_index << 24) | (race_formid & 0xFFFFFF)
        replace_first(b"RNAM", struct.pack("<I", final_race_formid))

    # --- Head parts + tints from the imported .jslot ---
    if spec.jslot_path:
        try:
            jdata = jslot_reader.parse_jslot(spec.jslot_path)
        except Exception as exc:
            jdata = None
            warnings.append(f"Couldn't read the imported face preset: {exc}")

        if jdata:
            active_plugins_lower = {p.lower() for p in instance.plugin_order} if instance else None

            excluded_hph_count = 0
            for hp in jdata.head_parts:
                plugin_lower = hp.plugin.lower()
                if spec.exclude_hph_master and plugin_lower in EXCLUDED_MASTER_PLUGINS:
                    excluded_hph_count += 1
                    continue
                if active_plugins_lower is not None and plugin_lower not in active_plugins_lower and plugin_lower != donor_plugin_name.lower():
                    warnings.append(f"Skipped a head part from '{hp.plugin}' -- that plugin isn't active in your load order.")
                    continue
                if hp.plugin not in masters:
                    masters.append(hp.plugin)
                master_index = masters.index(hp.plugin)
                try:
                    local_id = int(hp.form_id_hex, 16)
                except ValueError:
                    warnings.append(f"Skipped a head part with an unreadable form ID: {hp.form_id_hex!r}")
                    continue
                final_formid = (master_index << 24) | (local_id & 0xFFFFFF)
                subrecords.append(Subrecord(b"PNAM", struct.pack("<I", final_formid)))

            if excluded_hph_count:
                warnings.append(
                    f"Excluded {excluded_hph_count} head part(s) from High Poly Head -- its shape is "
                    "already captured once you copy the exported head (next step), so this plugin "
                    "doesn't need to be a master."
                )

            for tint in jdata.tints:
                subrecords.append(Subrecord(b"TINI", struct.pack("<H", tint.index)))
                subrecords.append(Subrecord(b"TINC", bytes((tint.red, tint.green, tint.blue, tint.alpha))))
                subrecords.append(Subrecord(b"TINV", struct.pack("<f", tint.alpha / 255.0)))
                # TIAS's real meaning isn't confirmed (not documented anywhere
                # I have access to, and the donor's own placeholder tints
                # didn't make its purpose obvious either) -- 0 is a neutral
                # value, and since TINC carries an explicit custom color,
                # this shouldn't matter for how the color actually renders.
                subrecords.append(Subrecord(b"TIAS", struct.pack("<H", 0)))

            if jdata.weight is not None:
                replace_first(b"NAM7", struct.pack("<f", float(jdata.weight)))

    # --- Class (CNAM) ---
    if spec.class_edid:
        class_result = _resolve_by_edid(donor_plugin_path, b"CLAS", spec.class_edid, instance, warnings, "Class")
        if class_result:
            class_formid, class_plugin = class_result
            if class_plugin not in masters:
                masters.append(class_plugin)
            class_master_index = masters.index(class_plugin)
            final_class_formid = (class_master_index << 24) | (class_formid & 0xFFFFFF)
            replace_first(b"CNAM", struct.pack("<I", final_class_formid))

    # --- Per-skill levels (DNAM) -- only the first 18 bytes (skill values)
    # are touched; everything else in the donor's 52-byte DNAM (skill
    # offsets, health/magicka/stamina, and the still-undecoded tail) is
    # preserved exactly as-is. ---
    if spec.skill_values:
        dnam_data = donor_record.get(b"DNAM")
        if dnam_data and len(dnam_data) >= 18:
            dnam = bytearray(dnam_data)
            for i, value in enumerate(spec.skill_values[:18]):
                dnam[i] = max(0, min(255, int(value)))
            replace_first(b"DNAM", bytes(dnam))
        else:
            warnings.append("Donor record had no usable DNAM subrecord -- skill levels weren't set.")

    # --- Spells (SPCT + SPLO) -- the donor's own spells (e.g. the Player's
    # personal spells) are never appropriate for a generic follower, so they
    # are always stripped here; spec.spell_refs (if given) replaces them. ---
    subrecords = [s for s in subrecords if s.type not in (b"SPCT", b"SPLO")]
    if spec.spell_refs:
        spell_formids = []
        for spell_plugin, spell_formid_hex in spec.spell_refs:
            if spell_plugin not in masters:
                masters.append(spell_plugin)
            spell_master_index = masters.index(spell_plugin)
            try:
                local_id = int(spell_formid_hex, 16)
            except ValueError:
                warnings.append(f"Skipped a spell with an unreadable form ID: {spell_formid_hex!r}")
                continue
            spell_formids.append((spell_master_index << 24) | (local_id & 0xFFFFFF))
        if spell_formids:
            subrecords.append(Subrecord(b"SPCT", struct.pack("<I", len(spell_formids))))
            for formid in spell_formids:
                subrecords.append(Subrecord(b"SPLO", struct.pack("<I", formid)))

    # --- Default outfit (OTFT + DOFT) -- the donor's own DOFT (if the
    # Player record even has one) isn't appropriate for a generic follower,
    # same reasoning as stripping the donor's spells above, so it's always
    # dropped and only rebuilt if spec.outfit_items is given. See
    # core/outfit_builder.py for how OTFT's binary shape was confirmed. ---
    subrecords = [s for s in subrecords if s.type != b"DOFT"]
    outfit_group = None
    if spec.outfit_items:
        armor_formids = []
        for armor_plugin, armor_formid_hex in spec.outfit_items:
            if armor_plugin not in masters:
                masters.append(armor_plugin)
            armor_master_index = masters.index(armor_plugin)
            try:
                local_id = int(armor_formid_hex, 16)
            except ValueError:
                warnings.append(f"Skipped an outfit item with an unreadable form ID: {armor_formid_hex!r}")
                continue
            armor_formids.append((armor_master_index << 24) | (local_id & 0xFFFFFF))
        if armor_formids:
            # Reference the OTFT record the exact same way the NPC_ record's
            # OWN header FormID is written just above -- a raw local id, top
            # byte 0, no master-count prefix. This deliberately matches
            # NEW_RECORD_LOCAL_FORMID's existing convention (confirmed
            # in-game via this app's own prior builds, e.g. VervainFollower.esp)
            # rather than core/follower_placement.py's different
            # (len(masters)<<24)-prefixed convention for ITS fresh records
            # (CELL/ACHR/QUST) -- those two subsystems disagree with each
            # other on this, and since the OTFT record lives in the SAME file
            # as the NPC_ record referencing it, this follows the one that
            # record itself already uses, rather than guessing which
            # convention is "more correct" and risking a reference that's
            # inconsistent with its own file's main record. See this build's
            # own warnings/summary for a note that this disagreement exists
            # and is worth checking against a real, in-game load.
            outfit_self_formid = outfit_builder.OUTFIT_LOCAL_FORMID
            plugin_stem = Path(spec.output_plugin_path).stem
            otft_record = outfit_builder.build_outfit_record(plugin_stem, armor_formids)
            outfit_group = esp_writer.wrap_top_group(b"OTFT", otft_record.to_bytes())
            subrecords.append(Subrecord(b"DOFT", struct.pack("<I", outfit_self_formid)))

    new_record = RawRecord(type=b"NPC_", flags=0, form_id=NEW_RECORD_LOCAL_FORMID, subrecords=subrecords)
    groups = [esp_writer.wrap_top_group(b"NPC_", new_record.to_bytes())]
    if outfit_group is not None:
        groups.append(outfit_group)
        warnings.append(f"Built a default outfit from {len(armor_formids)} item(s) and wired it onto DOFT.")

    quest_formid = None
    output_dir = Path(spec.output_plugin_path).parent
    plugin_stem = Path(spec.output_plugin_path).stem
    if spec.location_cell_edid:
        placement = follower_placement.build_placement(
            NEW_RECORD_LOCAL_FORMID, masters, spec.location_cell_edid, donor_plugin_path, plugin_stem,
        )
        if placement.ok:
            groups.extend(placement.groups)
            quest_formid = placement.quest_formid
        else:
            warnings.append(f"Couldn't place her at '{spec.location_cell_edid}': {placement.message}")

    try:
        esp_writer.write_plugin(spec.output_plugin_path, masters, groups, num_records=sum(1 for _ in groups))
    except Exception as exc:
        return BuildResult(False, f"Failed writing the plugin: {exc}", warnings=warnings)

    if quest_formid is not None:
        try:
            follower_placement.copy_spawn_script(output_dir)
            follower_placement.write_seq_file(output_dir, plugin_stem, quest_formid)
            warnings.append(f"Placed at '{spec.location_cell_edid}' -- she'll move there automatically the first time this save loads.")
        except Exception as exc:
            warnings.append(f"Built the placement quest, but couldn't finish packaging it: {exc}")

    message = f"Wrote {Path(spec.output_plugin_path).name} with masters: {', '.join(masters)}."
    if warnings:
        message += f" ({len(warnings)} warning(s), see below.)"

    credited_plugins = [m for m in masters if m != donor_plugin_name]
    plugin_name = Path(spec.output_plugin_path).name
    _write_mod_folder_extras(Path(spec.output_plugin_path).parent, credited_plugins, plugin_name, npc_edid)

    return BuildResult(ok=True, message=message, warnings=warnings, new_formid=f"{NEW_RECORD_LOCAL_FORMID:08X}")


def _write_mod_folder_extras(output_dir, credited_plugins, plugin_name, npc_edid):
    """
    Rounds the output folder out so it looks like a normal finished mod the
    moment it's built -- a meta.ini MO2 recognizes, and a credits.md listing
    whatever other plugins contributed head parts/tints/race.
    """
    meta_lines = [
        "[General]",
        "gameName=",
        "modid=0",
        "version=" + datetime.date.today().strftime("d%Y.%m.%d"),
        "newestVersion=",
        "category=0",
        "nexusFileStatus=1",
        "installationFile=",
        "repository=",
    ]
    meta_path = output_dir / "meta.ini"
    if not meta_path.exists():
        meta_path.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")

    credits_lines = [
        "# Credits",
        "",
        "Portable packages may contain assets created by other authors. Confirm "
        "that you have permission before distributing this follower.",
        "",
        "## Third-Party Asset Providers",
        "",
    ]
    if credited_plugins:
        credits_lines += ["- " + p for p in credited_plugins]
    else:
        credits_lines.append("- None beyond the base game.")
    (output_dir / "credits.md").write_text("\n".join(credits_lines) + "\n", encoding="utf-8")

    # SPID (Spell Perk Item Distributor) ini, scoped to just this NPC's own
    # EDID, so Racial Skin Variance (if the user has it) leaves this
    # follower's imported skin/head texture alone instead of overwriting it
    # with RSV's own per-race textures. Harmless without SPID or RSV
    # installed -- SPID just skips a keyword it can't resolve.
    distr_lines = [
        "; Generated by Soulforged.",
        "; Applies Racial Skin Variance's RSVignore keyword (RSV v2.0+) so this",
        "; follower keeps the skin/head texture it was built with instead of",
        "; receiving RSV's per-race substitute.",
        "; Safe without SPID (file is ignored) or without RSV (SPID skips the",
        "; unresolvable keyword).",
        f"Keyword = RSVignore|{npc_edid}",
    ]
    distr_name = Path(plugin_name).stem + "_DISTR.ini"
    (output_dir / distr_name).write_text("\n".join(distr_lines) + "\n", encoding="utf-8")

