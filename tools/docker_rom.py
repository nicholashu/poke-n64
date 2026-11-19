#!/usr/bin/env python3
"""Build using a Linux toolchain container native to the active Docker engine."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from bootstrap import ROOT
from build_rom import select_rom

IMAGE = "poke-n64-build"


def bind_mount(source: Path, target: str, readonly: bool = False) -> str:
    """Docker's --mount value is CSV, not shell text; quote commas in paths."""
    result = io.StringIO()
    fields = ["type=bind", f"source={source}", f"target={target}"]
    if readonly:
        fields.append("readonly")
    csv.writer(result, lineterminator="\r\n").writerow(fields)
    return result.getvalue()[:-2]


def docker_environment() -> tuple[str, str]:
    """Return the CLI and native daemon platform, including with remote contexts."""
    executable = shutil.which("docker")
    if not executable:
        raise RuntimeError(
            "Docker was not found. Install and open Docker Desktop, then run "
            "make rom-docker again. On Apple Silicon, use the Apple Silicon installer: "
            "https://docs.docker.com/desktop/setup/install/mac-install/"
        )
    try:
        result = subprocess.run(
            [executable, "info", "--format",
             '{"os":{{json .OSType}},"arch":{{json .Architecture}}}'],
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
    try:
        details = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Docker returned invalid system information. Check docker info and retry.") from exc
    if not isinstance(details, dict) or not all(isinstance(details.get(k), str) for k in ("os", "arch")):
        raise RuntimeError("Docker did not report its operating system and architecture. Check docker info.")
    if details["os"].lower() != "linux":
        raise RuntimeError("The N64 builder requires a Linux Docker engine. Select Linux containers and retry.")
    architectures = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}
    architecture = architectures.get(details["arch"].lower())
    if architecture is None:
        raise RuntimeError(f"Unsupported Docker engine architecture: {details['arch']!r}. Expected AMD64 or ARM64.")
    return executable, "linux/" + architecture


def run_in_docker(base: Path | None, jobs: int, check_tools: bool = False) -> None:
    if base is None and not check_tools:
        raise RuntimeError("A validated base ROM is required.")
    executable, platform = docker_environment()
    architecture = platform.split("/")[1]
    image = f"{IMAGE}-{architecture}"
    engine = f"/project/build/docker-engine-{architecture}"
    jobs = max(1, jobs)
    print(f"Using native Docker platform: {platform}", flush=True)
    # Only the build recipe is sent to the Docker image builder. Source code,
    # input ROMs and output files are supplied through local runtime mounts.
    context = ROOT / "tools/docker-context"
    # docker build's implicit builder follows the active daemon. A user-selected
    # buildx builder might be on another CPU, so omit that override for this call.
    build_environment = os.environ.copy()
    build_environment.pop("BUILDX_BUILDER", None)
    subprocess.run(
        [executable, "build", "--platform", platform, "--tag", image,
         "--file", str(ROOT / "Dockerfile"), str(context)],
        cwd=ROOT, env=build_environment, check=True,
    )
    command = [executable, "run", "--rm", "--platform", platform,
               "--mount", bind_mount(ROOT.resolve(), "/project")]
    roms = ROOT / "roms"
    if roms.is_dir():
        command += ["--mount", bind_mount(roms.resolve(), "/project/roms", readonly=True)]
    if check_tools:
        # Exercise the actual host tools and native Python dependencies on each
        # CPU. Object compilation alone cannot reveal host architecture failures.
        checks = [
            ["python3", "tools/build_env.py"],
            ["python3", "tools/check_native.py", "--require-mips", "--engine", engine],
            ["make", "--directory", engine, "VERSION=ntsc-1.2", "REGION=US",
             "DEBUG_FEATURES=0", f"N_THREADS={jobs}", "venv"],
            ["make", "--directory", engine + "/tools", f"-j{jobs}"],
            [engine + "/.venv/bin/python3", "-c",
             "import crunch64, ipl3checksum, pygfxd, rabbitizer, yaml, elftools; "
             "print('Native Python build dependencies loaded successfully.')"],
            [engine + "/tools/Flips/flips", "--version"],
        ]
        for arguments in checks:
            subprocess.run(command + [image, *arguments], cwd=ROOT, check=True)
        print("Docker host tools and native objects checked. No ROM was linked or run.")
        return
    command += ["--mount", bind_mount(base.resolve(), "/inputs/base.z64", readonly=True),
                image, "python3", "tools/build_rom.py", "--rom", "/inputs/base.z64",
                "--engine", engine, "--jobs", str(jobs)]
    subprocess.run(command, cwd=ROOT, check=True)
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
