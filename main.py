import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from core.paths import get_root_dir
from ui.main_window import MainWindow

FONTS_DIR = get_root_dir() / "assets" / "fonts"

# Fallback family names used by theme.qss if a given font file fails to load
# or the real embedded family name can't be resolved for some reason.
FALLBACK_FAMILIES = {
    "display": "Cinzel Decorative",
    "heading": "Cinzel",
    "body": "Cormorant Garamond",
}


def load_custom_fonts() -> dict:
    """Load the bundled gothic font files and return the real family names
    Qt resolved them to, keyed by role (display / heading / body)."""
    families = dict(FALLBACK_FAMILIES)

    font_files = {
        "display": "CinzelDecorative-Black.ttf",
        "heading": "Cinzel-Variable.ttf",
        "body": "CormorantGaramond-Variable.ttf",
    }
    # Also load the secondary decorative weight so it's available if needed.
    extra_files = ["CinzelDecorative-Regular.ttf"]

    for role, filename in font_files.items():
        font_path = FONTS_DIR / filename
        if not font_path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id == -1:
            continue
        loaded = QFontDatabase.applicationFontFamilies(font_id)
        if loaded:
            families[role] = loaded[0]

    for filename in extra_files:
        font_path = FONTS_DIR / filename
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))

    return families


def load_stylesheet(families: dict) -> str:
    qss_path = get_root_dir() / "ui" / "theme.qss"
    text = qss_path.read_text(encoding="utf-8")
    text = text.replace("__DISPLAY_FONT__", families["display"])
    text = text.replace("__HEADING_FONT__", families["heading"])
    text = text.replace("__BODY_FONT__", families["body"])
    return text


def main():
    app = QApplication(sys.argv)

    icon_path = get_root_dir() / "assets" / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    families = load_custom_fonts()
    app.setStyleSheet(load_stylesheet(families))
    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
