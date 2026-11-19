#!/usr/bin/env python3
"""Validate or build with a local OoT US NTSC 1.2 image, auto-detected in roms/."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import os
import shutil
import subprocess
import sys
from bootstrap import DEFAULT_ENGINE, LOCK, ROOT, install


def normalized_rom(path: Path) -> bytes:
    # Skip other games/archives without loading large files into memory.
    if path.stat().st_size != LOCK["base_rom_size"]:
        raise RuntimeError("Expected a 32 MiB Ocarina of Time US NTSC 1.2 ROM.")
    data = path.read_bytes()
    if len(data) != LOCK["base_rom_size"]:
        raise RuntimeError("Expected a 32 MiB Ocarina of Time US NTSC 1.2 ROM.")
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40":
        pass
    elif magic == b"\x37\x80\x40\x12":
        swapped = bytearray(len(data)); swapped[0::2] = data[1::2]; swapped[1::2] = data[0::2]; data = bytes(swapped)
    elif magic == b"\x40\x12\x37\x80":
        swapped = bytearray(len(data))
        for i in range(4): swapped[i::4] = data[3-i::4]
        data = bytes(swapped)
    else:
        raise RuntimeError("Unrecognized N64 ROM byte order/header.")
    actual = hashlib.md5(data).hexdigest()
    if actual != LOCK["base_rom_md5"]:
        raise RuntimeError(f"Wrong base ROM: normalized MD5 {actual}; expected {LOCK['base_rom_md5']} (US NTSC 1.2).")
    return data


def select_rom(explicit: Path | None, directory: Path) -> tuple[Path, bytes]:
    """Select by verified contents, never by a filename or directory order alone.

    An explicit invalid input fails rather than silently choosing another file.
    Multiple copies of the expected image normalize to the same checksum; use
    the first matching path in stable filename order. Other games are untouched.
    """
    if explicit is not None:
        return explicit, normalized_rom(explicit)
    if not directory.is_dir():
        raise RuntimeError(
            f"No local ROM folder at {directory}. Put your unzipped OoT US NTSC 1.2 "
            "dump in roms/, or pass --rom /path/to/oot.z64."
        )
    extensions = {".z64", ".n64", ".v64", ".rom", ".bin"}
    candidates = sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in extensions),
        key=lambda p: (p.name.casefold(), p.name),
    )
    if not candidates:
        raise RuntimeError(
            f"No unzipped N64 images in {directory}. Expected .z64, .n64 or .v64; "
            "archives must be extracted first."
        )
    rejected = []
    for path in candidates:
        try:
            data = normalized_rom(path)
        except (OSError, RuntimeError) as exc:
            rejected.append(f"  {path.name}: {exc}")
        else:
            return path, data
    detail = "\n".join(rejected[:8])
    if len(rejected) > 8:
        detail += f"\n  ... and {len(rejected) - 8} other nonmatching images."
    raise RuntimeError(
        f"No matching OoT US NTSC 1.2 image in {directory}. "
        f"Expected normalized MD5 {LOCK['base_rom_md5']}.\n{detail}\n"
        "Pokemon Stadium is an asset source for future work, not the base ROM."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    environment_rom = os.environ.get("POKE_N64_ROM")
    parser.add_argument("--rom", type=Path,
                        default=Path(environment_rom) if environment_rom else None,
                        help="explicit base ROM; otherwise inspect roms/ by checksum")
    parser.add_argument("--roms-dir", type=Path, default=ROOT / "roms",
                        help="folder to scan when no explicit ROM is supplied")
    parser.add_argument("--check", action="store_true",
                        help="validate local input only; no downloads, builds or writes")
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    args = parser.parse_args()
    # Validate source before cloning, downloading build tools or modifying files.
    path, data = select_rom(args.rom, args.roms_dir)
    print(f"Validated OoT US NTSC 1.2: {path}\nNormalized MD5: {LOCK['base_rom_md5']}", flush=True)
    if args.check:
        print("Input is ready. Run make rom to build the native target.")
        return
    engine = args.engine.resolve()
    install(engine)
    base = engine / "baseroms/ntsc-1.2/baserom.z64"
    if base.exists() and base.read_bytes() != data:
        raise RuntimeError(f"Refusing to overwrite an existing different base ROM at {base}")
    base.write_bytes(data)
    make = shutil.which("gmake") or shutil.which("make")
    if not make:
        raise RuntimeError("GNU make is required (Homebrew gmake on macOS).")
    jobs = max(1, args.jobs)
    common = [make, f"-j{jobs}", f"N_THREADS={jobs}", "VERSION=ntsc-1.2", "REGION=US", "DEBUG_FEATURES=0"]
    subprocess.run([*common, "setup"], cwd=engine, check=True)
    subprocess.run(common, cwd=engine, check=True)
    subprocess.run([*common, "compress"], cwd=engine, check=True)
    generated = engine / "build/ntsc-1.2/hackeroot-ntsc-1.2-compressed-yaz.z64"
    if not generated.exists():
        raise RuntimeError(f"Build returned success without expected output: {generated}")
    target = ROOT / "build/poke-n64.z64"
    shutil.copyfile(generated, target)
    flips = engine / "tools/Flips/flips"
    patch = ROOT / "build/poke-n64.bps"
    if not flips.is_file():
        raise RuntimeError(f"ROM built at {target}, but BPS tool is missing: {flips}")
    subprocess.run([str(flips), "--create", "--bps", str(base), str(target), str(patch)], check=True)
    print(f"Native ROM: {target}\nDistributable patch: {patch}")
    print("Use an 8 MiB Expansion Pak and an F3DEX3-capable LLE emulator. Save type: SRAM 32 KiB.")
    print("This command builds; it does not verify gameplay in an emulator or on a console.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"ROM build failed: {exc}")
