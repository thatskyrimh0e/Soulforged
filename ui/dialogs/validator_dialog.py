"""
Standalone "Validate Follower ESP" tool -- separate from the build wizard,
since it analyzes an existing plugin (yours or someone else's download)
rather than building a new one.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QTextEdit,
)

from core.esp_validator import validate_plugin
from core.esp_repair import repair_plugin

# Kept in one place so the colors work the same in light and dark Qt themes.
_BROKEN_COLOR = "#c0392b"   # red -- something is there but wrong
_MISSING_COLOR = "#b8860b"  # amber -- something isn't there at all
_CLEAN_COLOR = "#2e7d32"    # green
_MUTED_COLOR = "#777777"


class ValidatorDialog(QDialog):
    def __init__(self, parent, instance, game_data_dir):
        super().__init__(parent)
        self.instance = instance
        self.game_data_dir = game_data_dir
        self.setWindowTitle("Validate Follower ESP")
        self.resize(760, 600)

        layout = QVBoxLayout(self)

        heading = QLabel("Validate Follower ESP")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        subheading = QLabel(
            "Point this at any follower plugin -- one you built here, or one you downloaded -- "
            "and it checks masters, FormID references, and FaceGenData against your current "
            "MO2 load order."
        )
        subheading.setObjectName("subheading")
        subheading.setWordWrap(True)
        layout.addWidget(subheading)

        browse_row = QHBoxLayout()
        self.path_label = QLabel("No plugin selected.")
        self.path_label.setWordWrap(True)
        browse_row.addWidget(self.path_label, 1)
        self.browse_button = QPushButton("Browse for .esp / .esm...")
        self.browse_button.clicked.connect(self._on_browse)
        browse_row.addWidget(self.browse_button)
        self.repair_button = QPushButton("Repair...")
        self.repair_button.setEnabled(False)
        self.repair_button.clicked.connect(self._on_repair)
        browse_row.addWidget(self.repair_button)
        layout.addLayout(browse_row)

        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setPlaceholderText("Select a plugin above to see its validation report.")
        layout.addWidget(self.report_view, 1)

        self._current_path = None
        self._current_report = None

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_button = QPushButton("Close")
        close_button.setObjectName("secondary")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a follower plugin", "", "Skyrim plugins (*.esp *.esm)")
        if not path:
            return
        self.path_label.setText(path)
        self._run_validation(path)

    def _run_validation(self, path: str):
        self._current_path = path
        self._current_report = None
        self.repair_button.setEnabled(False)
        try:
            report = validate_plugin(path, instance=self.instance, game_data_dir=self.game_data_dir)
        except Exception as exc:
            self.report_view.setHtml(f"<p style='color:{_BROKEN_COLOR};'><b>Validation crashed:</b> {escape(str(exc))}</p>")
            return
        self._current_report = report
        self.repair_button.setEnabled(bool(report.broken()))
        self.report_view.setHtml(_render_report_html(report))

    def _on_repair(self):
        if not self._current_path or not self._current_report:
            return
        suggested = str(Path(self._current_path).with_name(Path(self._current_path).stem + "_repaired" + Path(self._current_path).suffix))
        output_path, _ = QFileDialog.getSaveFileName(self, "Save repaired plugin as...", suggested, "Skyrim plugins (*.esp *.esm)")
        if not output_path:
            return
        try:
            result = repair_plugin(
                self._current_path, output_path, self._current_report.masters, game_data_dir=self.game_data_dir,
            )
        except Exception as exc:
            self.report_view.setHtml(self.report_view.toHtml() + f"<p style='color:{_BROKEN_COLOR};'><b>Repair crashed:</b> {escape(str(exc))}</p>")
            return

        if not result.ok:
            self.report_view.setHtml(self.report_view.toHtml() + f"<p style='color:{_BROKEN_COLOR};'><b>Repair failed:</b> {escape(result.message)}</p>")
            return

        try:
            new_report = validate_plugin(output_path, instance=self.instance, game_data_dir=self.game_data_dir)
        except Exception:
            new_report = None

        self.path_label.setText(output_path)
        self._current_path = output_path
        self._current_report = new_report
        self.repair_button.setEnabled(bool(new_report and new_report.broken()))

        html = [f"<h3>Repaired -- saved to {escape(output_path)}</h3>"]
        if result.fixes:
            html.append(f"<p style='color:{_CLEAN_COLOR};'><b>Fixed:</b></p><ul>")
            for fix in result.fixes:
                html.append(f"<li>{escape(fix)}</li>")
            html.append("</ul>")
        if result.unfixable:
            html.append(f"<p style='color:{_MISSING_COLOR};'><b>Still needs manual attention (not auto-fixable):</b></p><ul>")
            for item in result.unfixable:
                html.append(f"<li>{escape(item)}</li>")
            html.append("</ul>")
        html.append("<hr>")
        if new_report is not None:
            html.append(_render_report_html(new_report))
        self.report_view.setHtml("\n".join(html))


def _render_report_html(report) -> str:
    broken = report.broken()
    missing = report.missing()
    info = report.info()

    parts = [
        f"<h2 style='margin-bottom:0;'>{escape(report.plugin_name)}</h2>",
        f"<p style='color:{_MUTED_COLOR}; margin-top:2px;'>{len(report.masters)} master(s) &nbsp;&middot;&nbsp; {report.npc_count} NPC_ record(s)</p>",
    ]

    if report.is_clean():
        parts.append(
            f"<p style='color:{_CLEAN_COLOR}; font-size:14px;'><b>&#10003; Nothing broken, nothing missing.</b> "
            "This plugin looks complete and consistent.</p>"
        )
    else:
        summary_bits = []
        if broken:
            summary_bits.append(f"<span style='color:{_BROKEN_COLOR};'><b>{len(broken)} broken</b></span>")
        if missing:
            summary_bits.append(f"<span style='color:{_MISSING_COLOR};'><b>{len(missing)} missing</b></span>")
        parts.append(f"<p style='font-size:14px;'>{' &nbsp;&middot;&nbsp; '.join(summary_bits)}</p>")

        if broken:
            parts.append(_section_html(
                f"&#10007; BROKEN -- {len(broken)} thing(s) are present but wrong (fix the plugin itself)",
                _BROKEN_COLOR, broken,
            ))
        if missing:
            parts.append(_section_html(
                f"&#9888; MISSING -- {len(missing)} thing(s) aren't there at all (add a file, enable a mod, or set a value)",
                _MISSING_COLOR, missing,
            ))

    if info:
        parts.append(_section_html("INFO", _MUTED_COLOR, info))

    if report.masters:
        parts.append(f"<p style='color:{_MUTED_COLOR}; margin-bottom:2px;'><b>Masters</b></p>")
        parts.append("<ul style='margin-top:2px;'>")
        for master in report.masters:
            parts.append(f"<li style='color:{_MUTED_COLOR};'>{escape(master)}</li>")
        parts.append("</ul>")

    return "\n".join(parts)


def _section_html(title: str, color: str, issues) -> str:
    rows = [f"<p style='color:{color}; font-weight:bold; margin-bottom:2px;'>{title}</p>", "<ul style='margin-top:2px;'>"]
    for issue in issues:
        rows.append(
            f"<li><span style='color:{color}; font-weight:bold;'>[{escape(issue.field)}]</span> {escape(issue.message)}</li>"
        )
    rows.append("</ul>")
    return "\n".join(rows)
