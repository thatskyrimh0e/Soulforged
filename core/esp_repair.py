"""
Attempts a conservative, safe repair of specific *broken* issues the
validator (core/esp_validator.py) finds in a follower plugin -- not a
general xEdit replacement, and not a way to restore a plugin to its
original look. It only touches what's provably unsalvageable as-is and
replaces it with something safe:

  - RNAM (race) pointing at a master index that doesn't exist -> reset to
    a safe default race (NordRace from Skyrim.esm, the same default
    core/follower_builder.py itself uses) so the NPC can actually spawn
    instead of crashing.
  - CNAM (class) pointing at a master index that doesn't exist -> dropped.
    No class override is a legitimate, common state for an NPC_ record.
  - PNAM (head part) entries pointing at a master index that doesn't
    exist -> dropped individually (valid ones are kept). They were
    already unresolvable -- nothing could ever render them -- and
    FaceGenData being missing (a separate, unfixable "missing" issue)
    already means the head can't render its intended look regardless.
  - SPLO (spell) entries pointing at a master index that doesn't exist,
    or an SPCT count that doesn't match the SPLO entries present -> the
    bad entries are dropped and SPCT is recomputed to match what's left.

Everything else in the file -- every other record, every other group, and
even every other subrecord on a record that DOES get touched -- is copied
through byte-for-byte unchanged. Nothing "missing" (no FaceGenData, no
voice type, a master that isn't active, etc.) can be fixed this way --
those need the real files or a real choice from you, not a guess.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from core.esp_format import (
    FLAG_COMPRESSED, GROUP_HEADER_FMT, GROUP_HEADER_SIZE, RECORD_HEADER_SIZE,
    RawRecord, Subrecord, read_record_at,
)
from core import esp_reader


@dataclass
class RepairResult:
    ok: bool
    message: str
    fixes: list[str] = field(default_factory=list)
    unfixable: list[str] = field(default_factory=list)
    output_path: str | None = None


def _resolve_master_name(formid: int, masters: list[str]) -> str | None:
    index = formid >> 24
    return masters[index] if index < len(masters) else None


def _find_top_level_group(raw: bytes, group_label: bytes):
    """Returns (group_header_start, data_start, data_end) for one top-level
    GRUP in an in-memory buffer, or None if it isn't present."""
    tes4_data_size = struct.unpack_from("<I", raw, 4)[0]
    pos = RECORD_HEADER_SIZE + tes4_data_size
    while pos < len(raw):
        if pos + GROUP_HEADER_SIZE > len(raw):
            break
        tag, group_size, label, group_type, *_ = struct.unpack_from(GROUP_HEADER_FMT, raw, pos)
        if tag != b"GRUP":
            break
        data_start = pos + GROUP_HEADER_SIZE
        data_end = pos + group_size
        if group_type == 0 and label == group_label:
            return pos, data_start, data_end
        pos = data_end
    return None


def _find_safe_race(masters: list[str], game_data_dir) -> int | None:
    """Looks up NordRace in Skyrim.esm (the same default
    core/follower_builder.py uses) and returns it re-encoded as a FormID
    local to THIS plugin's own master list. None if Skyrim.esm isn't a
    master here, or its Data-folder copy isn't available to look it up in."""
    try:
        skyrim_index = next(i for i, m in enumerate(masters) if m.lower() == "skyrim.esm")
    except StopIteration:
        return None
    if not game_data_dir:
        return None
    skyrim_path = Path(game_data_dir) / "Skyrim.esm"
    if not skyrim_path.exists():
        return None
    race = esp_reader.find_race_by_edid(skyrim_path, "NordRace")
    if race is None:
        return None
    return (skyrim_index << 24) | (race.form_id & 0xFFFFFF)


def repair_plugin(input_path: str | Path, output_path: str | Path, masters: list[str], game_data_dir=None) -> RepairResult:
    input_path = Path(input_path)
    output_path = Path(output_path)
    raw = input_path.read_bytes()

    group_loc = _find_top_level_group(raw, b"NPC_")
    if group_loc is None:
        return RepairResult(False, "No NPC_ group found in this plugin -- nothing to repair.")

    group_header_start, data_start, data_end = group_loc
    group_bytes = raw[data_start:data_end]

    safe_race_formid = _find_safe_race(masters, game_data_dir)

    fixes: list[str] = []
    unfixable: list[str] = []
    out_chunks: list[bytes] = []

    pos = 0
    while pos < len(group_bytes):
        start = pos
        record, next_pos = read_record_at(group_bytes, pos)
        pos = next_pos

        edid_data = record.get(b"EDID")
        from core.esp_format import cstring
        label = cstring(edid_data) if edid_data else f"{record.form_id:08X}"

        new_subs = list(record.subrecords)
        changed = False

        # --- Race ---
        rnam = record.get(b"RNAM")
        if rnam:
            formid = struct.unpack("<I", rnam)[0]
            if _resolve_master_name(formid, masters) is None:
                if safe_race_formid is not None:
                    for i, s in enumerate(new_subs):
                        if s.type == b"RNAM":
                            new_subs[i] = Subrecord(b"RNAM", struct.pack("<I", safe_race_formid))
                    changed = True
                    fixes.append(f"'{label}': reset broken race reference to NordRace (Skyrim.esm).")
                else:
                    unfixable.append(f"'{label}': race reference is broken, but couldn't resolve a safe fallback (need your game's Skyrim.esm available).")

        # --- Class ---
        cnam = record.get(b"CNAM")
        if cnam:
            formid = struct.unpack("<I", cnam)[0]
            if _resolve_master_name(formid, masters) is None:
                new_subs = [s for s in new_subs if s.type != b"CNAM"]
                changed = True
                fixes.append(f"'{label}': dropped a broken class reference.")

        # --- Head parts (PNAM) ---
        pnam_entries = [s for s in new_subs if s.type == b"PNAM"]
        if pnam_entries:
            dropped = 0
            kept_subs = []
            for s in new_subs:
                if s.type == b"PNAM":
                    formid = struct.unpack("<I", s.data)[0]
                    if _resolve_master_name(formid, masters) is None:
                        dropped += 1
                        continue
                kept_subs.append(s)
            if dropped:
                new_subs = kept_subs
                changed = True
                fixes.append(f"'{label}': dropped {dropped} broken head part reference(s).")

        # --- Spells (SPCT/SPLO) ---
        splo_entries = [s for s in new_subs if s.type == b"SPLO"]
        spct_entry = next((s for s in new_subs if s.type == b"SPCT"), None)
        if splo_entries or spct_entry:
            valid_splo = []
            dropped_spells = 0
            for s in splo_entries:
                formid = struct.unpack("<I", s.data)[0]
                if _resolve_master_name(formid, masters) is None:
                    dropped_spells += 1
                else:
                    valid_splo.append(s)
            declared = struct.unpack("<I", spct_entry.data)[0] if spct_entry else 0
            if dropped_spells or declared != len(valid_splo):
                new_subs = [s for s in new_subs if s.type not in (b"SPCT", b"SPLO")]
                if valid_splo:
                    new_subs.append(Subrecord(b"SPCT", struct.pack("<I", len(valid_splo))))
                    new_subs.extend(valid_splo)
                changed = True
                if dropped_spells:
                    fixes.append(f"'{label}': dropped {dropped_spells} broken spell reference(s).")
                else:
                    fixes.append(f"'{label}': fixed a spell count mismatch (SPCT vs. actual entries).")

        if changed:
            new_record = RawRecord(type=record.type, flags=record.flags & ~FLAG_COMPRESSED, form_id=record.form_id, subrecords=new_subs)
            out_chunks.append(new_record.to_bytes())
        else:
            out_chunks.append(group_bytes[start:pos])  # untouched -- copied verbatim

        if not record.get(b"ACBS"):
            unfixable.append(f"'{label}': missing ACBS -- this record is corrupt in a way that can't be safely guessed at.")
        if not record.get(b"OBND"):
            unfixable.append(f"'{label}': missing OBND -- this record is corrupt in a way that can't be safely guessed at.")

    new_group_body = b"".join(out_chunks)
    new_group_header = struct.pack(
        GROUP_HEADER_FMT, b"GRUP", GROUP_HEADER_SIZE + len(new_group_body), b"NPC_", 0, 0, 0, 0,
    )

    new_raw = raw[:group_header_start] + new_group_header + new_group_body + raw[data_end:]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(new_raw)

    if not fixes:
        return RepairResult(True, "No auto-fixable broken references were found -- nothing needed changing.", fixes, unfixable, str(output_path))

    message = f"Applied {len(fixes)} fix(es)."
    if unfixable:
        message += f" {len(unfixable)} other issue(s) couldn't be safely auto-fixed."
    return RepairResult(True, message, fixes, unfixable, str(output_path))
