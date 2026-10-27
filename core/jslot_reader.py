"""
Parses a RaceMenu/SKEE .jslot preset export into the pieces that can
actually be written into an NPC_ record via xEdit:

  - headParts  -> NPC "Head Parts" (PNAM) references (hair, brows, eyes,
                  mouth, facial hair, scars, etc.)
  - tintInfo   -> NPC "Tint Layers" (makeup, warpaint, blush, skin tone
                  overlay, etc.) -- color ints are 0xAARRGGBB
  - actor.hairColor / actor.weight -> HCLF hair color + NPC weight

IMPORTANT HONEST LIMITATION: a .jslot also stores "morphs.sculpt" and
"morphs.custom" -- per-vertex sculpt-tool deltas and RaceMenu/SKEE "extra
slider" data applied live via NetImmerse Override at runtime. There is no
native NPC_ record field for these; Creation Kit's own FaceGen bake only
understands the vanilla NAM9/NAMA sliders, not SKEE's extended sculpting.
So this reader intentionally does NOT attempt to translate "morphs" into
anything -- faithfully doing that requires either (a) the user exporting
their actual baked head NIF/DDS from in-game RaceMenu ("Export Head") and
copying those files into the new NPC's FaceGenData paths, or (b) applying
the jslot at runtime in-game via a RaceMenu/SKEE call. Head parts, tints,
hair color and weight below ARE faithfully portable and cover most of
what makes a preset "look right" (which hair/brows/eyes/scars were picked,
and all the tint/makeup colors).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HeadPart:
    part_type: int
    plugin: str
    form_id_hex: str  # e.g. "05150F", no leading "0x"


@dataclass
class TintEntry:
    index: int
    alpha: int
    red: int
    green: int
    blue: int


@dataclass
class JslotData:
    head_parts: list = field(default_factory=list)   # list[HeadPart]
    tints: list = field(default_factory=list)         # list[TintEntry]
    hair_color: int | None = None
    weight: float | None = None


def _split_form_identifier(identifier: str) -> tuple[str, str]:
    """'High Poly Head.esm|000A06' -> ('High Poly Head.esm', '000A06')."""
    plugin, _, form_hex = identifier.partition("|")
    return plugin.strip(), form_hex.strip()


def parse_jslot(path: str | Path) -> JslotData:
    path = Path(path)
    # RaceMenu writes these with a UTF-8 BOM sometimes.
    raw = json.loads(path.read_text(encoding="utf-8-sig"))

    data = JslotData()

    for hp in raw.get("headParts", []):
        identifier = hp.get("formIdentifier") or ""
        if "|" not in identifier:
            continue
        plugin, form_hex = _split_form_identifier(identifier)
        if not plugin or not form_hex:
            continue
        data.head_parts.append(HeadPart(part_type=int(hp.get("type", -1)), plugin=plugin, form_id_hex=form_hex))

    for tint in raw.get("tintInfo", []):
        color = int(tint.get("color", 0))
        alpha = (color >> 24) & 0xFF
        red = (color >> 16) & 0xFF
        green = (color >> 8) & 0xFF
        blue = color & 0xFF
        # Alpha 0 means "this tint slot isn't actively applied" in SKEE's
        # export -- skip it so we don't stomp a default with a no-op entry.
        if alpha == 0:
            continue
        data.tints.append(TintEntry(index=int(tint.get("index", -1)), alpha=alpha, red=red, green=green, blue=blue))

    actor = raw.get("actor", {})
    if "hairColor" in actor:
        data.hair_color = int(actor["hairColor"])
    if "weight" in actor:
        data.weight = float(actor["weight"])

    return data


def to_params_lines(data: JslotData) -> list[str]:
    """Flatten into the KEY=VALUE lines xedit_bridge writes to
    follower_params.txt, using ';'-separated records and '|'-separated
    fields within each record (neither character appears in plugin names
    or hex form IDs)."""
    lines = []

    head_part_records = [f"{hp.plugin}|{hp.form_id_hex}|{hp.part_type}" for hp in data.head_parts]
    lines.append("JSLOT_HEADPARTS=" + ";".join(head_part_records))

    tint_records = [f"{t.index}|{t.alpha}|{t.red}|{t.green}|{t.blue}" for t in data.tints]
    lines.append("JSLOT_TINTS=" + ";".join(tint_records))

    if data.hair_color is not None:
        lines.append(f"JSLOT_HAIRCOLOR={data.hair_color}")
    if data.weight is not None:
        lines.append(f"JSLOT_WEIGHT={data.weight}")

    return lines


def required_plugins(data: JslotData) -> list[str]:
    """Every plugin this preset's head parts reference, sorted. This is
    what actually needs to be active in the load order for the preset to
    apply correctly -- independent of any head-standard label, so it works
    the same whether the preset uses High Poly Head, COTR, or anything
    else entirely."""
    return sorted({hp.plugin for hp in data.head_parts})


# MO2's plugins.txt only lists plugins the USER can toggle -- the base-game
# masters are always loaded and typically aren't listed in it at all, so
# checking against plugin_order alone would wrongly flag "Skyrim.esm is
# missing" on every single preset. Treat these as always present.
ALWAYS_ACTIVE_MASTERS = {
    "skyrim.esm", "update.esm", "dawnguard.esm", "hearthfires.esm", "dragonborn.esm",
}


def missing_plugins(data: JslotData, active_plugin_order: list[str]) -> list[str]:
    """Which of required_plugins(data) are NOT present in the given active
    load order (case-insensitive compare, since Windows filesystems and
    MO2's own lists aren't consistent about casing). Base-game masters are
    always treated as present -- see ALWAYS_ACTIVE_MASTERS."""
    active_lower = {p.lower() for p in active_plugin_order} | ALWAYS_ACTIVE_MASTERS
    return [p for p in required_plugins(data) if p.lower() not in active_lower]


def describe_jslot(path: str | Path) -> list[str]:
    """
    Human-readable summary of what a .jslot actually needs: every head part
    it references (with a best-effort type name) and which plugin provides
    it, the active tint/makeup layers, hair color, weight, and -- most
    useful before you hit Build -- the full set of plugins this preset
    depends on, so you can check they're all active in your load order
    first. Returns a list of display lines; never raises -- parse problems
    come back as a single line starting with "Could not read this preset:".
    """
    try:
        data = parse_jslot(path)
    except Exception as exc:
        return [f"Could not read this preset: {exc}"]

    lines: list[str] = []

    if data.head_parts:
        lines.append(f"Head parts ({len(data.head_parts)}):")
        for hp in data.head_parts:
            # NOTE: deliberately not naming the slot (e.g. "hair"/"eyes") --
            # the vanilla type numbers only reliably mean anything for the
            # base game's own head parts, and mods add their own numbered
            # slots for piercings/tattoos/etc. with no universal meaning, so
            # a guessed name would often just be wrong. The plugin/formID is
            # what actually matters for checking requirements.
            lines.append(f"    Slot {hp.part_type}: {hp.plugin}  ({hp.form_id_hex})")
    else:
        lines.append("Head parts: none found in this preset.")

    lines.append(f"Active tint/makeup layers: {len(data.tints)}")
    if data.hair_color is not None:
        lines.append(f"Hair color (packed ARGB): {data.hair_color}")
    if data.weight is not None:
        lines.append(f"Weight: {data.weight}")

    plugins = sorted({hp.plugin for hp in data.head_parts})
    if plugins:
        lines.append("")
        lines.append("Requires these plugins to be active in your load order:")
        for plugin in plugins:
            lines.append(f"    - {plugin}")

    return lines
