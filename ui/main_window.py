import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QMainWindow, QMessageBox, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QListWidgetItem, QStackedWidget, QPushButton, QLabel, QFrame,
)

from core import mo2_reader, asset_scanner, follower_builder, facegen_copy
from core.paths import get_root_dir, get_output_root
from ui.tabs.project_tab import ProjectTab
from ui.tabs.export_tab import ExportTab
from ui.tabs.import_face_tab import ImportFaceTab
from ui.tabs.skills_tab import SkillsTab
from ui.dialogs.validator_dialog import ValidatorDialog

ROOT_DIR = get_root_dir()
SETTINGS_PATH = ROOT_DIR / "config" / "settings.json"
# Each build lands in its own self-contained mod folder here --
# the .esp plus its FaceGenData, ready to drop straight into MO2 as a new
# mod, rather than getting written into the live game install.
OUTPUT_ROOT = get_output_root()

STEP_NAMES = ["Import Face", "Character", "Skills", "Build"]


def _step_container(title: str, subtitle: str, *widgets: QWidget) -> QWidget:
    """Wraps one or more existing tab widgets into a single wizard step page
    with a shared heading."""
    page = QWidget()
    layout = QVBoxLayout(page)
    heading = QLabel(title)
    heading.setObjectName("heading")
    layout.addWidget(heading)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("subheading")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    for w in widgets:
        layout.addWidget(w, 1)
    return page


class _BuildWorker(QThread):
    """build_follower() can fall back to scanning the whole active load
    order (see core/follower_builder.py's _resolve_by_edid/_resolve_race) --
    even after that fast-path fix it's still real work, so it runs off the
    GUI thread like the Skills-tab scans, instead of freezing the window
    for however long it takes."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, spec, instance):
        super().__init__()
        self.spec = spec
        self.instance = instance

    def run(self):
        try:
            result = follower_builder.build_follower(self.spec, instance=self.instance)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soulforged")
        self.resize(1050, 700)

        self.settings = self._load_settings()

        try:
            profiles = mo2_reader.find_profiles(self.settings["mo2_install_dir"])
        except Exception as exc:
            QMessageBox.warning(self, "MO2 not found", f"Couldn't read your MO2 instance:\n{exc}")
            profiles = ["Default"]

        self.instance = None
        self.scan_results = None
        self._build_worker = None
        try:
            self.instance = mo2_reader.load_instance(
                self.settings["mo2_install_dir"], self.settings.get("mo2_profile", "Default")
            )
            self.scan_results = asset_scanner.scan(self.instance)
        except Exception as exc:
            QMessageBox.warning(self, "Scan failed", f"Couldn't scan your load order:\n{exc}")

        # --- Build the underlying step widgets (unchanged internals) ---
        self.project_tab = ProjectTab(self.settings, profiles)
        self.import_face_tab = ImportFaceTab(self.instance)
        ck_dir = self.settings.get("ck_dir")
        skills_game_data_dir = (Path(ck_dir) / "Data") if ck_dir else None
        self.skills_tab = SkillsTab(self.instance, skills_game_data_dir)
        self.export_tab = ExportTab()
        self.export_tab.build_button.clicked.connect(self._on_build_clicked)
        self.export_tab.use_exported_button.clicked.connect(self._on_use_exported_clicked)
        self.export_tab.open_output_button.clicked.connect(self._on_open_output_clicked)

        # --- Wizard pages, one per step ---
        self.stack = QStackedWidget()
        self.stack.addWidget(_step_container(
            "1. Import Face",
            "Browse for the RaceMenu preset (.jslot) you want this follower to use -- head parts, "
            "tints, hair color and weight are detected automatically, whatever head mod it needs "
            "(High Poly Head, COTR, or anything else). Any plugin it needs that isn't active in "
            "your load order gets flagged here too.",
            self.import_face_tab,
        ))
        self.stack.addWidget(_step_container(
            "2. Character", "Basic identity -- you'll pick body/physics/voice next.",
            self.project_tab,
        ))
        self.stack.addWidget(_step_container(
            "3. Skills", "She'll be built in vanilla gear, so set her class, per-skill levels, and any custom spells she should know instead.",
            self.skills_tab,
        ))
        self.stack.addWidget(_step_container(
            "4. Build", "", self.export_tab,
        ))

        # --- Left step rail (numbered wizard nav) ---
        self.nav = QListWidget()
        self.nav.setObjectName("wizardNav")
        for i, name in enumerate(STEP_NAMES, start=1):
            item = QListWidgetItem(f"{i}.  {name.replace('&&', '&')}")
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.validate_button = QPushButton("Validate Follower ESP...")
        self.validate_button.setObjectName("secondary")
        self.validate_button.clicked.connect(self._on_validate_clicked)

        # --- Back / Next footer ---
        self.back_button = QPushButton("< Back")
        self.back_button.setObjectName("secondary")
        self.next_button = QPushButton("Next >")
        self.back_button.clicked.connect(self._go_back)
        self.next_button.clicked.connect(self._go_next)
        footer = QHBoxLayout()
        footer.addWidget(self.back_button)
        footer.addStretch()
        footer.addWidget(self.next_button)

        right_side = QVBoxLayout()
        right_side.addWidget(self.stack, 1)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        right_side.addWidget(divider)
        right_side.addLayout(footer)
        right_widget = QWidget()
        right_widget.setLayout(right_side)

        nav_column = QVBoxLayout()
        nav_column.addWidget(self.nav, 1)
        nav_column.addWidget(self.validate_button)
        nav_widget = QWidget()
        nav_widget.setLayout(nav_column)
        nav_widget.setFixedWidth(190)

        central = QWidget()
        root = QHBoxLayout(central)
        root.addWidget(nav_widget)
        root.addWidget(right_widget, 1)
        self.setCentralWidget(central)

        self.stack.currentChanged.connect(self._sync_nav_buttons)
        self._sync_nav_buttons(0)

    # ---- Wizard navigation ----

    def _go_back(self):
        row = self.stack.currentIndex()
        if row > 0:
            self.nav.setCurrentRow(row - 1)

    def _go_next(self):
        row = self.stack.currentIndex()
        if row < self.stack.count() - 1:
            self.nav.setCurrentRow(row + 1)

    def _sync_nav_buttons(self, index: int):
        self.back_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < self.stack.count() - 1)
        self.next_button.setText("Next >" if index < self.stack.count() - 1 else "Done")

    # ---- Settings ----

    def _load_settings(self) -> dict:
        if SETTINGS_PATH.exists():
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return {"mo2_install_dir": "", "mo2_profile": "Default", "ck_dir": "", "last_project": None}

    # ---- Build actions ----

    def _follower_output_dir(self, plugin_name: str) -> Path:
        """The self-contained mod folder a given plugin's build/copy-head
        output goes into -- named after the plugin so both steps always
        agree on it, as long as the plugin name field hasn't changed."""
        return OUTPUT_ROOT / Path(plugin_name).stem

    def _on_build_clicked(self):
        if self._build_worker is not None:
            return

        project = self.project_tab.spec()
        plugin_name = self.export_tab.plugin_name()
        jslot_path = self.import_face_tab.selected_path()

        game_dir = self.settings.get("ck_dir")
        if not game_dir:
            QMessageBox.warning(self, "No game path", "Set ck_dir in config/settings.json first (it's used as the game's install folder).")
            return

        data_dir = Path(game_dir) / "Data"
        donor_plugin_path = data_dir / follower_builder.DEFAULT_DONOR_PLUGIN

        output_dir = self._follower_output_dir(plugin_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_plugin_path = output_dir / plugin_name

        spec = follower_builder.BuildSpec(
            output_plugin_path=str(output_plugin_path),
            name=project["name"],
            race_edid=project["race_edid"],
            sex=project["sex"],
            donor_plugin_path=str(donor_plugin_path),
            jslot_path=jslot_path,
            class_edid=self.skills_tab.class_edid(),
            skill_values=self.skills_tab.skill_values(),
            spell_refs=self.skills_tab.selected_spells(),
            outfit_items=self.skills_tab.selected_outfit_items(),
            location_cell_edid=project["location_cell_edid"],
        )

        if jslot_path:
            self.export_tab.append_log(
                f"Applying imported face: {self.import_face_tab.selected_name()} "
                "(head parts, tints, and weight -- see log for anything that didn't transfer cleanly)."
            )
        else:
            self.export_tab.append_log(
                "No face imported -- building with the donor template's default face. "
                "Import a RaceMenu preset on step 1 first if you want a specific look applied."
            )

        self.export_tab.append_log(f"Writing '{plugin_name}' into its own follower folder...")
        self.export_tab.build_button.setEnabled(False)
        self.export_tab.build_button.setText("Building...")

        self._build_worker = _BuildWorker(spec, self.instance)
        self._build_worker.done.connect(lambda result: self._on_build_done(result, plugin_name, output_dir))
        self._build_worker.failed.connect(self._on_build_failed)
        self._build_worker.start()

    def _on_build_finished_common(self):
        self.export_tab.build_button.setEnabled(True)
        self.export_tab.build_button.setText("Build")
        self._build_worker = None

    def _on_build_done(self, result, plugin_name, output_dir):
        self._on_build_finished_common()
        self.export_tab.append_log(("OK: " if result.ok else "FAILED: ") + result.message)
        for warning in result.warnings:
            self.export_tab.append_log(f"  - {warning}")
        if result.ok:
            self._last_plugin_name = plugin_name
            self._last_formid = result.new_formid
            self._last_output_dir = output_dir
            self.export_tab.use_exported_button.setEnabled(bool(result.new_formid))
            if result.new_formid:
                self.export_tab.set_exported_source(plugin_name, result.new_formid)
            self.export_tab.open_output_button.setEnabled(True)
            self.export_tab.append_log(
                f"Follower folder: {output_dir}"
            )
            self.export_tab.append_log(
                "Once step 2 is done, drop this whole folder into your MO2 mods folder as "
                "a new mod (or copy its contents straight into Data) -- it's fully self-contained, "
                "ready to use as-is."
            )

    def _on_build_failed(self, message):
        self._on_build_finished_common()
        self.export_tab.append_log(f"ERROR: {message}")

    def _on_use_exported_clicked(self):
        """
        Step 2 -- gives the new NPC its real face shape/texture. Copies a
        head already exported from RaceMenu in-game (its own head export
        option) into this NPC's FaceGenData paths, *inside its own follower
        output folder* -- not into the live game install -- so the finished
        folder is a complete, self-contained mod. This is the only
        face-fidelity mechanism now (no Creation Kit bake): the engine
        needs a baked mesh/texture to render a humanoid head at all, and a
        straight copy of what RaceMenu already exported reflects every
        sculpt-tool edit perfectly, which nothing else here could derive.
        """
        plugin_name = getattr(self, "_last_plugin_name", None)
        new_formid = getattr(self, "_last_formid", None)
        ck_dir = self.settings.get("ck_dir")

        if not plugin_name or not new_formid:
            QMessageBox.warning(self, "Build the NPC first", "Run step 1 (Build Follower NPC) before this.")
            return
        if not ck_dir:
            QMessageBox.warning(self, "No game path", "Set ck_dir in config/settings.json first (it's used as the game's install folder).")
            return

        # The common case needs nothing from the user: RaceMenu already saved
        # a matching head mesh/texture alongside the .jslot imported on step
        # 1 (see core/facegen_copy.find_chargen_siblings). The plugin/FormID
        # fields below are only a fallback, for a head exported live from an
        # actor instead. Where we WRITE is this build's own output folder
        # (see _on_build_clicked / _follower_output_dir).
        game_data_dir = Path(ck_dir) / "Data"
        output_dir = getattr(self, "_last_output_dir", None) or self._follower_output_dir(plugin_name)
        jslot_path = self.import_face_tab.selected_path()
        source_plugin = self.export_tab.exported_plugin()
        source_formid = self.export_tab.exported_formid()

        try:
            if jslot_path:
                self.export_tab.append_log(
                    f"Copying head from the imported preset ({Path(jslot_path).stem}) into {plugin_name}|{new_formid}..."
                )
            else:
                self.export_tab.append_log(
                    f"Copying exported head from {source_plugin}|{source_formid} into {plugin_name}|{new_formid}..."
                )
            result = facegen_copy.copy_exported_facegen(
                self.instance, game_data_dir, source_plugin, source_formid, plugin_name, new_formid,
                dest_root=output_dir, jslot_path=jslot_path,
            )
            self.export_tab.append_log(("OK: " if result.ok else "FAILED: ") + result.message)
            if result.ok:
                self._last_output_dir = output_dir
                self.export_tab.open_output_button.setEnabled(True)
        except Exception as exc:
            self.export_tab.append_log(f"ERROR: {exc}")

    def _on_validate_clicked(self):
        ck_dir = self.settings.get("ck_dir")
        game_data_dir = (Path(ck_dir) / "Data") if ck_dir else None
        dialog = ValidatorDialog(self, self.instance, game_data_dir)
        dialog.exec()

    def _on_open_output_clicked(self):
        output_dir = getattr(self, "_last_output_dir", None)
        if not output_dir or not Path(output_dir).exists():
            QMessageBox.warning(self, "Nothing built yet", "Build the follower (step 1) first.")
            return
        os.startfile(str(output_dir))
