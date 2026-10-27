from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QCheckBox, QLineEdit, QListWidget,
    QListWidgetItem, QHBoxLayout
)
from PySide6.QtCore import Qt


class HeadStandardTab(QWidget):
    """
    Head standard as checkboxes (High Poly Head / COtR / UBE Head) instead of
    a single-choice dropdown -- check whichever your follower actually needs.
    Below, a searchable list of the matching files for whatever's checked.
    """

    def __init__(self, candidates: dict[str, list[str]]):
        super().__init__()
        self._candidates = candidates
        layout = QVBoxLayout(self)

        heading = QLabel("Head")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        sub = QLabel("Check the head standard(s) this follower uses.")
        sub.setObjectName("subheading")
        layout.addWidget(sub)

        check_box = QGroupBox("Head standards found in your load order")
        check_layout = QHBoxLayout()
        self.checkboxes: dict[str, QCheckBox] = {}
        for standard, paths in candidates.items():
            cb = QCheckBox(f"{standard} ({len(paths)})")
            cb.setProperty("standard_key", standard)
            cb.stateChanged.connect(self._refresh_list)
            check_layout.addWidget(cb)
            self.checkboxes[standard] = cb
        check_box.setLayout(check_layout)
        layout.addWidget(check_box)

        list_box = QGroupBox("Matching files")
        list_layout = QVBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search matching files...")
        self.search_box.textChanged.connect(self._refresh_list)
        list_layout.addWidget(self.search_box)
        self.list_widget = QListWidget()
        list_layout.addWidget(self.list_widget)
        list_box.setLayout(list_layout)
        layout.addWidget(list_box)

        self._refresh_list()

    def _refresh_list(self, *_args):
        from pathlib import Path as _Path
        checked_standards = [s for s, cb in self.checkboxes.items() if cb.isChecked()]
        search_text = self.search_box.text().strip().lower()

        self.list_widget.clear()
        paths: list[str] = []
        for standard in checked_standards:
            paths.extend(self._candidates.get(standard, []))

        if search_text:
            paths = [p for p in paths if search_text in _Path(p).name.lower()]

        if not paths:
            placeholder = "(check a head standard above)" if not checked_standards else "(no matching files)"
            self.list_widget.addItem(placeholder)
            return

        for p in paths:
            item = QListWidgetItem(_Path(p).name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.list_widget.addItem(item)

    def checked_standards(self) -> list[str]:
        return [s for s, cb in self.checkboxes.items() if cb.isChecked()]

    def selected_path(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)
