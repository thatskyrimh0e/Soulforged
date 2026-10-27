"""
Walks a plugin's top-level CELL group, which (unlike NPC_/CLAS/SPEL) isn't a
flat list of records -- interior cells are nested inside "block" (GRUP type
2) and "sub-block" (GRUP type 3) groups, and each CELL record is followed by
its own "cell children" group (GRUP type 6, labeled with the CELL's own
FormID) containing "persistent" (type 8) and "temporary" (type 9) children
groups that hold the cell's actual placed references (REFR/ACHR/etc).

This nesting, and the Object-property layout decoded below, were confirmed
by directly inspecting a real follower mod's own spawn-placement system
(its holding cell + its quest's VMAD), the same way every other binary
format in this app was validated against real data rather than guessed
from docs.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from core.esp_format import GROUP_HEADER_FMT, GROUP_HEADER_SIZE, RawRecord, cstring, read_record_at
from core.esp_reader import read_top_group_bytes


@dataclass
class CellMatch:
    cell: RawRecord
    children: list[RawRecord]  # REFR/ACHR/etc. placed directly in this cell (persistent + temporary)


def _walk(buf: bytes) -> list[tuple[RawRecord | None, bytes]]:
    """One level of a CELL group's contents: yields (record_or_None, raw_group_bytes_or_b'')
    -- either a record was found, or a nested GRUP's data bytes (caller recurses)."""
    pos = 0
    out = []
    while pos < len(buf):
        tag = buf[pos:pos + 4]
        if tag == b"GRUP":
            gtag, gsize, glabel, gtype, ts, vc, unk = struct.unpack_from(GROUP_HEADER_FMT, buf, pos)
            out.append((None, (gtype, glabel, buf[pos + GROUP_HEADER_SIZE:pos + gsize])))
            pos += gsize
        else:
            record, next_pos = read_record_at(buf, pos)
            out.append((record, None))
            pos = next_pos
    return out


def find_cell(plugin_path, cell_edid: str) -> CellMatch | None:
    """Finds one interior CELL record by EDID (case-insensitive) and
    collects whatever REFR/ACHR/etc. records are already placed directly in
    it -- a candidate pool to pick a 'spawn anchor' from."""
    group_bytes = read_top_group_bytes(plugin_path, b"CELL")
    if group_bytes is None:
        return None

    edid_lower = cell_edid.lower()
    pending_cell: RawRecord | None = None

    for record, nested in _walk(group_bytes):
        if record is not None:
            if record.type == b"CELL":
                pending_cell = record
                edid_data = record.get(b"EDID")
                if edid_data and cstring(edid_data).lower() == edid_lower:
                    # Children, if any, are in the GRUP (type 6) that follows
                    # this exact CELL record -- handled where we recurse below.
                    found_cell = record
                    children = _find_children_after(group_bytes, record)
                    return CellMatch(cell=found_cell, children=children)
            continue
        gtype, glabel, inner = nested
        if gtype in (2, 3):
            # Block / sub-block -- just descend, these never hold records directly.
            result = _find_in_block(inner, edid_lower)
            if result is not None:
                return result
    return None


def _find_in_block(buf: bytes, edid_lower: str) -> CellMatch | None:
    for record, nested in _walk(buf):
        if record is not None and record.type == b"CELL":
            edid_data = record.get(b"EDID")
            if edid_data and cstring(edid_data).lower() == edid_lower:
                children = _find_children_after(buf, record)
                return CellMatch(cell=record, children=children)
            continue
        if record is None:
            gtype, glabel, inner = nested
            if gtype == 3:  # sub-block, descend further
                result = _find_in_block(inner, edid_lower)
                if result is not None:
                    return result
    return None


def _find_children_after(buf: bytes, cell_record: RawRecord) -> list[RawRecord]:
    """Re-walks buf looking for the CELL record matching this FormID, then
    returns the records inside the type-6 'cell children' GRUP immediately
    following it (persistent + temporary), if any."""
    pos = 0
    while pos < len(buf):
        tag = buf[pos:pos + 4]
        if tag == b"GRUP":
            gtag, gsize, glabel, gtype, ts, vc, unk = struct.unpack_from(GROUP_HEADER_FMT, buf, pos)
            if gtype == 6 and struct.unpack_from("<I", glabel, 0)[0] == cell_record.form_id:
                return _collect_refs(buf[pos + GROUP_HEADER_SIZE:pos + gsize])
            if gtype in (2, 3):
                found = _find_children_after(buf[pos + GROUP_HEADER_SIZE:pos + gsize], cell_record)
                if found:
                    return found
            pos += gsize
        else:
            record, next_pos = read_record_at(buf, pos)
            pos = next_pos
    return []


def _collect_refs(buf: bytes) -> list[RawRecord]:
    """Flattens whatever's inside a cell-children GRUP (persistent/temporary
    sub-groups) into one list of placed reference records."""
    out = []
    pos = 0
    while pos < len(buf):
        tag = buf[pos:pos + 4]
        if tag == b"GRUP":
            gtag, gsize, glabel, gtype, ts, vc, unk = struct.unpack_from(GROUP_HEADER_FMT, buf, pos)
            out.extend(_collect_refs(buf[pos + GROUP_HEADER_SIZE:pos + gsize]))
            pos += gsize
        else:
            record, next_pos = read_record_at(buf, pos)
            out.append(record)
            pos = next_pos
    return out


def pick_anchor(children: list[RawRecord]) -> RawRecord | None:
    """Picks a reasonable 'spawn anchor' from a cell's existing placed
    references -- something with a real position (DATA subrecord present),
    preferring a plain object over another actor so the follower doesn't
    get stacked exactly on top of someone. Not guaranteed to be the ideal
    spot, but every interior worth listing in the curated location list has
    SOMETHING placed in it, and this gets a follower into the right room."""
    best = None
    for record in children:
        data = record.get(b"DATA")
        if not data or len(data) < 12:
            continue
        if record.type == b"ACHR" and best is not None:
            continue  # prefer a non-actor if we already have a candidate
        best = record
        if record.type != b"ACHR":
            break
    return best
