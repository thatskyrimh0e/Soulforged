from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QListWidget, QListWidgetItem,
    QComboBox, QLineEdit
)
from PySide6.QtCore import Qt
from pathlib import Path


class AssetTab(QWidget):
    """
    Generic tab for picking a standard (dict input) or browsing a flat list
    (list input) of matching assets, with a search box to filter the list.
    """

    def __init__(self, title: str, subtitle: str, candidates: dict[str, list[str]] | list[str]):
        super().__init__()
        self._dict_candidates = candidates if isinstance(candidates, dict) else None
        self._flat_candidates = candidates if isinstance(candidates, list) else None

        layout = QVBoxLayout(self)

        heading = QLabel(title)
        heading.setObjectName("heading")
        layout.addWidget(heading)
        sub = QLabel(subtitle)
        sub.setObjectName("subheading")
        layout.addWidget(sub)

        self.standard_combo: QComboBox | None = None

        if self._dict_candidates is not None:
            box = QGroupBox("Standard found in your load order")
            box_layout = QVBoxLayout()
            self.standard_combo = QComboBox()
            for standard, paths in self._dict_candidates.items():
                label = f"{standard}  ({len(paths)} files found)" if paths else f"{standard}  (none found)"
                self.standard_combo.addItem(label, standard)
            self.standard_combo.currentIndexChanged.connect(self._refresh)
            box_layout.addWidget(self.standard_combo)
            box.setLayout(box_layout)
            layout.addWidget(box)

        list_box = QGroupBox("Matching items")
        list_layout = QVBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.textChanged.connect(self._refresh)
        list_layout.addWidget(self.search_box)
        self.list_widget = QListWidget()
        list_layout.addWidget(self.list_widget)
        list_box.setLayout(list_layout)
        layout.addWidget(list_box)

        self._refresh()

    def _current_paths(self) -> list[str]:
        if self._dict_candidates is not None and self.standard_combo is not None:
            key = self.standard_combo.currentData()
            return self._dict_candidates.get(key, [])
        return self._flat_candidates or []

    def _refresh(self, *_args):
        paths = self._current_paths()
        search_text = self.search_box.text().strip().lower()
        if search_text:
            paths = [p for p in paths if search_text in Path(p).name.lower()]

        self.list_widget.clear()
        if not paths:
            self.list_widget.addItem("(none found)")
            return
        for p in paths:
            item = QListWidgetItem(Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.list_widget.addItem(item)

    def selected_standard(self) -> str | None:
        return self.standard_combo.currentData() if self.standard_combo else None

    def selected_path(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)
