"""
Step: Skills. Replaces the removed Body & Physics step -- a custom
BodySlide/SMP physics config doesn't apply once the follower is built in
vanilla gear, but a class, per-skill levels, and a spell list are real
NPC_ data (CNAM/DNAM/SPCT+SPLO) this app can set directly.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QComboBox, QSpinBox, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QCheckBox,
)

from core.skill_data import SKILL_NAMES, DONOR_SKILL_DEFAULTS, scan_classes, scan_spells, scan_armors

# A convenience starting list so the class picker isn't empty before any
# scan -- every one of these ships in Skyrim.esm itself, so they always
# resolve against the donor plugin with no load-order scan needed at all.
# Each is also mapped to a skill-preset archetype below (see CLASS_ARCHETYPES).
VANILLA_CLASSES = [
    # Verified against a real Skyrim.esm CLAS-group dump (every earlier
    # guess here -- "Mage", "Warrior", "Thief", "Tank", "CombatMelee",
    # "CombatMage", "CombatThiefArcher", "CombatArcher", "CombatBandit" --
    # doesn't actually exist as an EDID in the game; picking one of those
    # silently failed to resolve at Export, which is what caused the
    # "Class ... wasn't found anywhere" warning).
    "CombatMageDestruction", "CombatMageConjurer", "CombatMageElemental", "CombatMageNecro",
    "CombatSorcerer", "CombatMystic", "CombatWitchblade",
    "CombatWarrior1H", "CombatWarrior2H", "CombatBarbarian", "Blade", "GuardImperial",
    "CombatThief", "CombatRogue", "CombatAssassin", "CombatRanger", "CombatScout", "CombatNightblade",
]

# Full 18-value skill templates, in SKILL_NAMES order, applied when a class
# is picked -- a reasonable starting point the spin boxes can still be
# hand-tuned from afterward.
SKILL_PRESETS: dict[str, list[int]] = {
    #                    1H  2H  Arc Blk Smt HAr LAr Pkp Lkp Snk Alc Spc Alt Con Des Ill Res Enc
    "mage":            [15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 40, 15, 50, 50, 60, 40, 45, 40],
    "warrior":         [60, 50, 20, 50, 40, 55, 15, 15, 15, 15, 15, 20, 15, 15, 15, 15, 15, 15],
    "rogue":           [35, 15, 50, 20, 15, 15, 45, 50, 55, 60, 30, 30, 15, 15, 15, 20, 15, 15],
}

# Fixed vanilla classes known ahead of time -- exact match, no guessing needed.
CLASS_ARCHETYPES: dict[str, str] = {
    "combatmagedestruction": "mage", "combatmageconjurer": "mage", "combatmageelemental": "mage",
    "combatmagenecro": "mage", "combatsorcerer": "mage", "combatmystic": "mage", "combatwitchblade": "mage",
    "combatwarrior1h": "warrior", "combatwarrior2h": "warrior", "combatbarbarian": "warrior",
    "blade": "warrior", "guardimperial": "warrior",
    "combatthief": "rogue", "combatrogue": "rogue", "combatassassin": "rogue",
    "combatranger": "rogue", "combatscout": "rogue", "combatnightblade": "rogue",
}

# For a scanned or hand-typed class this app has never seen before, guess an
# archetype from words that actually show up in modded class EDIDs/names --
# e.g. picking "CombatNecromancer" (a custom class from a mod) still fills in
# mage-leaning skill numbers instead of leaving the spin boxes untouched.
ARCHETYPE_KEYWORDS: dict[str, str] = {
    "mage": "mage", "sorcer": "mage", "witch": "mage", "necro": "mage", "wizard": "mage", "arcane": "mage", "conjur": "mage",
    "warrior": "warrior", "knight": "warrior", "fighter": "warrior", "tank": "warrior", "melee": "warrior",
    "bandit": "warrior", "guard": "warrior", "soldier": "warrior", "brute": "warrior", "barbarian": "warrior",
    "thief": "rogue", "archer": "rogue", "rogue": "rogue", "assassin": "rogue", "sneak": "rogue", "hunter": "rogue", "ranger": "rogue",
}


def _guess_archetype(class_edid: str) -> str | None:
    key = class_edid.strip().lower()
    if key in CLASS_ARCHETYPES:
        return CLASS_ARCHETYPES[key]
    for keyword, archetype in ARCHETYPE_KEYWORDS.items():
        if keyword in key:
            return archetype
    return None


def _humanize_edid(edid: str) -> str:
    """Only used as a last-resort label (no in-game display name at all) --
    turns e.g. "DreadZombieLeftHand" into "Dread Zombie Left Hand"."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])", " ", edid)
    return spaced.replace("_", " ").strip()


class _ScanWorker(QThread):
    """Scanning CLAS/SPEL across a real ~1000+ plugin load order takes
    several seconds even after the fast path (see core/skill_data.py) -- run
    it off the GUI thread so the button doesn't look frozen."""
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, scan_fn, instance, game_data_dir):
        super().__init__()
        self.scan_fn = scan_fn
        self.instance = instance
        self.game_data_dir = game_data_dir

    def run(self):
        try:
            results = self.scan_fn(self.instance, game_data_dir=self.game_data_dir)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(results)


class SkillsTab(QWidget):
    def __init__(self, instance=None, game_data_dir=None):
        super().__init__()
        self.instance = instance
        self.game_data_dir = game_data_dir
        self._class_scan_worker = None
        self._spell_scan_worker = None
        self._outfit_scan_worker = None

        layout = QVBoxLayout(self)

        # --- Class ---
        class_box = QGroupBox("Class")
        class_col = QVBoxLayout()
        class_row = QHBoxLayout()
        self.class_combo = QComboBox()
        self.class_combo.setEditable(True)
        self.class_combo.addItem("(leave as donor's class)", userData=None)
        for edid in VANILLA_CLASSES:
            self.class_combo.addItem(edid, userData=edid)
        self.class_combo.activated.connect(self._on_class_picked)
        self.class_combo.lineEdit().returnPressed.connect(self._on_class_typed)
        class_row.addWidget(self.class_combo, 1)
        self.scan_classes_button = QPushButton("Scan Load Order for Classes")
        self.scan_classes_button.setObjectName("secondary")
        self.scan_classes_button.clicked.connect(self._on_scan_classes)
        class_row.addWidget(self.scan_classes_button)
        class_col.addLayout(class_row)
        class_hint = QLabel("Picking a class fills in reasonable starting skill numbers below for that archetype (mage/warrior/rogue) -- tune them afterward however you like.")
        class_hint.setObjectName("subheading")
        class_hint.setWordWrap(True)
        class_col.addWidget(class_hint)
        class_box.setLayout(class_col)
        layout.addWidget(class_box)

        # --- Skills ---
        skills_box = QGroupBox("Skills")
        skills_grid = QGridLayout()
        self.skill_spinboxes: list[QSpinBox] = []
        for i, skill_name in enumerate(SKILL_NAMES):
            row, col = divmod(i, 3)
            label = QLabel(skill_name)
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setValue(DONOR_SKILL_DEFAULTS[i])
            self.skill_spinboxes.append(spin)
            pair = QHBoxLayout()
            pair.addWidget(label, 1)
            pair.addWidget(spin)
            pair_widget = QWidget()
            pair_widget.setLayout(pair)
            skills_grid.addWidget(pair_widget, row, col)
        skills_box.setLayout(skills_grid)
        layout.addWidget(skills_box)

        # --- Spells ---
        spells_box = QGroupBox("Spells (optional -- leave unchecked to strip the donor's own spells)")
        spells_layout = QVBoxLayout()
        search_row = QHBoxLayout()
        self.spell_search = QLineEdit()
        self.spell_search.setPlaceholderText("Search spells...")
        self.spell_search.textChanged.connect(self._filter_spells)
        search_row.addWidget(self.spell_search, 1)
        self.scan_spells_button = QPushButton("Scan Load Order for Spells")
        self.scan_spells_button.setObjectName("secondary")
        self.scan_spells_button.clicked.connect(self._on_scan_spells)
        search_row.addWidget(self.scan_spells_button)
        spells_layout.addLayout(search_row)

        self.magic_mods_only_check = QCheckBox("Only known magic mods (faster, less noise)")
        self.magic_mods_only_check.setChecked(True)
        self.magic_mods_only_check.setToolTip(
            "Most plugins define a stray spell or two (quest effects, follower abilities) that aren't "
            "meant to be picked here. Unchecking this scans every active plugin instead -- slower, "
            "and the list will include a lot more than actual spell mods."
        )
        spells_layout.addWidget(self.magic_mods_only_check)

        self.spell_list = QListWidget()
        self.spell_list.setFixedHeight(180)
        spells_layout.addWidget(self.spell_list)

        self.spell_status = QLabel("Not scanned yet -- click \"Scan Load Order for Spells\" to find custom magic.")
        self.spell_status.setObjectName("subheading")
        spells_layout.addWidget(self.spell_status)

        spells_box.setLayout(spells_layout)
        layout.addWidget(spells_box, 1)

        self._all_spells = []  # list[ScannedRecord], already filtered to named/castable-looking spells

        # --- Default outfit ---
        outfit_box = QGroupBox("Default Outfit (optional -- leave unchecked for no outfit equipped)")
        outfit_layout = QVBoxLayout()
        outfit_search_row = QHBoxLayout()
        self.outfit_search = QLineEdit()
        self.outfit_search.setPlaceholderText("Search armor/clothing...")
        self.outfit_search.textChanged.connect(self._filter_outfit_items)
        outfit_search_row.addWidget(self.outfit_search, 1)
        self.scan_outfit_button = QPushButton("Scan Load Order for Armor")
        self.scan_outfit_button.setObjectName("secondary")
        self.scan_outfit_button.clicked.connect(self._on_scan_outfit)
        outfit_search_row.addWidget(self.scan_outfit_button)
        outfit_layout.addLayout(outfit_search_row)

        self.outfit_list = QListWidget()
        self.outfit_list.setFixedHeight(140)
        outfit_layout.addWidget(self.outfit_list)

        self.outfit_status = QLabel(
            "Not scanned yet -- click \"Scan Load Order for Armor\" to find wearable items "
            "(this scans every active plugin, so it can take a little while on a big load "
            "order). Check one or more to build a default outfit she'll spawn wearing."
        )
        self.outfit_status.setObjectName("subheading")
        self.outfit_status.setWordWrap(True)
        outfit_layout.addWidget(self.outfit_status)

        outfit_box.setLayout(outfit_layout)
        layout.addWidget(outfit_box, 1)

        self._all_armors = []  # list[ScannedRecord]

    # ---- Class scan / preset application ----

    def _on_scan_classes(self):
        if self._class_scan_worker is not None or self._spell_scan_worker is not None or self._outfit_scan_worker is not None:
            return  # a scan is already running -- never start a second one concurrently
        self.scan_classes_button.setEnabled(False)
        self.scan_spells_button.setEnabled(False)
        self.scan_outfit_button.setEnabled(False)
        self.scan_classes_button.setText("Scanning...")
        self._class_scan_worker = _ScanWorker(scan_classes, self.instance, self.game_data_dir)
        self._class_scan_worker.done.connect(self._on_classes_scanned)
        self._class_scan_worker.failed.connect(self._on_scan_failed(self.scan_classes_button, "Scan Load Order for Classes"))
        self._class_scan_worker.start()

    def _on_classes_scanned(self, results):
        self._class_scan_worker = None
        self.scan_classes_button.setEnabled(True)
        self.scan_spells_button.setEnabled(True)
        self.scan_outfit_button.setEnabled(True)
        self.scan_classes_button.setText(f"Scan Load Order for Classes ({len(results)} found)")
        current_text = self.class_combo.currentText()
        self.class_combo.clear()
        self.class_combo.addItem("(leave as donor's class)", userData=None)
        seen = set()
        for record in sorted(results, key=lambda r: r.edid.lower()):
            if record.edid in seen:
                continue
            seen.add(record.edid)
            label = record.edid if not record.full_name else f"{record.edid} ({record.full_name})"
            label += f"  --  {record.plugin}"
            self.class_combo.addItem(label, userData=record.edid)
        if current_text:
            self.class_combo.setEditText(current_text)

    def _on_scan_failed(self, button, default_text):
        def handler(message):
            self._class_scan_worker = None
            self._spell_scan_worker = None
            self._outfit_scan_worker = None
            self.scan_classes_button.setEnabled(True)
            self.scan_spells_button.setEnabled(True)
            self.scan_outfit_button.setEnabled(True)
            button.setText(default_text)
            if button is self.scan_outfit_button:
                self.outfit_status.setText(f"Scan failed: {message}")
            else:
                self.spell_status.setText(f"Scan failed: {message}")
        return handler

    def _on_class_picked(self, index: int):
        self._apply_class_preset(self.class_combo.itemData(index))

    def _on_class_typed(self):
        self._apply_class_preset(self.class_edid())

    def _apply_class_preset(self, class_edid: str | None):
        if not class_edid:
            return
        archetype = _guess_archetype(class_edid)
        if archetype is None:
            return
        preset = SKILL_PRESETS[archetype]
        for spin, value in zip(self.skill_spinboxes, preset):
            spin.setValue(value)

    # ---- Spell scan ----

    def _on_scan_spells(self):
        if self._class_scan_worker is not None or self._spell_scan_worker is not None or self._outfit_scan_worker is not None:
            return  # a scan is already running -- never start a second one concurrently
        self.scan_classes_button.setEnabled(False)
        self.scan_spells_button.setEnabled(False)
        self.scan_outfit_button.setEnabled(False)
        self.scan_spells_button.setText("Scanning...")
        self.spell_status.setText("Scanning your active load order for spells -- this can take several seconds...")
        magic_mods_only = self.magic_mods_only_check.isChecked()
        self._spell_scan_worker = _ScanWorker(
            lambda instance, game_data_dir: scan_spells(instance, game_data_dir=game_data_dir, magic_mods_only=magic_mods_only),
            self.instance, self.game_data_dir,
        )
        self._spell_scan_worker.done.connect(self._on_spells_scanned)
        self._spell_scan_worker.failed.connect(self._on_scan_failed(self.scan_spells_button, "Scan Load Order for Spells"))
        self._spell_scan_worker.start()

    def _on_spells_scanned(self, results):
        self._spell_scan_worker = None
        self.scan_classes_button.setEnabled(True)
        self.scan_spells_button.setEnabled(True)
        self.scan_outfit_button.setEnabled(True)
        self.scan_spells_button.setText("Scan Load Order for Spells")
        # The SPEL group also holds non-castable entries modders use for
        # abilities, diseases, and scripted FX (things like "AbMG08..." or
        # "Survival_DiseaseWitbane3") -- those never carry an in-game display
        # name, since the game never shows them as a spell either. Requiring
        # a real name here is what actually "cleans up" the list: it's the
        # same test the game itself effectively uses for what shows up in
        # the Magic menu.
        named = [r for r in results if r.full_name]
        self._all_spells = named
        skipped = len(results) - len(named)
        self.spell_status.setText(
            f"{len(named)} named spell(s) found across your active load order "
            f"({skipped} unnamed ability/effect record(s) hidden). Check any to give this follower."
        )
        self._populate_spells(named)

    def _populate_spells(self, spells):
        # Keep already-checked spells checked across a re-filter/re-scan.
        previously_checked = {
            self.spell_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.spell_list.count())
            if self.spell_list.item(i).checkState() == Qt.CheckState.Checked
        }
        self.spell_list.clear()
        for record in sorted(spells, key=lambda r: (r.full_name or r.edid).lower()):
            display_name = record.full_name or _humanize_edid(record.edid)
            label = f"{display_name}  --  {record.plugin}"
            item = QListWidgetItem(label)
            item.setToolTip(f"EDID: {record.edid}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            key = (record.plugin, record.form_id_hex)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setCheckState(Qt.CheckState.Checked if key in previously_checked else Qt.CheckState.Unchecked)
            self.spell_list.addItem(item)

    def _filter_spells(self, text: str):
        text = text.strip().lower()
        matches = [
            s for s in self._all_spells
            if text in s.edid.lower() or (s.full_name and text in s.full_name.lower())
        ] if text else self._all_spells
        self._populate_spells(matches)

    # ---- Outfit scan ----

    def _on_scan_outfit(self):
        if self._class_scan_worker is not None or self._spell_scan_worker is not None or self._outfit_scan_worker is not None:
            return  # a scan is already running -- never start a second one concurrently
        self.scan_classes_button.setEnabled(False)
        self.scan_spells_button.setEnabled(False)
        self.scan_outfit_button.setEnabled(False)
        self.scan_outfit_button.setText("Scanning...")
        self.outfit_status.setText("Scanning your active load order for armor/clothing -- this can take a little while...")
        self._outfit_scan_worker = _ScanWorker(scan_armors, self.instance, self.game_data_dir)
        self._outfit_scan_worker.done.connect(self._on_outfits_scanned)
        self._outfit_scan_worker.failed.connect(self._on_scan_failed(self.scan_outfit_button, "Scan Load Order for Armor"))
        self._outfit_scan_worker.start()

    def _on_outfits_scanned(self, results):
        self._outfit_scan_worker = None
        self.scan_classes_button.setEnabled(True)
        self.scan_spells_button.setEnabled(True)
        self.scan_outfit_button.setEnabled(True)
        self.scan_outfit_button.setText("Scan Load Order for Armor")
        # Same reasoning as spells: an unnamed ARMO is almost always a
        # script-internal/placeholder piece the game never shows a name for
        # either, not something worth offering here.
        named = [r for r in results if r.full_name]
        self._all_armors = named
        skipped = len(results) - len(named)
        self.outfit_status.setText(
            f"{len(named)} named armor/clothing item(s) found across your active load order "
            f"({skipped} unnamed piece(s) hidden). Check one or more to build her default outfit."
        )
        self._populate_outfits(named)

    def _populate_outfits(self, armors):
        previously_checked = {
            self.outfit_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.outfit_list.count())
            if self.outfit_list.item(i).checkState() == Qt.CheckState.Checked
        }
        self.outfit_list.clear()
        for record in sorted(armors, key=lambda r: (r.full_name or r.edid).lower()):
            display_name = record.full_name or _humanize_edid(record.edid)
            label = f"{display_name}  --  {record.plugin}"
            item = QListWidgetItem(label)
            item.setToolTip(f"EDID: {record.edid}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            key = (record.plugin, record.form_id_hex)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setCheckState(Qt.CheckState.Checked if key in previously_checked else Qt.CheckState.Unchecked)
            self.outfit_list.addItem(item)

    def _filter_outfit_items(self, text: str):
        text = text.strip().lower()
        matches = [
            a for a in self._all_armors
            if text in a.edid.lower() or (a.full_name and text in a.full_name.lower())
        ] if text else self._all_armors
        self._populate_outfits(matches)

    # ---- Read back for the build step ----

    def class_edid(self) -> str | None:
        data = self.class_combo.currentData()
        if data:
            return data
        text = self.class_combo.currentText().strip()
        # Allow typing a class EDID directly even if it was never scanned/listed.
        if text and text != "(leave as donor's class)":
            return text
        return None

    def skill_values(self) -> list[int]:
        return [spin.value() for spin in self.skill_spinboxes]

    def selected_spells(self) -> list[tuple[str, str]]:
        return [
            self.spell_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.spell_list.count())
            if self.spell_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def selected_outfit_items(self) -> list[tuple[str, str]]:
        return [
            self.outfit_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.outfit_list.count())
            if self.outfit_list.item(i).checkState() == Qt.CheckState.Checked
        ]
