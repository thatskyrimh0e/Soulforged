"""
Read-only BSA (Bethesda archive) support, so the asset scanner/VFS resolver
can see files packed inside a .bsa, not just loose files on disk.

Why this exists: mo2_reader.walk_active_files() / resolve_file() only walk
each active mod's folder with os.walk()/Path.exists() -- that's blind to
anything a mod ships packed into a .bsa instead of loose, which is most
release-quality mods. This module gives a cheap, read-only index of what's
inside a BSA plus on-demand extraction, so the VFS resolver can fall back to
"is it in one of this mod's BSAs" after "is it a loose file" comes up empty.

Format notes (SSE / v105, which is what this is written against):
  Header is 36 bytes: magic, version, folder-records offset, archive_flags,
  folder_count, file_count, total_folder_name_len, total_file_name_len,
  file_flags.
  archive_flags: 0x1 has folder names, 0x2 has file names, 0x4 compressed
  by default, 0x100 each file record is prefixed with its own embedded name.
  Folder records are 24 bytes in v105 (16 in older BA2-less BSA versions --
  v105 pads to 24 for 64-bit alignment). File records are 16 bytes:
  namehash(8) + size(4) + offset(4); the size field's top bit (0x40000000)
  TOGGLES the archive's default compression setting for that one file.
  Compressed file data in SSE is LZ4 **frame** format (magic 04 22 4D 18),
  not zlib -- preceded by a 4-byte uncompressed-size field, and if
  embed_names is set, THAT comes first as [1-byte namelen][name].

Only reads; never writes/modifies a BSA.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

try:
    import lz4.frame
    _HAVE_LZ4 = True
except ImportError:
    _HAVE_LZ4 = False


@dataclass
class _FileRecord:
    folder: str
    name: str
    size_field: int  # raw size field, compression-toggle bit still packed in
    offset: int

    @property
    def rel_path(self) -> str:
        return f"{self.folder}\\{self.name}" if self.folder else self.name


class BSAArchive:
    """
    Lazily-indexed read-only view of one .bsa file. Index (names + offsets)
    is built once on construction; actual file bytes are only read/decoded
    on extract(), so opening a big Textures.bsa just to check what it
    contains stays cheap -- this is what made the old bethesda_structs-based
    approach OOM on a vanilla Textures BSA; this module never materializes
    more than one extracted file's bytes at a time.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._records: dict[str, _FileRecord] = {}
        self._compressed_default = False
        self._embed_names = False
        self._load_index()

    def _load_index(self) -> None:
        with open(self.path, "rb") as f:
            header = f.read(36)
            if len(header) < 36:
                raise ValueError(f"{self.path}: not a valid BSA (truncated header)")
            (magic, version, _rec_offset, archive_flags, folder_count, file_count,
             total_folder_name_len, total_file_name_len, _file_flags) = struct.unpack("<4sIIIIIIII", header)
            if magic != b"BSA\x00":
                raise ValueError(f"{self.path}: not a BSA (bad magic {magic!r})")

            has_folder_names = bool(archive_flags & 0x1)
            has_file_names = bool(archive_flags & 0x2)
            self._compressed_default = bool(archive_flags & 0x4)
            self._embed_names = bool(archive_flags & 0x100)
            folder_rec_size = 24 if version == 105 else 16

            folder_counts = []
            for _ in range(folder_count):
                rec = f.read(folder_rec_size)
                _namehash, count = struct.unpack("<QI", rec[0:12])
                folder_counts.append(count)

            file_records: list[_FileRecord] = []
            for i in range(folder_count):
                foldername = ""
                if has_folder_names:
                    namelen = f.read(1)[0]
                    raw = f.read(namelen)
                    foldername = raw.rstrip(b"\x00").decode("latin1")
                for _ in range(folder_counts[i]):
                    rec = f.read(16)
                    _namehash, size, offset = struct.unpack("<QII", rec)
                    file_records.append(_FileRecord(foldername, "", size, offset))

            if has_file_names:
                names_blob = f.read(total_file_name_len)
                parts = names_blob.split(b"\x00")
                for idx, rec in enumerate(file_records):
                    if idx < len(parts):
                        rec.name = parts[idx].decode("latin1")

        for rec in file_records:
            if rec.name:
                # normalize so lookups match however mo2_reader hands us a path
                key = rec.rel_path.replace("/", "\\").lower()
                self._records[key] = rec

    def __contains__(self, rel_path: str) -> bool:
        return rel_path.replace("/", "\\").lower() in self._records

    def names(self) -> list[str]:
        return [r.rel_path for r in self._records.values()]

    def extract(self, rel_path: str) -> bytes | None:
        """Return the decompressed bytes for rel_path, or None if absent."""
        rec = self._records.get(rel_path.replace("/", "\\").lower())
        if rec is None:
            return None

        is_compressed = self._compressed_default
        if rec.size_field & 0x40000000:
            is_compressed = not is_compressed
        clean_size = rec.size_field & 0x3FFFFFFF

        with open(self.path, "rb") as f:
            f.seek(rec.offset)
            raw = f.read(clean_size)

        if self._embed_names:
            namelen = raw[0]
            raw = raw[1 + namelen:]

        if not is_compressed:
            return raw

        declen = struct.unpack("<I", raw[:4])[0]
        body = raw[4:]
        # SSE (v105) uses LZ4 frame format; older BSA versions used zlib.
        # Try the one that matches this archive's magic, fall back to the other.
        if body[:4] == b"\x04\x22\x4d\x18" and _HAVE_LZ4:
            data = lz4.frame.decompress(body)
        else:
            try:
                data = zlib.decompress(body)
            except zlib.error:
                if not _HAVE_LZ4:
                    raise RuntimeError(
                        f"{self.path}: {rel_path} is LZ4-compressed but the 'lz4' "
                        "package isn't installed (pip install lz4)"
                    )
                data = lz4.frame.decompress(body)
        if len(data) != declen:
            raise ValueError(f"{self.path}: {rel_path} decompressed to {len(data)} bytes, expected {declen}")
        return data


class BSAIndexCache:
    """
    Keeps one BSAArchive instance per .bsa path for the lifetime of a scan,
    so a load order with many mods/plugins doesn't re-read/re-index the same
    archive's directory structure repeatedly.
    """

    def __init__(self):
        self._cache: dict[str, BSAArchive] = {}

    def get(self, bsa_path: str | Path) -> BSAArchive | None:
        key = str(bsa_path)
        if key not in self._cache:
            try:
                self._cache[key] = BSAArchive(bsa_path)
            except (ValueError, OSError):
                return None
        return self._cache[key]
