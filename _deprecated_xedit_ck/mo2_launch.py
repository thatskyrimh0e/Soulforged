"""
Shared helper for launching an external tool (xEdit, Creation Kit) through
Mod Organizer 2's virtual filesystem instead of directly.

Launched directly, a tool only ever sees the REAL game Data folder -- MO2
keeps the user's actual mods in its own mods/<ModName>/ folders and only
merges them virtually (via USVFS) when something runs inside a profile's
VFS. So a direct launch sees a near-empty/vanilla Data folder, not the
user's real active load order -- wrong plugins.txt, missing meshes/head
parts, etc.

The fix: launch "ModOrganizer.exe -p <profile> <tool.exe> <tool args>"
instead of the tool directly. That applies the chosen profile's VFS before
the tool itself starts. ModOrganizer.exe's own manifest requires admin
elevation (it has to drive USVFS), and a plain subprocess.Popen can't
silently elevate a process -- it fails outright with "WinError 740: The
requested operation requires elevation" -- so it has to go through
ShellExecute's "runas" verb instead, which pops the normal Windows UAC
prompt rather than failing.
"""
from __future__ import annotations

import ctypes
import subprocess
from pathlib import Path


def find_mo2_exe(mo2_install_dir: str | Path | None) -> Path | None:
    """ModOrganizer.exe, if mo2_install_dir is set and it's actually there."""
    if not mo2_install_dir:
        return None
    candidate = Path(mo2_install_dir) / "ModOrganizer.exe"
    return candidate if candidate.exists() else None


def _quote_arg(arg: str) -> str:
    return f'"{arg}"' if " " in arg and not arg.startswith('"') else arg


def build_command(
    exe: str | Path,
    exe_args: list[str],
    mo2_install_dir: str | Path | None,
    mo2_profile: str | None,
) -> list[str]:
    """Builds the full command line: through MO2 if mo2_install_dir has a
    real ModOrganizer.exe and a profile was given, otherwise a direct
    launch of exe with exe_args."""
    mo2_exe = find_mo2_exe(mo2_install_dir)
    if mo2_exe and mo2_profile:
        return [str(mo2_exe), "-p", mo2_profile, str(exe)] + exe_args
    return [str(exe)] + exe_args


def launch(cmd: list[str], cwd: str | Path) -> bool:
    """
    Launches cmd (from build_command). Returns True if it went through
    ModOrganizer.exe (elevated via ShellExecute -- the caller doesn't get a
    normal subprocess handle for the real tool process in this case, since
    MO2 spawns it as its own child under USVFS), False if it was a direct
    launch via subprocess.Popen.
    """
    exe = cmd[0]
    if Path(exe).name.lower() == "modorganizer.exe":
        param_str = " ".join(_quote_arg(a) for a in cmd[1:])
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, param_str, str(cwd), 1)
        if result <= 32:
            raise OSError(
                f"Couldn't launch ModOrganizer.exe (ShellExecute error code {result}). "
                "If a UAC prompt appeared and you clicked 'No', try again and allow it."
            )
        return True
    subprocess.Popen(cmd, cwd=str(cwd))
    return False
