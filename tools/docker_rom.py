#!/usr/bin/env python3
"""Build on macOS/Linux using the project's amd64 Linux toolchain container."""
from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys

from bootstrap import ROOT
from build_rom import select_rom

IMAGE = "poke-n64-build"
PLATFORM = "linux/amd64"
ENGINE = "/project/build/docker-engine"


def bind_mount(source: Path, target: str, readonly: bool = False) -> str:
    """Docker's --mount value is CSV, not shell text; quote commas in paths."""
    result = io.StringIO()
    fields = ["type=bind", f"source={source}", f"target={target}"]
    if readonly:
        fields.append("readonly")
    csv.writer(result, lineterminator="\r\n").writerow(fields)
    return result.getvalue()[:-2]


def docker_cli() -> str:
    executable = shutil.which("docker")
    if not executable:
        raise RuntimeError(
            "Docker was not found. Install and open Docker Desktop, then run "
            "make rom-docker again. On Apple Silicon, use the Apple Silicon installer: "
            "https://docs.docker.com/desktop/setup/install/mac-install/"
        )
    try:
        result = subprocess.run(
            [executable, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Docker did not respond. Open Docker Desktop and wait until its engine "
            "is running, then retry make rom-docker."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            "Docker is installed but its engine is unavailable. Open Docker Desktop "
            "and wait until it is running, then retry make rom-docker. "
            "If using another Docker runtime, check its active context and permissions."
        )
    return executable


def run_in_docker(base: Path | None, jobs: int, check_tools: bool = False) -> None:
    if base is None and not check_tools:
        raise RuntimeError("A validated base ROM is required.")
    executable = docker_cli()
    # Only the build recipe is sent to the Docker image builder. Source code,
    # input ROMs and output files are supplied through local runtime mounts.
    context = ROOT / "tools/docker-context"
    subprocess.run(
        [executable, "build", "--platform", PLATFORM, "--tag", IMAGE,
         "--file", str(ROOT / "Dockerfile"), str(context)],
        cwd=ROOT, check=True,
    )
    command = [executable, "run", "--rm", "--platform", PLATFORM,
               "--mount", bind_mount(ROOT.resolve(), "/project")]
    roms = ROOT / "roms"
    if roms.is_dir():
        command += ["--mount", bind_mount(roms.resolve(), "/project/roms", readonly=True)]
    if check_tools:
        # Also run the host preflight in the actual container; no ROM is needed.
        subprocess.run(command + [IMAGE, "python3", "tools/build_env.py"], cwd=ROOT, check=True)
        subprocess.run(command + [IMAGE, "python3", "tools/check_native.py", "--require-mips",
                                  "--engine", ENGINE], cwd=ROOT, check=True)
        # Exercise the upstream toolchain detection too. This target's dry run
        # parses the real Makefiles without installing dependencies or using ROMs.
        command += [IMAGE, "make", "--directory", ENGINE, "--dry-run", "VERSION=ntsc-1.2",
                    "REGION=US", "DEBUG_FEATURES=0", f"N_THREADS={max(1, jobs)}", "venv"]
    else:
        command += ["--mount", bind_mount(base.resolve(), "/inputs/base.z64", readonly=True),
                    IMAGE, "python3", "tools/build_rom.py", "--rom", "/inputs/base.z64",
                    "--engine", ENGINE, "--jobs", str(max(1, jobs))]
    subprocess.run(command, cwd=ROOT, check=True)
    if check_tools:
        print("Docker toolchain and native objects checked. No ROM was linked or run.")
    else:
        print(f"Outputs: {ROOT / 'build/poke-n64.z64'} and {ROOT / 'build/poke-n64.bps'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    environment_rom = os.environ.get("POKE_N64_ROM")
    parser.add_argument("--rom", type=Path,
                        default=Path(environment_rom) if environment_rom else None)
    parser.add_argument("--roms-dir", type=Path, default=ROOT / "roms")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    parser.add_argument("--check-tools", action="store_true",
                        help="build the image and compile native objects without a ROM")
    args = parser.parse_args()
    if args.check_tools:
        run_in_docker(None, args.jobs, check_tools=True)
    else:
        # Fail on missing or mismatched input before any Docker downloads/writes.
        path, _ = select_rom(args.rom, args.roms_dir)
        print(f"Validated base ROM: {path}", flush=True)
        run_in_docker(path, args.jobs)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Docker ROM build failed: {exc}")
