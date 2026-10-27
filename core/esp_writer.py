"""
Writes a new, minimal Skyrim SE plugin containing exactly one record (our
built NPC_), with the right TES4 header and master list. No xEdit/CK
involved -- this is the direct replacement for xedit_bridge.py's old
"drive xEdit to clone+save a plugin" approach.
"""
from __future__ import annotations

import struct
from pathlib import Path

from core.esp_format import GROUP_HEADER_FMT, RawRecord, Subrecord, pack_cstring

SSE_VERSION = 1.71
DEFAULT_NEXT_OBJECT_ID = 0x800  # first free-ish local form id; our record uses its own explicit id anyway


def build_tes4(masters: list[str], num_records: int, author: str = "Soulforged") -> RawRecord:
    subrecords = [
        Subrecord(b"HEDR", struct.pack("<fII", SSE_VERSION, num_records, DEFAULT_NEXT_OBJECT_ID)),
        Subrecord(b"CNAM", pack_cstring(author)),
    ]
    for master in masters:
        subrecords.append(Subrecord(b"MAST", pack_cstring(master)))
        subrecords.append(Subrecord(b"DATA", struct.pack("<Q", 0)))
    return RawRecord(type=b"TES4", flags=0, form_id=0, subrecords=subrecords)


def wrap_top_group(label: bytes, body_bytes: bytes) -> bytes:
    """Wraps raw bytes (one record's bytes, or several records/nested
    groups concatenated -- e.g. core/follower_placement.py's CELL group,
    which has its own internal block/sub-block/children nesting) in a
    top-level GRUP header. group_type is always 0 here since every group
    this app ever WRITES fresh is a top-level one; a group this app only
    needs to copy-and-nest (like that CELL group's internal structure) is
    built as raw bytes by the caller and passed in as part of body_bytes,
    not reconstructed through this function."""
    group_size = 24 + len(body_bytes)  # 24 = GRUP header size
    header = struct.pack(GROUP_HEADER_FMT, b"GRUP", group_size, label, 0, 0, 0, 0)
    return header + body_bytes


def write_plugin(output_path: str | Path, masters: list[str], groups: list[bytes], num_records: int = 1) -> None:
    """Writes TES4 (with the given masters) followed by each of `groups` --
    complete top-level group byte blobs, each already including its own
    24-byte GRUP header (build these with wrap_top_group). num_records is
    only the informational count TES4's HEDR carries; the game doesn't use
    it to decide how many records to actually read."""
    tes4 = build_tes4(masters, num_records=num_records)
    content = tes4.to_bytes() + b"".join(groups)
    Path(output_path).write_bytes(content)
