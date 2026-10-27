"""
Builds a default-outfit (OTFT) record for a follower and wires it onto her
NPC_ via DOFT -- so a built follower actually spawns wearing something,
instead of whatever bare/default body the game falls back to with no
default outfit set at all. This was a real functional gap: nothing else in
this app ever touched DOFT, so every follower built before this came out
with no default outfit set.

OTFT's binary shape here was confirmed the same way every other format in
this app was -- by directly decoding real OTFT records out of the user's own
Skyrim.esm, not guessed from docs:
  - EDID (editor id, standard cstring subrecord).
  - Exactly ONE INAM subrecord, holding N*4 bytes: one packed FormID per
    outfit piece (e.g. a cuirass + boots + gloves all in the SAME INAM
    subrecord), NOT one INAM subrecord per item as some wiki pages describe.
    Checked a spread of real OTFT records with 1, 2, 3, 4, 5, and 6 items --
    every one was a single INAM sized exactly 4x its item count.
  - NPC_'s DOFT subrecord is a plain 4-byte FormID pointing at an OTFT
    record's own FormID -- confirmed by cross-referencing real NPC_ DOFT
    values against the OTFT FormIDs decoded above (e.g. an NPC's
    DOFT of 0x10FE82 lines up exactly with the real "MQ304StormcloakOutfit"
    OTFT record's own FormID).

What this does NOT do: it doesn't create new ARMO/ARMA records or any new
armor mesh/texture. It builds a fresh OTFT that references ARMO records the
user ALREADY has active in their load order (picked in the Skills tab,
resolved the same donor-then-load-order way every other EDID'd field in this
app resolves), which is the honest, buildable version of "give this
follower a starting outfit" -- actually authoring new wearable assets from
scratch isn't something this app (or Creation Kit, for that matter) can do
without real mesh/texture work from a human.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from core.esp_format import RawRecord, Subrecord, pack_cstring

# Doesn't collide with NEW_RECORD_LOCAL_FORMID (0x800) or
# core/follower_placement.py's HOLDING_CELL/ACHR/QUST local FormIDs
# (0x801-0x803) -- every "thing this app writes fresh into its own plugin"
# local FormID is tracked here in one place for exactly that reason.
OUTFIT_LOCAL_FORMID = 0x804


@dataclass
class OutfitBuildResult:
    ok: bool
    message: str
    otft_group: bytes | None = None
    otft_self_formid: int | None = None  # fully-encoded FormID, for the NPC's own DOFT


def build_outfit_record(plugin_stem: str, armor_formids: list[int]) -> RawRecord:
    """armor_formids are already fully-encoded (master-index << 24 | local),
    same convention as everywhere else in this app -- the caller (see
    core/follower_builder.py) is responsible for adding each item's owning
    plugin as a master and computing that encoding before calling this."""
    edid = f"{plugin_stem}_DefaultOutfit"
    inam_data = b"".join(struct.pack("<I", fid) for fid in armor_formids)
    return RawRecord(type=b"OTFT", flags=0, form_id=OUTFIT_LOCAL_FORMID, subrecords=[
        Subrecord(b"EDID", pack_cstring(edid)),
        Subrecord(b"INAM", inam_data),
    ])
