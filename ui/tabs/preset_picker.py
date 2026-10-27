from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QGroupBox, QLabel, QPushButton, QTextEdit, QFileDialog,
)
from PySide6.QtCore import Qt


class PresetPicker(QWidget):
    """
    Searchable list of actual presets (RaceMenu .jslot presets, or BodySlide
    SliderSet presets) shown by their real display name only -- never a raw
    file path. The underlying ABSOLUTE path is kept on each item
    (Qt.UserRole) for when the Build step needs to actually open the file.

    Two optional extras, used for the Face Presets picker:
      - allow_browse / browse_filter: adds a "Browse for file..." button so
        the user can point at any .jslot on disk, not just ones this app's
        scanner found in the active mod list.
      - on_describe: a callable(path) -> list[str] of lines. When given,
        selecting (or browsing to) a preset immediately shows what's
        actually inside it below the list -- e.g. which head parts/plugins
        a .jslot references -- instead of just a bare name.
    """

    def __init__(
        self,
        title: str,
        presets: list,
        allow_browse: bool = False,
        browse_filter: str = "All files (*)",
        on_describe=None,
    ):
        super().__init__()
        self.on_describe = on_describe
        self.browse_filter = browse_filter
        layout = QVBoxLayout(self)

        box = QGroupBox(title)
        box_layout = QVBoxLayout()

        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(f"Search {title.lower()}...")
        self.search_box.textChanged.connect(self._filter)
        search_row.addWidget(self.search_box, 1)

        if allow_browse:
            self.browse_button = QPushButton("Browse...")
            self.browse_button.setObjectName("secondary")
            self.browse_button.clicked.connect(self._on_browse)
            search_row.addWidget(self.browse_button)
        box_layout.addLayout(search_row)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        box_layout.addWidget(self.list_widget)

        self.count_label = QLabel()
        self.count_label.setObjectName("subheading")
        box_layout.addWidget(self.count_label)

        if on_describe is not None:
            self.detail_view = QTextEdit()
            self.detail_view.setReadOnly(True)
            self.detail_view.setPlaceholderText("Select (or browse for) a preset to see what it actually contains.")
            self.detail_view.setFixedHeight(140)
            box_layout.addWidget(self.detail_view)
        else:
            self.detail_view = None

        box.setLayout(box_layout)
        layout.addWidget(box)

        self._all_presets = presets
        self._populate(presets)

    def _populate(self, presets: list):
        self.list_widget.clear()
        if not presets:
            self.count_label.setText("None found in your active mods.")
            return
        for preset in presets:
            item = QListWidgetItem(preset.name)
            abs_path = getattr(preset, "abs_path", "") or preset.relative_path
            item.setData(Qt.ItemDataRole.UserRole, abs_path)
            item.setToolTip(f"{preset.mod_name}  ->  {preset.relative_path}")
            self.list_widget.addItem(item)
        self.count_label.setText(f"{len(presets)} found")

    def _filter(self, text: str):
        text = text.strip().lower()
        matches = [p for p in self._all_presets if text in p.name.lower()] if text else self._all_presets
        self._populate(matches)
        if text:
            self.count_label.setText(f"{len(matches)} of {len(self._all_presets)} match \"{text}\"")

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a preset file", "", self.browse_filter)
        if not path:
            return

        # Simple namespace-free stand-in for a scanned PresetRef, just
        # enough for _populate()/selected_path()/selected_name() to work.
        class _AdHocPreset:
            pass

        from pathlib import Path as _Path
        ad_hoc = _AdHocPreset()
        ad_hoc.name = _Path(path).stem + "  (browsed)"
        ad_hoc.relative_path = path
        ad_hoc.mod_name = "(not from your load order)"
        ad_hoc.abs_path = path

        self._all_presets = [ad_hoc] + [p for p in self._all_presets if getattr(p, "abs_path", "") != path]
        self.search_box.clear()
        self._populate(self._all_presets)
        self.list_widget.setCurrentRow(0)

    def _on_selection_changed(self, current, _previous):
        if self.detail_view is None:
            return
        if current is None:
            self.detail_view.clear()
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        try:
            lines = self.on_describe(path)
        except Exception as exc:
            lines = [f"Could not read this preset: {exc}"]
        self.detail_view.setPlainText("\n".join(lines))

    def selected_name(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.text() if item else None

    def selected_path(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None
