"""
Reads what we need out of an existing plugin: a specific record by its
local FormID (for cloning a donor NPC_), and records by their EDID or type
(for resolving a race/class the user picked/typed, or scanning a plugin for
spells/classes to offer in the Skills step) -- without needing xEdit at all.

Only reads top-level groups (GRUP group_type 0) directly under TES4; that's
where NPC_, RACE, CLAS and SPEL records all live, so nothing else needs
walking.

Everything here streams via seek()/read() instead of loading a whole plugin
into memory. That matters a lot once a caller needs to check many plugins
(e.g. scanning every active plugin's CLAS/SPEL group for the Skills step):
a full Skyrim.esm is several hundred MB, but its CLAS group is a few KB and
its SPEL group a few hundred KB -- reading only the group bytes needed,
rather than the whole file, is the difference between a scan across a big
load order finishing in a couple of seconds versus timing out.
"""
from __future__ import annotations

import struct
from pathlib import Path

from core.esp_format import GROUP_HEADER_FMT, GROUP_HEADER_SIZE, RawRecord, cstring, read_record_at


def _iter_top_groups_streaming(f):
    """Yields (label: bytes, data_start: int, data_end: int) for every
    top-level GRUP in the file, reading only each 24-byte group header (and
    the TES4 record's own header) rather than the whole file."""
    f.seek(0)
    tes4_header = f.read(24)
    if len(tes4_header) < 24:
        return
    tes4_data_size = struct.unpack_from("<I", tes4_header, 4)[0]
    f.seek(24 + tes4_data_size)

    while True:
        pos = f.tell()
        header_bytes = f.read(GROUP_HEADER_SIZE)
        if len(header_bytes) < GROUP_HEADER_SIZE:
            break
        tag, group_size, label, group_type, *_ = struct.unpack_from(GROUP_HEADER_FMT, header_bytes, 0)
        if tag != b"GRUP":
            break  # not a group here -- stop rather than misread garbage as records
        data_start = pos + GROUP_HEADER_SIZE
        data_end = pos + group_size
        if group_type == 0:
            yield label, data_start, data_end
        f.seek(data_end)


def iter_records_in_group(plugin_path: str | Path, group_label: bytes):
    """Yields every RawRecord directly under one plugin's top-level group of
    this type (e.g. b"SPEL", b"CLAS") -- used for scanning a whole plugin
    rather than looking up one known record. Only that group's bytes are
    read off disk, not the whole plugin."""
    with open(plugin_path, "rb") as f:
        for label, start, end in _iter_top_groups_streaming(f):
            if label != group_label:
                continue
            f.seek(start)
            group_bytes = f.read(end - start)
            pos = 0
            while pos < len(group_bytes):
                record, next_pos = read_record_at(group_bytes, pos)
                yield record
                pos = next_pos
            return  # a plugin has at most one top-level group per label


def read_top_group_bytes(plugin_path: str | Path, group_label: bytes) -> bytes | None:
    """Returns the raw data bytes (no GRUP header) of one top-level group,
    or None if that plugin doesn't have one. Used for groups like CELL/WRLD
    whose contents are nested (blocks/sub-blocks/children) rather than a
    flat list of records -- callers that understand that nesting (see
    core/esp_cell_reader.py) parse the returned bytes themselves."""
    with open(plugin_path, "rb") as f:
        for label, start, end in _iter_top_groups_streaming(f):
            if label != group_label:
                continue
            f.seek(start)
            return f.read(end - start)
    return None


def find_record_by_local_formid(plugin_path: str | Path, group_label: bytes, local_form_id: int) -> RawRecord | None:
    """
    Finds a record of the given type (e.g. b"NPC_") whose on-disk FormID
    equals local_form_id, directly under that plugin's own top-level group.
    "Local" here means as that plugin itself stores it (top byte 0 unless
    the record overrides something from one of ITS OWN masters) -- exactly
    what a .jslot's "Plugin|HEXID" or our own donor FormID already give us.
    """
    for record in iter_records_in_group(plugin_path, group_label):
        if record.form_id == local_form_id:
            return record
    return None


def find_record_by_edid(plugin_path: str | Path, group_label: bytes, edid: str) -> RawRecord | None:
    """Finds a record of this type with this exact EDID (case-insensitive)
    in one plugin. Cheap even on a big plugin: only that one group's bytes
    are read, not the whole file."""
    edid_lower = edid.lower()
    for record in iter_records_in_group(plugin_path, group_label):
        raw_edid = record.get(b"EDID")
        if raw_edid is not None and cstring(raw_edid).lower() == edid_lower:
            return record
    return None


def find_race_by_edid(plugin_path: str | Path, edid: str) -> RawRecord | None:
    """Finds a RACE record with this exact EDID. Kept as its own name since
    callers already use it; just a thin wrapper over find_record_by_edid."""
    return find_record_by_edid(plugin_path, b"RACE", edid)
