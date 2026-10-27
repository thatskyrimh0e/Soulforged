"""
Places a built follower at a chosen location in the world: a tiny "holding
cell" the follower's ACHR starts in, a quest whose script teleports her from
there to a "spawn anchor" object already standing in the destination cell,
the first time the save loads this plugin.

Every binary detail here (the CELL block/sub-block/children nesting, the
holding cell's subrecords, the ACHR's DATA, the QUST's VMAD script-property
layout) was confirmed by directly decoding a real follower mod's own plugin
(see core/esp_cell_reader.py's docstring) -- not guessed from docs. The one
thing that's a genuine heuristic is WHICH existing object in the destination
cell gets used as the spawn anchor (core/esp_cell_reader.pick_anchor): it
just picks a pre-existing object already standing in the chosen cell, rather
than inventing a more precise placement mechanism this app has no way to
validate.

The spawn script itself (bundled as assets/SoulforgedFollowerSpawn.pex) is a
real, already-compiled Papyrus script reused byte-for-byte for its logic --
this app can't compile Papyrus without Creation Kit, so writing one from
scratch isn't an option. Its original donor name has been scrubbed out
directly in the compiled bytecode, though: the .pex format's own string
table (see the rename performed when this asset was bundled) stores the
script's class name, debug Trace() text, and compile-metadata (author/
machine) as plain length-prefixed strings referenced everywhere else by
TABLE INDEX rather than by raw byte content, so renaming those table
entries in place -- without touching the actual compiled instructions --
was a safe, structural edit, not a decompile/recompile. The filename and
the script-name string written into the QUST's VMAD record (see
_build_vmad below) are NOT cosmetic, though: Skyrim's script engine loads
a script by filename matching the class name baked into the compiled
bytecode, so both have to stay exactly "SoulforgedFollowerSpawn" or the
quest's script silently fails to attach at runtime.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from core import esp_cell_reader, esp_writer
from core.esp_format import GROUP_HEADER_FMT, Subrecord, RawRecord, pack_cstring

# (display name, interior cell EDID in Skyrim.esm) -- all confirmed to
# exist, and to already have at least one placeable object in them, by
# direct lookup against a real Skyrim.esm (see the module's own dev notes;
# not a guessed list).
CURATED_LOCATIONS: list[tuple[str, str]] = [
    ("Temple of Dibella (Markarth)", "MarkarthTempleofDibella"),
    ("Temple of Mara (Riften)", "RiftenTempleofMara"),
    ("Temple of the Divines (Solitude)", "SolitudeTempleoftheDivines"),
    ("Breezehome (Whiterun)", "WhiterunBreezehome"),
    ("Jorrvaskr (Whiterun)", "WhiterunJorrvaskr"),
    ("Dragonsreach (Whiterun)", "WhiterunDragonsreach"),
    ("Bannered Mare (Whiterun)", "WhiterunBanneredMare"),
    ("Sleeping Giant Inn (Riverwood)", "RiverwoodSleepingGiantInn"),
]

HOLDING_CELL_LOCAL_FORMID = 0x801
ACHR_LOCAL_FORMID = 0x802
QUST_LOCAL_FORMID = 0x803

# Lighting data copied verbatim from a real follower mod's holding cell -- the
# follower is never actually seen standing in this cell (she's moved out by
# script before the player could ever get there), so its exact values don't
# matter; only that a valid-shaped XCLL is present.
_HOLDING_CELL_XCLL = bytes.fromhex(
    "ffffff0000000000000000000000000000000000000000000000000000000000000000"
    "00000000803f18ff0a00e5fff300ff0aff00fff3ff007979730084848a0000000000000"
    "0803f000000000000803f00000000000000009f000000"
)


@dataclass
class PlacementResult:
    ok: bool
    message: str
    groups: list[bytes] | None = None
    quest_formid: int | None = None  # fully-encoded, for the .seq file


def _self_formid(masters: list[str], local_id: int) -> int:
    return (len(masters) << 24) | (local_id & 0xFFFFFF)


def _vmad_object_property(name: str, formid: int) -> bytes:
    name_bytes = name.encode("latin1")
    return (
        struct.pack("<H", len(name_bytes)) + name_bytes
        + bytes((1, 1))  # type=Object, flags=1 (matches the real donor quest)
        + bytes.fromhex("0000ffff")  # sentinel -- confirmed empirically, see module docstring
        + struct.pack("<I", formid)
    )


def build_placement(
    npc_local_formid: int,
    masters: list[str],
    location_cell_edid: str,
    skyrim_esm_path: str | Path,
    plugin_stem: str,
) -> PlacementResult:
    try:
        skyrim_index = next(i for i, m in enumerate(masters) if m.lower() == "skyrim.esm")
    except StopIteration:
        return PlacementResult(False, "Skyrim.esm isn't a master of this plugin -- can't place a follower without it.")

    match = esp_cell_reader.find_cell(skyrim_esm_path, location_cell_edid)
    if match is None:
        return PlacementResult(False, f"Couldn't find the cell '{location_cell_edid}' in your Skyrim.esm.")
    anchor = esp_cell_reader.pick_anchor(match.children)
    if anchor is None:
        return PlacementResult(False, f"'{location_cell_edid}' has nothing in it this app could use as a spawn point.")

    anchor_formid = (skyrim_index << 24) | (anchor.form_id & 0xFFFFFF)
    follower_achr_formid = _self_formid(masters, ACHR_LOCAL_FORMID)
    npc_formid = _self_formid(masters, npc_local_formid)
    cell_formid = _self_formid(masters, HOLDING_CELL_LOCAL_FORMID)
    quest_formid = _self_formid(masters, QUST_LOCAL_FORMID)

    # --- Holding cell + ACHR ---
    cell_record = RawRecord(type=b"CELL", flags=0, form_id=cell_formid, subrecords=[
        Subrecord(b"EDID", pack_cstring(f"{plugin_stem}_HoldingCell")),
        Subrecord(b"DATA", struct.pack("<H", 0x0001)),  # interior
        Subrecord(b"XCLL", _HOLDING_CELL_XCLL),
        Subrecord(b"LTMP", struct.pack("<I", 0)),
        Subrecord(b"XCLW", struct.pack("<f", 0.0)),
    ])
    achr_record = RawRecord(type=b"ACHR", flags=0x400, form_id=_self_formid(masters, ACHR_LOCAL_FORMID), subrecords=[
        Subrecord(b"NAME", struct.pack("<I", npc_formid)),
        Subrecord(b"DATA", b"\x00" * 26),  # position/rotation -- irrelevant, moved out immediately by script
    ])

    cell_local = HOLDING_CELL_LOCAL_FORMID
    block_label = cell_local % 10
    subblock_label = (cell_local // 10) % 10

    persistent_group = esp_writer.wrap_top_group(struct.pack("<I", cell_formid), achr_record.to_bytes())
    # type 8 = persistent children -- override the group_type field wrap_top_group defaults to 0.
    persistent_group = _retype_group(persistent_group, group_type=8)

    children_group = esp_writer.wrap_top_group(struct.pack("<I", cell_formid), persistent_group)
    children_group = _retype_group(children_group, group_type=6)

    subblock_body = cell_record.to_bytes() + children_group
    subblock_group = esp_writer.wrap_top_group(struct.pack("<i", subblock_label), subblock_body)
    subblock_group = _retype_group(subblock_group, group_type=3)

    block_group = esp_writer.wrap_top_group(struct.pack("<i", block_label), subblock_group)
    block_group = _retype_group(block_group, group_type=2)

    cell_top_group = esp_writer.wrap_top_group(b"CELL", block_group)

    # --- Quest ---
    vmad = (
        struct.pack("<HHH", 5, 2, 1)
        + struct.pack("<H", len("SoulforgedFollowerSpawn")) + b"SoulforgedFollowerSpawn"
        + bytes((0,))  # status
        + struct.pack("<H", 2)  # property count
        + _vmad_object_property("FollowerRef", follower_achr_formid)
        + _vmad_object_property("SpawnAnchor", anchor_formid)
    )
    quest_record = RawRecord(type=b"QUST", flags=0, form_id=quest_formid, subrecords=[
        Subrecord(b"EDID", pack_cstring(f"{plugin_stem}_SpawnQuest")),
        Subrecord(b"VMAD", vmad),
        Subrecord(b"DNAM", bytes.fromhex("010000ff0000000000000000")),  # priority/flags, copied from the real donor quest
        Subrecord(b"NEXT", b""),
        Subrecord(b"ANAM", struct.pack("<I", 0)),
    ])
    quest_top_group = esp_writer.wrap_top_group(b"QUST", quest_record.to_bytes())

    return PlacementResult(True, f"Placed at '{location_cell_edid}'.", groups=[cell_top_group, quest_top_group], quest_formid=quest_formid)


def _retype_group(group_bytes: bytes, group_type: int) -> bytes:
    """wrap_top_group always writes group_type=0; this patches that one
    field for the nested block/sub-block/children groups CELL placement
    needs, without needing a second group-building function."""
    header = list(struct.unpack_from(GROUP_HEADER_FMT, group_bytes, 0))
    header[3] = group_type
    new_header = struct.pack(GROUP_HEADER_FMT, *header)
    return new_header + group_bytes[len(new_header):]


def write_seq_file(output_dir: Path, plugin_stem: str, quest_formid: int) -> Path:
    """A .seq file just lists FormIDs (4 bytes each) of quests to auto-start
    on first load -- confirmed against a real mod's .seq file, which has one
    4-byte entry per auto-started quest."""
    seq_dir = Path(output_dir) / "Seq"
    seq_dir.mkdir(parents=True, exist_ok=True)
    seq_path = seq_dir / f"{plugin_stem}.seq"
    seq_path.write_bytes(struct.pack("<I", quest_formid))
    return seq_path


def copy_spawn_script(output_dir: Path) -> Path:
    from core.paths import get_root_dir
    src = get_root_dir() / "assets" / "SoulforgedFollowerSpawn.pex"
    dest_dir = Path(output_dir) / "Scripts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SoulforgedFollowerSpawn.pex"
    dest.write_bytes(src.read_bytes())
    return dest
