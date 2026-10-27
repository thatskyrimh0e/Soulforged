"""
Resolves the project's root folder for bundled resources (ui/, assets/,
scripts/, config/), working the same way whether the app is run from
source ("python main.py") or as a built FollowerBuilder.exe (PyInstaller
onedir build via build_exe.bat).
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from uuid import UUID

# FOLDERID_Desktop -- a stable Windows constant, not something that changes
# per install. SHGetKnownFolderPath resolves this correctly even when the
# user's Desktop has been redirected (e.g. by OneDrive, as it is here) --
# unlike guessing "%USERPROFILE%\\Desktop", which breaks in exactly that case.
_FOLDERID_DESKTOP = UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")


def get_desktop_dir() -> Path:
    """The user's real Desktop folder, OneDrive redirection and all."""
    if sys.platform == "win32":
        try:
            buf = ctypes.c_wchar_p()
            guid = ctypes.create_string_buffer(_FOLDERID_DESKTOP.bytes_le, 16)
            result = ctypes.windll.shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(buf))
            if result == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Desktop"


def get_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller sets sys._MEIPASS; in a --onedir build this is the
        # app's own "_internal" resources folder, which is where
        # --add-data resources (ui/, assets/, config/) get copied to.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def get_output_root() -> Path:
    """
    Where built follower mod folders go: a "Soulforged Output" folder
    right on the user's Desktop -- somewhere obvious and outside any
    game/MO2 install, ready to find and drag into MO2 (or wherever) as a
    new mod. Deliberately
    NOT get_root_dir() or anything relative to the app itself: in a frozen
    build that's the buried "_internal" resources folder, and either way a
    rebuild of the app shouldn't put a build's own output at risk.
    """
    return get_desktop_dir() / "Soulforged Output"
