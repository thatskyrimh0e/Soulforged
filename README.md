# Soulforged

A desktop tool (PySide6) that reads your Mod Organizer 2 load order, lets you
import a RaceMenu preset, and builds a brand-new follower NPC plugin --
**directly, as bytes, with no Creation Kit or xEdit involved at runtime.**

> **Note on this file:** earlier versions of this README (and this app, under
> the name "Follower Builder") described driving SSEEdit + Creation Kit via
> Pascal scripts and `pywinauto`. That approach was fully replaced -- the app
> now writes plugins directly (see `core/esp_writer.py`, `core/esp_format.py`,
> `core/follower_builder.py`) and the old scripts live under
> `_deprecated_xedit_ck/` for reference only. This file now describes the
> current, actual architecture.

## Setup

```
pip install -r requirements.txt
python main.py
```

Paths are set in `config/settings.json`:
- `mo2_install_dir`: your Mod Organizer 2 install folder
- `mo2_profile`: which MO2 profile to read
- `ck_dir`: your Skyrim SE install folder (used as the game's `Data` source,
  despite the name -- Creation Kit itself is no longer actually driven)

## What it does right now

- Reads your MO2 `modlist.txt` / `plugins.txt` / `loadorder.txt` and resolves
  the virtual file system (which mod "wins" a file conflict, including files
  packed inside `.bsa` archives, not just loose files), the same way MO2
  itself would show you in-game.
- **Step 1 -- Import Face:** pick a RaceMenu `.jslot` preset. Head parts,
  tints, hair color weight, and the plugins they need get read directly from
  the preset.
- **Step 2 -- Character:** name, race (resolved by EDID against the donor
  plugin, then the rest of your active load order), sex, and an optional
  automatic placement at one of several curated interior locations (a quest
  teleports her there the first time the save loads -- see
  `core/follower_placement.py`).
- **Step 3 -- Skills:** class (with starting skill-value presets for
  mage/warrior/rogue archetypes), all 18 per-skill values, an optional spell
  list, and an optional **default outfit** -- scan your active load order for
  armor/clothing and check off the piece(s) she should spawn wearing (new;
  see "Default outfit" below).
- **Step 4 -- Build:** writes a brand-new, self-contained follower mod folder
  to your Desktop (`Soulforged Output/<plugin name>/`) containing the .esp,
  a `meta.ini` MO2 recognizes, a `credits.md` crediting any plugin that
  contributed head parts/tints/race/class/spells/outfit, and an
  `RSVignore` SPID `_DISTR.ini` so Racial Skin Variance leaves her imported
  skin/head texture alone. A second button copies in her real face
  shape/texture (see "How face fidelity works" below). Drop the whole folder
  into MO2 as a new mod when both are done.
- **Validate Follower ESP...** -- checks ANY `.esp`/`.esm` (one built here or
  downloaded) for missing/broken race, class, voice type, head parts,
  spells, default outfit, and FaceGenData files. See `core/esp_validator.py`.

## How face fidelity works (no Creation Kit FaceGen bake)

Creation Kit's FaceGen bake only understands vanilla sliders -- it has no
idea about RaceMenu's sculpt-tool vertex edits or extended SKEE sliders, so
a preset built with those never baked correctly through CK regardless. This
app sidesteps that entirely: when RaceMenu saves a preset, it ALSO writes a
matching head mesh/texture right alongside it
(`SKSE/Plugins/CharGen/<name>.nif`/`.dds`, siblings of the `.jslot`). That
pair already reflects every sculpt/slider edit perfectly. `core/facegen_copy.py`
just copies and renames those files into the new follower's own
FaceGenData paths -- simpler and more faithful than any bake could be.

## Default outfit (OTFT + DOFT)

Until now, a follower built here had **no default outfit set at all** -- a
real functional gap, not polish (an NPC with no DOFT spawns with nothing
equipped). `core/outfit_builder.py` builds a fresh `OTFT` (Default Outfit)
record listing ARMO pieces you pick in the Skills tab (already-active items
in your load order, resolved the same way class/spells are -- this doesn't
create new armor meshes or ARMA records, which would need real asset work
this app can't do) and wires it onto the new NPC's `DOFT` subrecord.

OTFT's binary shape (one `EDID` + exactly one `INAM` holding N packed
FormIDs, not one `INAM` per item) and the DOFT->OTFT relationship were
confirmed by directly decoding real `OTFT`/`NPC_` records out of the user's
own `Skyrim.esm`, the same standard every other binary format in this app
was validated against -- not guessed from docs.

**Known open question, flagged honestly:** this app's main `NPC_` record has
always been written with a FormID whose top byte is 0 regardless of how many
masters the finished plugin ends up with (an "injected FormID" against
`Skyrim.esm`, rather than the `(number of masters)`-prefixed convention a
genuinely new record should get per the format's own rules -- confirmed by
decoding real DLC files: `Dawnguard.esm`, which has 2 masters, writes its own
new RACE records with FormID top byte 2). `core/follower_placement.py`'s
CELL/ACHR/QUST records already use the "correct" prefixed convention and say
so in their own docstring. These two subsystems disagree with each other.
The new OTFT/DOFT code deliberately matches the main `NPC_` record's existing
convention (top byte 0) rather than guessing which one is "more correct,"
since whatever already works (or doesn't) for the main record will apply
identically to the new outfit record living in the same file. **This is
worth testing against a real in-game load with a multi-master follower** --
if the engine is lenient about FormID top byte 0 pointing at a master that
doesn't actually have that local ID (a known "FormID injection" pattern that
does work in practice for many Skyrim mods), everything here is fine as-is;
if not, every multi-master follower this app has ever built -- not just the
new outfit feature -- needs the same fix, and that's a bigger, separate change
this app's own author should make deliberately and test in-game, not
something to guess at overnight.

## What it still does NOT do (by design, not oversight)

- **Hair color (HCLF)** isn't set -- needs a full vanilla hair-color FormID
  lookup table this app doesn't have authoritative data for. Left as the
  donor's default; adjust manually in-game/xEdit if needed.
- **RaceMenu "morphs"** (sculpt-tool vertex edits / extended SKEE sliders)
  can't be reproduced from plugin data alone -- see "How face fidelity
  works" above for why that's fine in practice.
- **BodySlide batch-building** still happens in BodySlide itself.
- **Beast race / custom race support** -- race resolution works generically
  by EDID, but head-part handling (tails, feet, etc.) hasn't been
  specifically exercised against a beast race. A real gap worth testing.

## Roadmap ideas (not built yet)

- Write a build-checklist file per project (what's left to do in
  RaceMenu/BodySlide, in order) instead of just logging to the UI.
- Remember/reload past projects (currently each run starts fresh).
- Auto-launch BodySlide with a chosen preset pre-selected.
