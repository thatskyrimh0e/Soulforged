"""
Full-fidelity alternative to driving Creation Kit's FaceGen bake: copies a
head mesh/texture RaceMenu already produced for an imported preset into the
new follower NPC's FaceGenData paths, renamed to match its own plugin +
FormID.

Why this exists: Creation Kit's FaceGen bake only understands vanilla
NAM9/NAMA sliders. It has no idea about RaceMenu's sculpt-tool vertex edits
or extended SKEE sliders (see core/jslot_reader.py), so a preset built with
those won't bake correctly through CK no matter what. But the game itself
doesn't care how a FaceGenData\\FaceGeom\\<plugin>\\<formid>.nif got there --
if you already have the *exact* head RaceMenu already has (which already
reflects every sculpt edit), copying and renaming it is both simpler and
more faithful than re-baking anything.

Where that head actually comes from: when RaceMenu saves a preset (the
.jslot this app's Import Face step reads), it ALSO writes a matching head
mesh/texture right alongside it -- SKSE/Plugins/CharGen/<name>.nif and
SKSE/Plugins/CharGen/<name>.dds, as siblings of
SKSE/Plugins/CharGen/Presets/<name>.jslot. That pair already reflects every
sculpt/slider edit the preset has, and it's written the moment the preset
is saved -- no extra in-game export step needed. This is the primary and
most reliable source. The older idea of exporting a live actor's head
straight to FaceGenData is kept as a fallback for anyone who did that
instead.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FaceGenCopyResult:
    ok: bool
    message: str


def _facegen_rel_paths(plugin: str, formid_hex: str) -> tuple[str, str]:
    formid_hex = formid_hex.upper()
    nif_rel = f"meshes/actors/character/FaceGenData/FaceGeom/{plugin}/{formid_hex}.nif"
    dds_rel = f"textures/actors/character/FaceGenData/FaceTint/{plugin}/{formid_hex}.dds"
    return nif_rel, dds_rel


def find_chargen_siblings(jslot_path: str | Path | None) -> tuple[Path | None, Path | None]:
    """
    The cheap, reliable route: the jslot this app already resolved to a real
    file on disk lives at .../SKSE/Plugins/CharGen/Presets/<name>.jslot --
    its matching head mesh/texture are one folder up, same basename:
    .../SKSE/Plugins/CharGen/<name>.nif and <name>.dds. No searching needed.
    """
    if not jslot_path:
        return None, None
    jslot_path = Path(jslot_path)
    chargen_dir = jslot_path.parent.parent
    nif_candidate = chargen_dir / f"{jslot_path.stem}.nif"
    dds_candidate = chargen_dir / f"{jslot_path.stem}.dds"
    return (
        nif_candidate if nif_candidate.exists() else None,
        dds_candidate if dds_candidate.exists() else None,
    )


def find_source_files(instance, game_data_dir, plugin: str, formid_hex: str) -> tuple[Path | None, Path | None]:
    """
    Fallback route, for a head genuinely exported live from an actor rather
    than saved as a RaceMenu preset: looks in the order it's actually likely
    to exist for an MO2 setup -- MO2's "overwrite" folder first (where a
    running game's new writes land by default), then whichever active mod
    wins that path in the VFS, then the real game Data folder as a last
    resort (non-MO2 launches, or files moved there manually).
    """
    nif_rel, dds_rel = _facegen_rel_paths(plugin, formid_hex)

    def _find(rel: str) -> Path | None:
        if instance is not None:
            overwrite_candidate = instance.install_dir / "overwrite" / rel
            if overwrite_candidate.exists():
                return overwrite_candidate
            from core import mo2_reader
            resolved = mo2_reader.resolve_file(instance, rel)
            if resolved:
                return resolved
        if game_data_dir:
            data_candidate = Path(game_data_dir) / rel
            if data_candidate.exists():
                return data_candidate
        return None

    return _find(nif_rel), _find(dds_rel)


def copy_exported_facegen(
    instance,
    game_data_dir: str | Path,
    source_plugin: str,
    source_formid_hex: str,
    dest_plugin: str,
    dest_formid_hex: str,
    dest_root: str | Path | None = None,
    jslot_path: str | Path | None = None,
) -> FaceGenCopyResult:
    """
    game_data_dir is only used for the fallback plugin+FormID lookup (see
    find_source_files). dest_root is where the copy is WRITTEN: a
    standalone follower-mod folder (see core/paths.get_output_root) by
    default, so the whole follower -- plugin + its FaceGenData -- ends up
    in one self-contained folder, ready to drop straight into a mod manager, rather than
    dropped straight into the live install.

    Tries, in order: (1) the RaceMenu preset's own CharGen sibling files
    (jslot_path), the common case and needs nothing from the user; (2) the
    plugin+FormID FaceGenData lookup, for a head exported live from an
    actor instead.
    """
    game_data_dir = Path(game_data_dir)
    dest_root = Path(dest_root) if dest_root is not None else game_data_dir

    src_nif, src_dds = find_chargen_siblings(jslot_path)
    source_desc = f"the imported preset ({Path(jslot_path).stem})" if jslot_path else None

    if not src_nif and not src_dds:
        src_nif, src_dds = find_source_files(instance, game_data_dir, source_plugin, source_formid_hex)
        source_desc = f"{source_plugin}|{source_formid_hex.upper()}"

    if not src_nif and not src_dds:
        return FaceGenCopyResult(
            False,
            "Couldn't find a head mesh/texture for this follower. If you imported a RaceMenu "
            "preset on step 1, RaceMenu should have saved a matching "
            "SKSE/Plugins/CharGen/<name>.nif + .dds alongside its .jslot -- check that mod's "
            "folder has those files. Otherwise, in-game with RaceMenu open on the actor, use "
            "its head export option, set 'Exported from plugin/FormID' below to match, and "
            "try again.",
        )

    nif_rel, dds_rel = _facegen_rel_paths(dest_plugin, dest_formid_hex)
    dest_nif = dest_root / nif_rel
    dest_dds = dest_root / dds_rel

    copied = []
    if src_nif:
        dest_nif.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_nif, dest_nif)
        copied.append("head mesh (.nif)")
    if src_dds:
        dest_dds.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_dds, dest_dds)
        copied.append("head texture (.dds)")

    missing = []
    if not src_nif:
        missing.append("head mesh (.nif)")
    if not src_dds:
        missing.append("head texture (.dds)")

    message = f"Copied {', '.join(copied)} from {source_desc} into {dest_plugin}'s FaceGenData (form {dest_formid_hex.upper()})."
    if missing:
        message += f" Missing: {', '.join(missing)} -- that part falls back to whatever CK/vanilla provides."

    return FaceGenCopyResult(ok=bool(copied), message=message)
