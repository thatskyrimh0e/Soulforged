from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QLabel, QGroupBox
)

from core.follower_placement import CURATED_LOCATIONS

# Every vanilla + DLC humanoid race EDID a follower might plausibly use.
# This is a convenience pick-list, NOT a restriction -- the combo box below
# is editable, so typing any other race EDID (from a custom race mod, e.g.
# "NingheimRace" or a RaceMenu custom race) works exactly the same way; the
# xEdit side just sets RNAM by whatever EDID string ends up here.
VANILLA_RACES = [
    "NordRace",
    "ImperialRace",
    "BretonRace",
    "RedguardRace",
    "HighElfRace",
    "WoodElfRace",
    "DarkElfRace",
    "OrcRace",
    "KhajiitRace",
    "ArgonianRace",
]

VAMPIRE_RACES = [f"{r}Vampire" for r in VANILLA_RACES]

OTHER_RACES = [
    "ElderRace",
    "VampireLordRace",
    "WerewolfBeastRace",
]


class ProjectTab(QWidget):
    """Basic identity of the follower: name, race, sex, and the MO2/xEdit
    paths this project will read from."""

    def __init__(self, settings: dict, mo2_profiles: list[str]):
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)

        heading = QLabel("New Follower")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        sub = QLabel("Basic identity. You'll pick head/body/physics/voice assets in the other tabs.")
        sub.setObjectName("subheading")
        layout.addWidget(sub)

        form_box = QGroupBox("Identity")
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Princess Nyx")

        self.race_combo = QComboBox()
        self.race_combo.setEditable(True)
        self.race_combo.addItems(VANILLA_RACES)
        self.race_combo.insertSeparator(self.race_combo.count())
        self.race_combo.addItems(VAMPIRE_RACES)
        self.race_combo.insertSeparator(self.race_combo.count())
        self.race_combo.addItems(OTHER_RACES)
        self.race_combo.setCurrentText("NordRace")
        self.race_combo.setEditText("NordRace")
        self.race_combo.lineEdit().setPlaceholderText("Pick a race, or type a custom race mod's EDID")

        self.sex_combo = QComboBox()
        self.sex_combo.addItems(["Female", "Male"])
        form.addRow("Follower name:", self.name_edit)
        form.addRow("Race (EDID):", self.race_combo)
        form.addRow("Sex:", self.sex_combo)
        form_box.setLayout(form)
        layout.addWidget(form_box)

        location_box = QGroupBox("Location")
        location_form = QFormLayout()
        self.location_combo = QComboBox()
        self.location_combo.addItem("(Don't place automatically)", userData=None)
        for display_name, cell_edid in CURATED_LOCATIONS:
            self.location_combo.addItem(display_name, userData=cell_edid)
        location_form.addRow("Spawn location:", self.location_combo)
        location_hint = QLabel(
            "She'll move here automatically the first time your save loads this plugin -- "
            "a quest + script handles it, so there's no manual MoveTo needed."
        )
        location_hint.setObjectName("subheading")
        location_hint.setWordWrap(True)
        location_form.addRow(location_hint)
        location_box.setLayout(location_form)
        layout.addWidget(location_box)

        source_box = QGroupBox("Load order source")
        source_form = QFormLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(mo2_profiles)
        if self.settings.get("mo2_profile") in mo2_profiles:
            self.profile_combo.setCurrentText(self.settings["mo2_profile"])
        self.mo2_path_label = QLabel(self.settings.get("mo2_install_dir", ""))
        source_form.addRow("MO2 profile:", self.profile_combo)
        source_form.addRow("MO2 install dir:", self.mo2_path_label)
        source_box.setLayout(source_form)
        layout.addWidget(source_box)

        layout.addStretch()

    def spec(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or "New Follower",
            "race_edid": self.race_combo.currentText().strip() or "NordRace",
            "sex": self.sex_combo.currentText(),
            "profile": self.profile_combo.currentText(),
            "location_cell_edid": self.location_combo.currentData(),
        }
