"""
Scans the active MO2 load order for assets relevant to follower building:
head standards (High Poly Head / Charmers of the Reach / UBE), body standards
(CBBE / 3BA / UBE / UNP family / BHUNP / 7Base / male bodies), actual
RaceMenu face presets, actual BodySlide presets (parsed by name, not just by
file), and SMP physics configs.

This is signature/keyword based (filenames + path fragments) for the broad
"standard" detection, but presets are resolved to their real in-game display
name wherever possible (RaceMenu preset name = jslot filename; BodySlide
preset name = the <SliderSet name="..."> inside the XML), since that's what
actually shows up when you load them in-game and is what users search for.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from core.mo2_reader import MO2Instance, walk_active_files

# Keyword signatures. Matched case-insensitively against the relative path.
HEAD_SIGNATURES = {
    "High Poly Head": ["highpolyhead", "high poly head", "hph"],
    "Charmers of the Reach (COtR)": ["charmers of the reach", "cotr"],
    "UBE Head": ["universal body exchange", "ube"],
}

# Every widely-used Skyrim SE/AE body standard, female and male, that a
# BodySlide-based or fixed-mesh follower is likely to be built on.
BODY_SIGNATURES = {
    "CBBE": ["cbbe", "caliente"],
    "CBBE 3BA (3BBB Advanced)": ["3ba", "3bbb", "3ba advanced"],
    "CBBE SMP / SAE": ["cbbe smp", "cbbe-sae", "cbbe sae"],
    "UNP": ["\\unp\\", "/unp/", " unp ", "unp body"],
    "UNPB": ["unpb"],
    "UNPetite": ["unpetite", "unp petite"],
    "7Base": ["7base", "7b base"],
    "BHUNP (UUNP successor)": ["bhunp"],
    "UUNP": ["uunp"],
    "TBD (The Body by Dogma)": ["tbd ", "the body by dogma", "dogma body"],
    "Fair Skin / Bijin body variants": ["fair skin body"],
    "UBE Body": ["universal body exchange", "ube"],
    "Vanilla Male": ["vanilla male body"],
    "SOS (Schlongs of Skyrim)": ["schlongs of skyrim", "sos "],
    "SAM (Superior/Amazing Male)": ["sam light", "sam heavy", "superior amazing male", "\\sam\\"],
    "Bodytalk": ["bodytalk"],
    "Atomic Muscle": ["atomic muscle"],
}

SMP_SIGNATURES = ["hdtsmp64.xml", "smp", "faststart.hkx", "hdt-smp"]

RACEMENU_PRESET_EXTS = (".jslot",)


@dataclass
class PresetRef:
    """A pickable preset: clean display name, the real relative path it came
    from (for display/tooltips), and the actual absolute path on disk (what
    anything that needs to open/parse the file -- e.g. jslot application --
    must use)."""
    name: str
    relative_path: str
    mod_name: str
    abs_path: str = ""


@dataclass
class ScanResults:
    head_candidates: dict[str, list[str]] = field(default_factory=dict)   # standard -> relative paths
    body_candidates: dict[str, list[str]] = field(default_factory=dict)
    racemenu_presets: list[PresetRef] = field(default_factory=list)
    bodyslide_presets: list[PresetRef] = field(default_factory=list)
    smp_configs: list[PresetRef] = field(default_factory=list)  # name = owning mod's title


def _matches_any(haystack: str, needles: list[str]) -> bool:
    return any(n in haystack for n in needles)


def _extract_bodyslide_preset_names(abs_path: Path, rel_path: str, mod_name: str) -> list[PresetRef]:
    """A BodySlide 'SliderSets' / 'SliderPresets' xml can hold several named
    presets. Parse it and return one PresetRef per <SliderSet name="..."> or
    <Preset name="..."> found; falls back to the filename if parsing fails."""
    try:
        tree = ET.parse(abs_path)
        root = tree.getroot()
        names = []
        for tag in ("SliderSet", "Preset"):
            for el in root.iter(tag):
                nm = el.get("name")
                if nm:
                    names.append(nm)
        if names:
            return [PresetRef(name=n, relative_path=rel_path, mod_name=mod_name, abs_path=str(abs_path)) for n in names]
    except ET.ParseError:
        pass
    return [PresetRef(name=Path(rel_path).stem, relative_path=rel_path, mod_name=mod_name, abs_path=str(abs_path))]


def scan(instance: MO2Instance) -> ScanResults:
    results = ScanResults(
        head_candidates={k: [] for k in HEAD_SIGNATURES},
        body_candidates={k: [] for k in BODY_SIGNATURES},
    )

    for rel_path, abs_path, mod_name in walk_active_files(instance):
        lower = rel_path.lower()
        lower_mod = mod_name.lower()

        for standard, needles in HEAD_SIGNATURES.items():
            if _matches_any(lower, needles) or _matches_any(lower_mod, needles):
                results.head_candidates[standard].append(rel_path)

        for standard, needles in BODY_SIGNATURES.items():
            if _matches_any(lower, needles) or _matches_any(lower_mod, needles):
                results.body_candidates[standard].append(rel_path)

        if rel_path.lower().endswith(RACEMENU_PRESET_EXTS):
            results.racemenu_presets.append(
                PresetRef(name=Path(rel_path).stem, relative_path=rel_path, mod_name=mod_name, abs_path=str(abs_path))
            )

        if rel_path.lower().endswith(".xml") and "slider" in lower and ("preset" in lower or "sliderset" in lower):
            results.bodyslide_presets.extend(_extract_bodyslide_preset_names(abs_path, rel_path, mod_name))

        if _matches_any(lower, SMP_SIGNATURES):
            results.smp_configs.append(PresetRef(name=mod_name, relative_path=rel_path, mod_name=mod_name, abs_path=str(abs_path)))

    # Dedupe SMP configs by owning mod -- a mod can ship several physics xmls,
    # but the UI shows "the mod's title," not each individual file.
    seen_mods = set()
    deduped_smp = []
    for ref in results.smp_configs:
        if ref.mod_name not in seen_mods:
            seen_mods.add(ref.mod_name)
            deduped_smp.append(ref)
    results.smp_configs = deduped_smp

    results.racemenu_presets.sort(key=lambda p: p.name.lower())
    results.bodyslide_presets.sort(key=lambda p: p.name.lower())
    results.smp_configs.sort(key=lambda p: p.name.lower())
    return results
