from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QGroupBox, QLabel, QPushButton, QTextEdit
)


class ExportTab(QWidget):
    """
    Final step. No donor plugin/form ID to hunt down, and no external editor
    involved -- the NPC_ record is built and written directly as a new
    plugin (see core/follower_builder.py).
    """

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        heading = QLabel("Build")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        sub = QLabel(
            "Step 1 writes a brand new, self-contained follower mod folder to your Desktop "
            "(in a \"Soulforged Output\" folder) -- fully self-contained -- "
            "containing the plugin with the NPC_ record (race, sex, head parts, tints) built "
            "directly, no xEdit or Creation Kit involved, plus a meta.ini, credits.md, and an "
            "RSVignore _DISTR.ini. Step 2 drops the real face shape/texture into that same "
            "folder: copy a head you already exported in-game with RaceMenu's own export "
            "option (the only way to preserve sculpt-tool edits -- see the note below). Once "
            "both are done, drag the whole folder into MO2's mods folder as its own mod. "
            "BodySlide batch-building and DBVO line wiring still happen in their own tools "
            "afterward."
        )
        sub.setObjectName("subheading")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        plugin_box = QGroupBox("Output")
        form = QFormLayout()
        self.plugin_edit = QLineEdit("MyFollower.esp")
        form.addRow("New plugin name:", self.plugin_edit)
        plugin_box.setLayout(form)
        layout.addWidget(plugin_box)

        self.build_button = QPushButton("1. Build Follower NPC")
        layout.addWidget(self.build_button)

        export_box = QGroupBox("2. Use an Exported RaceMenu Head (face shape/texture)")
        export_form = QFormLayout()
        export_note = QLabel(
            "Head parts and tints transfer automatically, but a preset's manual sculpting "
            "and extended sliders only exist as a baked mesh/texture -- there's no way to "
            "derive those from plugin data alone. In-game, open RaceMenu on the actor with "
            "that face and use its head export option, then point this at who you exported:"
        )
        export_note.setWordWrap(True)
        export_note.setObjectName("subheading")
        export_form.addRow(export_note)
        self.exported_plugin_edit = QLineEdit("Skyrim.esm")
        export_form.addRow("Exported from plugin:", self.exported_plugin_edit)
        self.exported_formid_edit = QLineEdit("00000007")
        export_form.addRow("Exported from FormID (hex):", self.exported_formid_edit)
        export_box.setLayout(export_form)
        layout.addWidget(export_box)

        self.use_exported_button = QPushButton("2. Copy Exported Head")
        self.use_exported_button.setObjectName("secondary")
        self.use_exported_button.setEnabled(False)
        layout.addWidget(self.use_exported_button)

        self.open_output_button = QPushButton("Open Follower Folder")
        self.open_output_button.setObjectName("secondary")
        self.open_output_button.setEnabled(False)
        layout.addWidget(self.open_output_button)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def plugin_name(self) -> str:
        return self.plugin_edit.text().strip() or "MyFollower.esp"

    def exported_plugin(self) -> str:
        return self.exported_plugin_edit.text().strip() or "Skyrim.esm"

    def exported_formid(self) -> str:
        return self.exported_formid_edit.text().strip() or "00000007"

    def set_exported_source(self, plugin: str, formid_hex: str):
        """
        Called after a successful build. Defaults step 2's "exported from"
        fields to the follower's OWN plugin+FormID -- the normal workflow is
        to spawn the just-built follower in-game and export its head
        directly from RaceMenu while IT is the one open (which writes
        straight to that plugin+FormID's own FaceGenData), not to export
        from some other actor and copy across. The user can still overwrite
        these if they genuinely exported from somewhere else (e.g. the
        player wearing the same preset).
        """
        self.exported_plugin_edit.setText(plugin)
        self.exported_formid_edit.setText(formid_hex)

    def append_log(self, text: str):
        self.log.append(text)
