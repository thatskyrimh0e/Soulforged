from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QLabel, QPushButton, QTextEdit, QFileDialog
)

from core import jslot_reader


class ImportFaceTab(QWidget):
    """
    "Import Face" step: one action (browse for your RaceMenu
    .jslot export), after which everything about the face -- head parts,
    which plugins it needs, tints, hair color, weight -- is detected and
    shown automatically. No separate head-standard picker: whatever plugins
    the preset actually references (High Poly Head, COTR, UBE, or anything
    else) are read straight off the preset itself, so this isn't limited to
    a fixed list of known head standards.

    Also checks the detected plugins against the active MO2 load order and
    flags anything missing, since that's the single biggest reason a built
    follower comes out looking wrong (silently missing head part/texture).
    """

    def __init__(self, instance):
        super().__init__()
        self.instance = instance
        self._jslot_path: str | None = None

        layout = QVBoxLayout(self)

        box = QGroupBox("Import Face")
        box_layout = QVBoxLayout()

        self.browse_button = QPushButton("Browse for RaceMenu Preset (.jslot)...")
        self.browse_button.clicked.connect(self._on_browse)
        box_layout.addWidget(self.browse_button)

        self.loaded_label = QLabel("No preset loaded yet.")
        self.loaded_label.setObjectName("subheading")
        self.loaded_label.setWordWrap(True)
        box_layout.addWidget(self.loaded_label)

        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlaceholderText(
            "Head parts, tints, hair color, weight, and required plugins will show here once you import a preset."
        )
        box_layout.addWidget(self.detail_view, 1)

        self.check_label = QLabel("")
        self.check_label.setWordWrap(True)
        box_layout.addWidget(self.check_label)

        box.setLayout(box_layout)
        layout.addWidget(box, 1)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a RaceMenu preset", "", "RaceMenu Preset (*.jslot)")
        if not path:
            return
        self._load(path)

    def _load(self, path: str):
        self._jslot_path = path
        self.loaded_label.setText(f"Loaded: {Path(path).stem}")

        try:
            data = jslot_reader.parse_jslot(path)
        except Exception as exc:
            self.detail_view.setPlainText(f"Could not read this preset: {exc}")
            self.check_label.setText("")
            self._jslot_path = None
            return

        self.detail_view.setPlainText("\n".join(jslot_reader.describe_jslot(path)))

        active_plugins = self.instance.plugin_order if self.instance else []
        missing = jslot_reader.missing_plugins(data, active_plugins)
        if not active_plugins:
            self.check_label.setText(
                "Couldn't read your load order to check for missing plugins -- check config/settings.json."
            )
        elif missing:
            self.check_label.setText(
                "⚠ Missing from your load order (enable these in MO2 first): " + ", ".join(missing)
            )
        else:
            self.check_label.setText("✓ All required plugins are active in your load order.")

    def selected_path(self) -> str | None:
        return self._jslot_path

    def selected_name(self) -> str | None:
        return Path(self._jslot_path).stem if self._jslot_path else None
