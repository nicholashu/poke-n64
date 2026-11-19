#!/usr/bin/env python3
"""Launch the OoT total-conversion ROM in a clean, isolated RetroArch session.

Each invocation has a unique savefile/savestate directory, so a previous ROM's
SRAM or savestate cannot accidentally be restored. Existing saved files and
the user's ParaLLEl graphics settings are never modified or deleted.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_DATA = Path.home() / "Library/parallel-launcher/data"
RETROARCH_APP = LAUNCHER_DATA / "retroarch/RetroArch.app"
RETROARCH_CONFIG = LAUNCHER_DATA / "retroarch.cfg"
RETROARCH_CORE = LAUNCHER_DATA / "retro-data/cores/parallel_n64_next_libretro.dylib"
ROM_DEFAULT = ROOT / "build/poke-n64-oot.z64"
SESSIONS_ROOT = ROOT / "build/emulator-sessions"


def quote_config(value: Path | str) -> str:
    """Write a quoted RetroArch config string, with no shell interpolation."""
    raw = str(value)
    if "\n" in raw or "\r" in raw:
        raise ValueError("RetroArch configuration paths must not contain newlines")
    return '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


def session_overlay(save_dir: Path, state_dir: Path) -> str:
    """Overrides only save/state, shader/filter and config-write settings.

    Deliberately keep the user's Vulkan, ParaLLEl RDP/RSP, audio and input
    settings intact. No previously saved game state can be read from these
    newly created directories.
    """
    options = {
        "savefile_directory": str(save_dir),
        "savestate_directory": str(state_dir),
        "savestate_auto_load": "false",
        "savestate_auto_save": "false",
        "sort_savefiles_enable": "false",
        "sort_savestates_enable": "false",
        "video_filter": "",
        "video_shader_enable": "false",
        "config_save_on_exit": "false",
    }
    return "".join(f"{key} = {quote_config(value)}\n" for key, value in options.items())


def launch_args(app: Path, config: Path, core: Path, rom: Path, overlay: Path) -> list[str]:
    """Pass each argument separately so spaces in macOS paths remain safe."""
    return [
        "open", "-n", "-a", str(app), "--args",
        "-c", str(config),
        f"--appendconfig={overlay}",
        "-L", str(core),
        "--no-patch", str(rom),
    ]


def running_emulators(binary: Path, rom: Path, process_listing: str) -> list[int]:
    """Match only the actual emulator executable launched with this ROM."""
    matches = []
    for line in process_listing.splitlines():
        pieces = line.strip().split(maxsplit=1)
        if len(pieces) != 2 or not pieces[0].isdigit():
            continue
        command = pieces[1]
        if command.startswith(str(binary) + " ") and str(rom) in command:
            matches.append(int(pieces[0]))
    return matches


def ensure_not_running(binary: Path, rom: Path) -> None:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True
    )
    running = running_emulators(binary, rom, result.stdout)
    if running:
        raise RuntimeError(
            "This ROM is already running in RetroArch (PID " +
            ", ".join(map(str, running)) + "). Quit that emulator window, " +
            "then launch again for a fresh session. No saved data was changed."
        )


def validate_inputs(rom: Path, app: Path, config: Path, core: Path) -> None:
    for kind, path in [
        ("OoT conversion ROM", rom),
        ("ParaLLEl launcher app", app),
        ("ParaLLEl launcher config", config),
        ("ParaLLEl N64 core", core),
    ]:
        expected = path.is_dir() if kind.endswith("app") else path.is_file()
        if not expected:
            raise RuntimeError(f"Missing {kind}: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=ROM_DEFAULT)
    parser.add_argument("--app", type=Path, default=RETROARCH_APP)
    parser.add_argument("--config", type=Path, default=RETROARCH_CONFIG)
    parser.add_argument("--core", type=Path, default=RETROARCH_CORE)
    parser.add_argument("--sessions-root", type=Path, default=SESSIONS_ROOT)
    parser.add_argument("--dry-run", action="store_true",
                        help="show a preview command without launching or creating files")
    args = parser.parse_args()
    try:
        rom, app, config, core = (
            p.expanduser().resolve() for p in
            (args.rom, args.app, args.config, args.core)
        )
        validate_inputs(rom, app, config, core)
        binary = app / "Contents/MacOS/RetroArch"
        if not binary.is_file():
            raise RuntimeError(f"Launcher app has no RetroArch executable: {binary}")
        if not args.dry_run:
            ensure_not_running(binary, rom)

        session_name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        session = args.sessions_root.expanduser().resolve() / session_name
        overlay = session / "clean-launch.cfg"
        command = launch_args(app, config, core, rom, overlay)

        if args.dry_run:
            print("Preview only. A unique session directory will be created on a real launch.")
            print("Config override:\n" + session_overlay(session / "saves", session / "states"))
            print("Command: " + shlex.join(command))
            return

        (session / "saves").mkdir(parents=True)
        (session / "states").mkdir()
        overlay.write_text(session_overlay(session / "saves", session / "states"), encoding="utf-8")
        print(f"Fresh emulator session: {session}", flush=True)
        print("Existing SRAM and savestates are isolated, never deleted.", flush=True)
        print("Auto restore, saved shader/filter and auto patching are disabled.", flush=True)
        print("Command: " + shlex.join(command), flush=True)
        subprocess.run(command, check=True)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Clean emulator launch failed: {exc}\n")


if __name__ == "__main__":
    main()
