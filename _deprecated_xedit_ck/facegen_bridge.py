"""
Automates Skyrim SE/AE Creation Kit's FaceGen export for a follower plugin.

Mechanism (confirmed via community docs, see README "How FaceGen automation
works"): CK will export FaceGen (head NIF + FaceTint DDS) automatically the
moment you SAVE a plugin that's set as the active file, IF two ini flags are
on:

    DisableAutoFaceGen = 0
    DisableExportNIF   = 0

CK has no command-line flag to set a plugin "active" -- that still requires
driving the File > Data dialog -- so this module uses pywinauto (control/menu
lookups, not fixed pixel coordinates) to do just that one step, then saves
and waits for CK to finish writing FaceGen files before closing it.

This is best-effort GUI automation against a third-party application CK
doesn't officially script. Supervise the first run per machine/CK version;
if CK's dialog layout doesn't match, the relevant step raises instead of
clicking blind.
"""
from __future__ import annotations
import configparser
import time
from dataclasses import dataclass
from pathlib import Path

from core import mo2_launch

# pywinauto (and the comtypes/pywin32 it pulls in) initializes COM at IMPORT
# time, in a threading mode that conflicts with Qt's own COM initialization
# if imported before a QApplication exists ("COM error 0x80010106: Cannot
# change thread mode after it is set"). So this is imported lazily, only
# inside generate_facegen() -- by then Qt has already claimed its COM mode
# and pywinauto initializing afterward doesn't collide with it.

CK_SAVE_TIMEOUT_SECONDS = 180
CK_LOAD_TIMEOUT_SECONDS = 60


@dataclass
class FaceGenResult:
    ok: bool
    message: str


def _candidate_ini_paths(ck_dir: Path) -> list[Path]:
    # Different CK builds/years have used different ini filenames for this.
    # Patch whichever exist; CK reads whichever its version expects.
    return [
        ck_dir / "CreationKit.ini",
        ck_dir / "CreationKitCustom.ini",
        ck_dir / "SkyrimEditor.ini",
    ]


def ensure_facegen_autoexport(ck_dir: str | Path) -> list[Path]:
    """
    Patch CK's ini file(s) so saving the active plugin auto-exports FaceGen.
    Returns the list of ini files actually patched. Creates [General] /
    the relevant keys if missing; preserves everything else untouched.
    """
    ck_dir = Path(ck_dir)
    patched: list[Path] = []
    for ini_path in _candidate_ini_paths(ck_dir):
        if not ini_path.exists():
            continue
        parser = configparser.ConfigParser(strict=False)
        parser.optionxform = str  # preserve key casing
        parser.read(ini_path, encoding="utf-8")
        if "General" not in parser:
            parser["General"] = {}
        parser["General"]["bAllowMultipleMasterLoads"] = "1"
        parser["General"]["DisableAutoFaceGen"] = "0"
        parser["General"]["DisableExportNIF"] = "0"
        with open(ini_path, "w", encoding="utf-8") as f:
            parser.write(f)
        patched.append(ini_path)
    return patched


def generate_facegen(
    ck_exe: str | Path,
    plugin_name: str,
    timeout: int = CK_SAVE_TIMEOUT_SECONDS,
    mo2_install_dir: str | Path | None = None,
    mo2_profile: str | None = None,
) -> FaceGenResult:
    """
    Launch Creation Kit, set `plugin_name` as the active file via the File >
    Data dialog, save it (triggering FaceGen auto-export per the ini flags
    set by ensure_facegen_autoexport), wait for CK to finish, then close it.
    """
    try:
        from pywinauto import Application
        from pywinauto.findwindows import ElementNotFoundError
    except ImportError:
        return FaceGenResult(False, "pywinauto isn't installed (pip install -r requirements.txt) or this isn't Windows.")

    ck_exe = Path(ck_exe)
    note = ""
    try:
        # See core/mo2_launch.py: launched directly, CK only sees the real
        # Data folder, not MO2's virtual merge of the user's actual active
        # mods -- same problem as launching xEdit directly. Route it
        # through ModOrganizer.exe when configured; otherwise fall back to
        # starting it directly (and say so in the result).
        cmd = mo2_launch.build_command(ck_exe, [], mo2_install_dir, mo2_profile)
        via_mo2 = mo2_launch.launch(cmd, ck_exe.parent)
        if not via_mo2:
            note = (
                "(launched Creation Kit directly, NOT through MO2 -- it only saw your real "
                "Data folder's plugins, not your MO2 load order; set mo2_install_dir in "
                "config/settings.json to fix this) "
            )
            time.sleep(3)  # CK's splash/init is slow; give it room before probing windows
            app = Application(backend="win32").connect(path=str(ck_exe), timeout=CK_LOAD_TIMEOUT_SECONDS)
        else:
            # MO2 spawns CK as its own child under USVFS -- there's no direct
            # process handle for it from here, so connect by window title
            # instead of by the process .start()/.connect(path=...) would need.
            time.sleep(6)  # elevation prompt + CK splash/init both take a moment
            app = Application(backend="win32").connect(title_re=".*Creation Kit.*", timeout=CK_LOAD_TIMEOUT_SECONDS)
        main_win = app.window(title_re=".*Creation Kit.*")
        main_win.wait("visible", timeout=CK_LOAD_TIMEOUT_SECONDS)

        # File > Data...
        main_win.menu_select("File->Data")
        data_dlg = app.window(title_re="Data")
        data_dlg.wait("visible", timeout=15)

        # Double-click the target plugin in the list to set it active, then OK.
        plugin_list = data_dlg.child_window(class_name="ListBox")
        plugin_list.wait("visible", timeout=10)
        found = False
        for item in plugin_list.item_texts():
            if plugin_name.lower() in item.lower():
                plugin_list.select(item)
                found = True
                break
        if not found:
            data_dlg.close()
            main_win.close()
            return FaceGenResult(False, f"'{plugin_name}' wasn't in CK's Data dialog plugin list -- check it exists and CK's Data path is correct.")

        # "Set as Active File" is usually a double-click or a dedicated button labelled similarly.
        try:
            plugin_list.get_item(plugin_list.selected_indices()[0]).double_click_input()
        except Exception:
            pass
        ok_btn = data_dlg.child_window(title="OK", class_name="Button")
        ok_btn.click()

        # Loading a big master list can take a while and may prompt extra dialogs
        # (e.g. "would you like to create new ... forms?"); CK itself has no
        # single universal confirm here, so we give it time and proceed.
        time.sleep(5)

        # Save -> triggers FaceGen export per the ini flags.
        main_win.set_focus()
        main_win.type_keys("^s")

        waited = 0
        while waited < timeout:
            # CK blocks the UI while exporting; once the title bar stops showing
            # a busy/working state and no modal is present, treat it as done.
            time.sleep(2)
            waited += 2
            try:
                app.window(title_re=".*Working.*").wait_not("visible", timeout=1)
                break
            except Exception:
                continue

        main_win.close()
        return FaceGenResult(True, note + f"FaceGen export triggered for {plugin_name}. Check Data/Meshes and Data/Textures under actors/character/FaceGenData for the output.")
    except ElementNotFoundError as exc:
        return FaceGenResult(False, f"Couldn't find an expected CK window/control ({exc}). CK's dialog layout may differ for your version -- this step needs a one-time manual check.")
    except Exception as exc:
        return FaceGenResult(False, f"FaceGen automation failed: {exc}")
