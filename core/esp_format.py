"""
Minimal binary reader/writer for Skyrim SE's plugin (.esp/.esm) format --
just enough to read one donor NPC_ record's raw subrecords out of a plugin
and write a new plugin containing a modified clone of it. This replaces
driving xEdit/Creation Kit entirely: no external tool, no GUI automation,
no MO2-launch complications.

Format reference (record/group headers are each 24 bytes, uncompressed
records only -- we never read or write compressed records):

Record header:
    4s   type        e.g. b"NPC_", b"TES4"
    I    data_size    size of the record's data, NOT including this header
    I    flags
    I    form_id
    H    timestamp
    H    version_control_info_1
    H    internal_version
    H    unknown

GRUP header:
    4s   "GRUP"
    I    group_size   total size INCLUDING this 24-byte header
    4s   label        record type for a top-level group, e.g. b"NPC_"
    i    group_type   0 = top-level
    H    timestamp
    H    version_control_info_1
    I    unknown

Subrecord:
    4s   type         e.g. b"EDID", b"FULL"
    H    size
    <size> bytes of data
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

RECORD_HEADER_FMT = "<4sIIIHHHH"
RECORD_HEADER_SIZE = struct.calcsize(RECORD_HEADER_FMT)  # 24
GROUP_HEADER_FMT = "<4sI4siHHI"
GROUP_HEADER_SIZE = struct.calcsize(GROUP_HEADER_FMT)  # 24

FLAG_COMPRESSED = 0x00040000


@dataclass
class Subrecord:
    type: bytes   # 4-byte subrecord tag, e.g. b"EDID"
    data: bytes

    def to_bytes(self) -> bytes:
        if len(self.data) > 0xFFFF:
            # Oversized subrecord -- needs an XXXX size-override subrecord
            # immediately before it. NPC_ records never get this big in
            # practice, but handle it rather than silently truncate.
            xxxx = struct.pack("<4sHI", b"XXXX", 4, len(self.data))
            return xxxx + struct.pack("<4sH", self.type, 0) + self.data
        return struct.pack("<4sH", self.type, len(self.data)) + self.data


@dataclass
class RawRecord:
    type: bytes
    flags: int
    form_id: int
    subrecords: list[Subrecord] = field(default_factory=list)

    def get(self, sub_type: bytes) -> bytes | None:
        for s in self.subrecords:
            if s.type == sub_type:
                return s.data
        return None

    def get_all(self, sub_type: bytes) -> list[bytes]:
        return [s.data for s in self.subrecords if s.type == sub_type]

    def to_bytes(self) -> bytes:
        body = b"".join(s.to_bytes() for s in self.subrecords)
        header = struct.pack(
            RECORD_HEADER_FMT, self.type, len(body), self.flags, self.form_id,
            0, 0, 44, 0,  # timestamp/vcs/internal-version/unknown -- not meaningful for a fresh record
        )
        return header + body


def iter_subrecords(data: bytes) -> list[Subrecord]:
    """Parses a record's raw data blob into its subrecord list, handling
    an XXXX size-override subrecord if present."""
    subs: list[Subrecord] = []
    pos = 0
    pending_size: int | None = None
    while pos < len(data):
        sub_type = data[pos:pos + 4]
        size = struct.unpack_from("<H", data, pos + 4)[0]
        pos += 6
        if sub_type == b"XXXX":
            pending_size = struct.unpack_from("<I", data, pos)[0]
            pos += size
            continue
        real_size = pending_size if pending_size is not None else size
        pending_size = None
        sub_data = data[pos:pos + real_size]
        pos += real_size
        subs.append(Subrecord(type=sub_type, data=sub_data))
    return subs


def read_record_at(buf: bytes, offset: int) -> tuple[RawRecord, int]:
    """
    Reads one record starting at offset. Returns (record, next_offset).
    Handles Bethesda's per-record compression (common in SE/AE master files,
    e.g. Skyrim.esm itself): when the compressed flag is set, the record's
    on-disk data is a 4-byte uncompressed-size prefix followed by zlib data;
    next_offset always advances by the ON-DISK (compressed) size, since
    that's what actually occupies file space.
    """
    rtype, data_size, flags, form_id, *_ = struct.unpack_from(RECORD_HEADER_FMT, buf, offset)
    body_start = offset + RECORD_HEADER_SIZE
    next_offset = body_start + data_size

    if flags & FLAG_COMPRESSED:
        decompressed_size = struct.unpack_from("<I", buf, body_start)[0]
        compressed = buf[body_start + 4:next_offset]
        body = zlib.decompress(compressed)
        if len(body) != decompressed_size:
            raise ValueError(
                f"Record {rtype!r} ({form_id:08X}): decompressed to {len(body)} bytes, expected {decompressed_size}."
            )
    else:
        body = buf[body_start:next_offset]

    record = RawRecord(type=rtype, flags=flags, form_id=form_id, subrecords=iter_subrecords(body))
    return record, next_offset


def cstring(data: bytes) -> str:
    """Decodes a null-terminated subrecord string."""
    return data.split(b"\x00", 1)[0].decode("cp1252", errors="replace")


def pack_cstring(text: str) -> bytes:
    return text.encode("cp1252", errors="replace") + b"\x00"
