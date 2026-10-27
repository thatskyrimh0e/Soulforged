"""
Drives SSEEdit/xEdit to create the follower's NPC_ record, via the
CreateFollower.pas script (scripts/xedit/CreateFollower.pas).

xEdit scripts can't take CLI arguments directly, so this writes a small
"follower_params.txt" key=value file into xEdit's own "Edit Scripts" folder
right next to the script, runs xEdit with -script:, and then reads back
"follower_result.txt" that the script writes when it's done.
"""
from __future__ import annotations
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from core import jslot_reader, mo2_launch

SCRIPT_NAME = "CreateFollower.pas"
STRIP_SCRIPT_NAME = "StripHPHMaster.pas"
PARAMS_FILE = "follower_params.txt"
RESULT_FILE = "follower_result.txt"
STRIP_RESULT_FILE = "follower_strip_result.txt"
RESULT_TIMEOUT_SECONDS = 120


# Internal default "donor" NPC -- the Player's own base actor record. It's
# guaranteed to exist in every install, has every required subrecord already
# populated correctly (class, combat style, AI data, etc.), and carries no
# unique quest baggage once cloned. This is what removes the need for the
# user to hunt down a donor plugin/form ID themselves -- race and sex are
# overwritten anyway, so which vanilla template gets cloned doesn't affect
# the final appearance.
DEFAULT_DONOR_PLUGIN = "Skyrim.esm"
DEFAULT_DONOR_FORMID = "00000007"  # Player


@dataclass
class FollowerSpec:
    new_plugin: str          # e.g. "MyFollower.esp"
    name: str
    race_edid: str = "NordRace"
    sex: str = "Female"      # "Male" or "Female"
    base_plugin: str = DEFAULT_DONOR_PLUGIN
    base_formid: str = DEFAULT_DONOR_FORMID
    jslot_path: str | None = None   # RaceMenu .jslot preset to apply (headParts/tints/hair/weight)


@dataclass
class FollowerResult:
    ok: bool
    message: str
    new_formid: str | None = None  # hex, local to its own plugin, e.g. "00000D62"


def _find_edit_scripts_dir(xedit_dir: Path) -> Path:
    candidate = xedit_dir / "Edit Scripts"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _find_xedit_exe(xedit_dir: Path) -> Path:
    # SSEEdit/FO4Edit/etc. ship under different exe names depending on game;
    # prefer the obvious SSEEdit.exe but fall back to any *Edit.exe present.
    preferred = xedit_dir / "SSEEdit.exe"
    if preferred.exists():
        return preferred
    for candidate in xedit_dir.glob("*Edit.exe"):
        return candidate
    raise FileNotFoundError(f"No xEdit executable (SSEEdit.exe / *Edit.exe) found in {xedit_dir}")


def _build_xedit_command(
    xedit_exe: Path,
    script_name: str,
    game_data_dir: str | Path | None,
    mo2_install_dir: str | Path | None,
    mo2_profile: str | None,
) -> list[str]:
    """See core/mo2_launch.py for why this goes through MO2 when configured."""
    xedit_args = ["-autoexit", f"-script:{script_name}"]
    if game_data_dir:
        xedit_args.append(f"-D:{game_data_dir}")
    return mo2_launch.build_command(xedit_exe, xedit_args, mo2_install_dir, mo2_profile)


def install_script(xedit_dir: str | Path, repo_script_path: str | Path) -> Path:
    """Copy one of our .pas scripts into xEdit's own Edit Scripts folder
    (idempotent), keeping the source file's own name as the destination."""
    xedit_dir = Path(xedit_dir)
    repo_script_path = Path(repo_script_path)
    scripts_dir = _find_edit_scripts_dir(xedit_dir)
    dest = scripts_dir / repo_script_path.name
    shutil.copyfile(repo_script_path, dest)
    return dest


def run_create_follower(
    xedit_dir: str | Path,
    spec: FollowerSpec,
    game_data_dir: str | Path | None = None,
    mo2_install_dir: str | Path | None = None,
    mo2_profile: str | None = None,
) -> FollowerResult:
    xedit_dir = Path(xedit_dir)
    scripts_dir = _find_edit_scripts_dir(xedit_dir)
    params_path = scripts_dir / PARAMS_FILE
    result_path = scripts_dir / RESULT_FILE

    if result_path.exists():
        result_path.unlink()

    param_lines = [
        f"NEW_PLUGIN={spec.new_plugin}",
        f"BASE_PLUGIN={spec.base_plugin}",
        f"BASE_FORMID={spec.base_formid}",
        f"NAME={spec.name}",
        f"RACE_EDID={spec.race_edid}",
        f"SEX={spec.sex}",
    ]

    if spec.jslot_path:
        jslot_data = jslot_reader.parse_jslot(spec.jslot_path)
        param_lines.extend(jslot_reader.to_params_lines(jslot_data))

    params_path.write_text("\n".join(param_lines), encoding="utf-8")

    exe = _find_xedit_exe(xedit_dir)
    cmd = _build_xedit_command(exe, SCRIPT_NAME, game_data_dir, mo2_install_dir, mo2_profile)
    via_mo2 = cmd[0] != str(exe)

    mo2_launch.launch(cmd, xedit_dir)

    waited = 0.0
    while waited < RESULT_TIMEOUT_SECONDS:
        if result_path.exists():
            text = result_path.read_text(encoding="utf-8", errors="replace")
            ok = "OK=True" in text or "OK=true" in text
            message = ""
            new_formid = None
            for line in text.splitlines():
                if line.startswith("MESSAGE="):
                    message = line[len("MESSAGE="):]
                elif line.startswith("NEW_FORMID="):
                    new_formid = line[len("NEW_FORMID="):].strip() or None
            if not via_mo2:
                message = (
                    "(launched xEdit directly, NOT through MO2 -- it only saw your real Data "
                    "folder's plugins, not your MO2 load order; set mo2_install_dir in "
                    "config/settings.json to fix this) " + message
                )
            return FollowerResult(ok=ok, message=message or text, new_formid=new_formid)
        time.sleep(1.0)
        waited += 1.0

    return FollowerResult(
        ok=False,
        message=(
            "Timed out waiting for xEdit to finish. xEdit may still be open waiting on a "
            "dialog (e.g. 'Apply Filter' or the master list) -- check its window, and close "
            "it manually once the follower is created."
        ),
    )


def run_strip_hph_master(
    xedit_dir: str | Path,
    new_plugin: str,
    game_data_dir: str | Path | None = None,
    mo2_install_dir: str | Path | None = None,
    mo2_profile: str | None = None,
) -> FollowerResult:
    """
    Run StripHPHMaster.pas against an already-created plugin. Only call this
    AFTER FaceGen has been generated for the follower (core.facegen_bridge) --
    running it earlier bakes the low-poly vanilla head instead of HPH's.
    """
    xedit_dir = Path(xedit_dir)
    scripts_dir = _find_edit_scripts_dir(xedit_dir)
    params_path = scripts_dir / PARAMS_FILE
    result_path = scripts_dir / STRIP_RESULT_FILE

    if result_path.exists():
        result_path.unlink()

    # Only NEW_PLUGIN matters to this script, but keep the file shape
    # consistent with CreateFollower.pas in case the same file is reused.
    params_path.write_text(f"NEW_PLUGIN={new_plugin}", encoding="utf-8")

    exe = _find_xedit_exe(xedit_dir)
    cmd = _build_xedit_command(exe, STRIP_SCRIPT_NAME, game_data_dir, mo2_install_dir, mo2_profile)

    mo2_launch.launch(cmd, xedit_dir)

    waited = 0.0
    while waited < RESULT_TIMEOUT_SECONDS:
        if result_path.exists():
            text = result_path.read_text(encoding="utf-8", errors="replace")
            ok = "OK=True" in text or "OK=true" in text
            message = ""
            for line in text.splitlines():
                if line.startswith("MESSAGE="):
                    message = line[len("MESSAGE="):]
            return FollowerResult(ok=ok, message=message or text)
        time.sleep(1.0)
        waited += 1.0

    return FollowerResult(
        ok=False,
        message="Timed out waiting for xEdit to finish stripping the HPH master reference.",
    )
