"""
Reads a Mod Organizer 2 instance: active mod list, load order, and resolves
the virtual file system (VFS) so the rest of the app can see what a player
would actually see in-game, in the correct override priority.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MO2Mod:
    name: str
    enabled: bool
    priority: int  # higher = wins conflicts (closer to bottom of MO2's list)
    path: Path


@dataclass
class MO2Instance:
    install_dir: Path
    mods_dir: Path
    profile_name: str
    profile_dir: Path
    mods: list[MO2Mod] = field(default_factory=list)
    plugin_order: list[str] = field(default_factory=list)  # ESP/ESM load order, enabled only

    @property
    def active_mods(self) -> list[MO2Mod]:
        return [m for m in self.mods if m.enabled]


def find_profiles(install_dir: str | Path) -> list[str]:
    """List profile names available in this MO2 instance."""
    profiles_dir = Path(install_dir) / "profiles"
    if not profiles_dir.is_dir():
        raise FileNotFoundError(f"No 'profiles' folder found under {install_dir}")
    return sorted(p.name for p in profiles_dir.iterdir() if p.is_dir())


def load_instance(install_dir: str | Path, profile_name: str = "Default") -> MO2Instance:
    """
    Parse modlist.txt + loadorder.txt/plugins.txt for the given profile and
    build an MO2Instance describing the active mods in override-priority order.
    """
    install_dir = Path(install_dir)
    mods_dir = install_dir / "mods"
    profile_dir = install_dir / "profiles" / profile_name

    modlist_path = profile_dir / "modlist.txt"
    if not modlist_path.exists():
        raise FileNotFoundError(f"modlist.txt not found at {modlist_path}")

    # modlist.txt lists mods TOP (highest priority / wins conflicts) to BOTTOM.
    # Lines: "+ModName" (enabled), "-ModName" (disabled), "*ModName" (separator/backup - skip),
    # lines starting with '#' are comments. We reverse so priority index increases downward
    # to match MO2's own internal "priority" numbering (0 = bottom/lowest).
    raw_lines = [
        line.strip() for line in modlist_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    entries = []
    for line in raw_lines:
        if line.startswith("+") or line.startswith("-"):
            enabled = line.startswith("+")
            name = line[1:]
            if name.endswith("_separator"):
                continue
            entries.append((name, enabled))

    # entries[0] is MO2's topmost (highest priority) mod. Assign priority so that
    # the LAST entry (bottom of MO2 list) gets the lowest number -- matches
    # MO2's own convention where priority 0 is the bottom.
    total = len(entries)
    mods = []
    for idx, (name, enabled) in enumerate(entries):
        priority = total - idx  # topmost entry gets highest priority number
        mod_path = mods_dir / name
        mods.append(MO2Mod(name=name, enabled=enabled, priority=priority, path=mod_path))

    instance = MO2Instance(
        install_dir=install_dir,
        mods_dir=mods_dir,
        profile_name=profile_name,
        profile_dir=profile_dir,
        mods=mods,
    )

    # Plugin (ESP/ESM) order: prefer plugins.txt (has the "*" enabled marker used
    # by newer MO2) and fall back to loadorder.txt (plain list, enabled-only).
    plugins_path = profile_dir / "plugins.txt"
    loadorder_path = profile_dir / "loadorder.txt"
    plugin_order: list[str] = []
    if plugins_path.exists():
        for line in plugins_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("*"):
                plugin_order.append(line[1:])
            # lines without '*' in plugins.txt are present-but-disabled in modern MO2; skip them
    elif loadorder_path.exists():
        plugin_order = [
            line.strip() for line in loadorder_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    instance.plugin_order = plugin_order
    return instance


def resolve_file(instance: MO2Instance, relative_path: str) -> Path | None:
    """
    Given a path relative to the game's Data folder (e.g. "meshes/actors/character/foo.nif"),
    return the actual file that wins in the VFS -- i.e. the active mod with the
    HIGHEST priority that contains it. Returns None if no active mod provides it.
    """
    relative_path = relative_path.replace("\\", "/").lstrip("/")
    winner: Path | None = None
    winner_priority = -1
    for mod in instance.active_mods:
        candidate = mod.path / relative_path
        if candidate.exists() and mod.priority > winner_priority:
            winner = candidate
            winner_priority = mod.priority
    return winner


def resolve_plugin_paths(instance: MO2Instance) -> dict[str, Path]:
    """
    Build a plugin-filename -> winning absolute path map in ONE pass over the
    active mods, instead of calling resolve_file() once per plugin (which does
    its own O(active_mods) scan every call -- across a large load order, e.g.
    ~1200 plugins x ~1000 active mods, that's well over a million directory
    checks and is what made the old per-plugin scan time out).

    Plugin files (.esp/.esm/.esl) always live directly at the top level of a
    mod's folder, so a single non-recursive iterdir() per active mod is enough
    -- no need for the full recursive walk that walk_active_files() does for
    arbitrary assets.
    """
    plugin_map: dict[str, tuple[Path, int]] = {}
    for mod in instance.active_mods:
        try:
            entries = list(mod.path.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix.lower() not in (".esp", ".esm", ".esl"):
                continue
            key = entry.name.lower()
            prev = plugin_map.get(key)
            if prev is None or mod.priority > prev[1]:
                plugin_map[key] = (entry, mod.priority)
    return {name: path for name, (path, _priority) in plugin_map.items()}


def walk_active_files(instance: MO2Instance, extensions: tuple[str, ...] | None = None):
    """
    Yield (relative_path, winning_absolute_path, owning_mod_name) for every file
    across all active mods, respecting VFS override order (a file that exists in
    multiple active mods is only yielded once, from the highest-priority mod).

    extensions: optional tuple of lowercase extensions to filter on, e.g. (".nif", ".json")
    """
    seen: dict[str, tuple[Path, str, int]] = {}  # rel_path -> (abs_path, mod_name, priority)
    for mod in instance.active_mods:
        if not mod.path.is_dir():
            continue
        for root, _dirs, files in os.walk(mod.path):
            for fname in files:
                if extensions and not fname.lower().endswith(extensions):
                    continue
                abs_path = Path(root) / fname
                rel_path = str(abs_path.relative_to(mod.path)).replace("\\", "/")
                prev = seen.get(rel_path)
                if prev is None or mod.priority > prev[2]:
                    seen[rel_path] = (abs_path, mod.name, mod.priority)
    for rel_path, (abs_path, mod_name, _prio) in seen.items():
        yield rel_path, abs_path, mod_name


def mod_bsa_paths(mod) -> list:
    """
    .bsa archives sitting directly in a mod's own folder (where MO2 expects
    them -- same level as the mod's meshes/textures folders, not nested).
    Doesn't check the mod's .ini for which archives the game will actually
    load; for VFS-resolution purposes we want "could this mod provide the
    file," which any .bsa present in the folder answers well enough.
    """
    if not mod.path.is_dir():
        return []
    return sorted(mod.path.glob("*.bsa"))


def resolve_file_bytes(instance: MO2Instance, relative_path: str, bsa_cache=None) -> bytes | None:
    """
    Like resolve_file(), but also looks inside each active mod's .bsa
    archives when no active mod provides the path as a loose file -- so a
    texture/mesh/sound a mod ships packed instead of loose is still found.
    Returns the winning file's bytes (loose or BSA-decompressed), honoring
    the same "highest active-mod priority wins" VFS rule either way; a loose
    file always wins over a BSA at the SAME priority (that's how the game's
    own VFS resolves a mod's own loose-vs-packed files), but a lower-priority
    mod's loose file still loses to a higher-priority mod's BSA entry, same
    as resolve_file() would for two loose files.

    bsa_cache: an optional bsa_reader.BSAIndexCache to reuse across many
    calls (building it once outside a loop avoids re-indexing the same
    archive's directory structure per lookup).
    """
    relative_path = relative_path.replace("\\", "/").lstrip("/")

    winner_bytes: bytes | None = None
    winner_priority = -1

    loose_winner = resolve_file(instance, relative_path)
    if loose_winner is not None:
        for mod in instance.active_mods:
            if mod.path in loose_winner.parents or mod.path == loose_winner.parent:
                winner_priority = mod.priority
                break
        winner_bytes = loose_winner.read_bytes()

    if bsa_cache is None:
        from core.bsa_reader import BSAIndexCache
        bsa_cache = BSAIndexCache()

    for mod in instance.active_mods:
        if mod.priority <= winner_priority:
            continue
        for bsa_path in mod_bsa_paths(mod):
            archive = bsa_cache.get(bsa_path)
            if archive is None:
                continue
            if relative_path in archive:
                winner_bytes = archive.extract(relative_path)
                winner_priority = mod.priority
                break

    return winner_bytes
