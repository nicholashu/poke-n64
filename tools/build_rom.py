#!/usr/bin/env python3
"""Validate or build with a local OoT US NTSC 1.2 image, auto-detected in roms/."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
import os
import shutil
import subprocess
import sys
from bootstrap import DEFAULT_ENGINE, LOCK, ROOT, install
from build_env import native_make


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


# HackerOoT setup is an expensive ROM decomposition + asset extraction,
# not part of the incremental Make graph. Cache only fully completed setups.
SETUP_STAMP_NAME = ".poke-setup-cache.json"
SETUP_CACHE_FORMAT = 1


def setup_identity() -> dict[str, str | int]:
    return {
        "format": SETUP_CACHE_FORMAT,
        "engine": LOCK["commit"],
        "version": LOCK["version"],
        "region": LOCK["region"],
        "base_md5": LOCK["base_rom_md5"],
    }


def setup_prerequisites(engine: Path) -> tuple[Path, ...]:
    version = LOCK["version"]
    return (
        engine / ".venv/bin/python3",
        engine / f"baseroms/{version}/baserom-decompressed.z64",
        engine / f"extracted/{version}/baserom",
    )


def setup_is_cached(engine: Path) -> bool:
    stamp = engine / SETUP_STAMP_NAME
    try:
        previous = json.loads(stamp.read_text())
    except (OSError, ValueError):
        return False
    return (
        previous == setup_identity()
        and all(path.exists() for path in setup_prerequisites(engine))
    )


def ensure_extracted(engine: Path, common: list[str], *, refresh: bool = False) -> bool:
    """Run HackerOoT setup only if its successful extraction is not cached.

    Return True when setup ran. Failed extractions never get stamped and will
    be retried. To force a refresh after editing upstream asset XML use
    --refresh-setup, which explicitly reruns the full upstream setup process.
    """
    if not refresh and setup_is_cached(engine):
        print("Reusing extracted OoT assets and Python environment.", flush=True)
        return False
    print("Preparing OoT base assets (first run or requested refresh)...", flush=True)
    subprocess.run([*common, "setup"], cwd=engine, check=True)
    # Do not claim a cached setup if the upstream setup didn't produce files.
    missing = [path for path in setup_prerequisites(engine) if not path.exists()]
    if missing:
        raise RuntimeError("OoT setup did not create expected files: " +
                           ", ".join(str(path) for path in missing))
    stamp = engine / SETUP_STAMP_NAME
    temporary = stamp.with_suffix(".tmp")
    temporary.write_text(json.dumps(setup_identity(), sort_keys=True) + "\n")
    temporary.replace(stamp)
    return True


def compression_is_cached(engine: Path, compressed: Path) -> bool:
    raw = engine / f"build/{LOCK['version']}/hackeroot-{LOCK['version']}.z64"
    return (
        compressed.is_file()
        and raw.is_file()
        and compressed.stat().st_mtime_ns >= raw.stat().st_mtime_ns
    )


def linked_symbol_address(map_text: str, symbol: str) -> int:
    """Read a concrete symbol address from a GNU ld map, not a reference."""
    for line in map_text.splitlines():
        fields = line.split()
        if len(fields) < 2 or not fields[0].startswith("0x"):
            continue
        if fields[1] == symbol:
            try:
                return int(fields[0], 16)
            except ValueError:
                continue
    raise RuntimeError(f"Linker map is missing {symbol}; ROM cannot be verified")


def verify_pallet_segment_headers(map_file: Path) -> None:
    """Scene/room commands MUST start at offset zero of OoT ROM segments.

    GCC can reorder global C variables within a translation unit; an earlier
    build put collision data at scene offset 0 and the header at 0x1004.
    Object-only compile tests missed this fatal startup error. Check the final
    linked map on every OoT conversion build before ROM compression.
    """
    if not map_file.is_file():
        raise RuntimeError(f"Native ROM link map missing: {map_file}")
    data = map_file.read_text()
    for segment, header in (
        ("spot04_scene", "gPalletSceneHeader"),
        ("spot04_room_0", "gPalletRoomHeader"),
    ):
        start = linked_symbol_address(data, f"_{segment}SegmentStart")
        actual = linked_symbol_address(data, header)
        if actual != start:
            raise RuntimeError(
                f"OoT {segment} header is not at ROM segment offset 0: "
                f"{header} at 0x{actual:08X} but segment begins 0x{start:08X}. "
                "OoT would read geometry or collision data as scene commands."
            )
        print(f"Verified {segment} commands at segment offset 0.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    environment_rom = os.environ.get("POKE_N64_ROM")
    parser.add_argument("--rom", type=Path,
                        default=Path(environment_rom) if environment_rom else None,
                        help="explicit base ROM; otherwise inspect roms/ by checksum")
    parser.add_argument("--roms-dir", type=Path, default=ROOT / "roms",
                        help="folder to scan when no explicit ROM is supplied")
    parser.add_argument("--control-boot", action="store_true",
                        help="build the stock Zelda boot path for diagnosing the custom state")
    parser.add_argument("--oot-conversion", action="store_true",
                        help="build Pokémon's native OoT PlayState total-conversion experiment")
    parser.add_argument("--refresh-setup", action="store_true",
                        help="force the full upstream ROM extraction and dependency setup")
    parser.add_argument("--check", action="store_true",
                        help="validate local input only; no downloads, builds or writes")
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    args = parser.parse_args()
    if args.control_boot and args.oot_conversion:
        raise RuntimeError("Choose only one boot mode: --control-boot or --oot-conversion")
    # Validate source before cloning, downloading build tools or modifying files.
    path, data = select_rom(args.rom, args.roms_dir)
    print(f"Validated OoT US NTSC 1.2: {path}\nNormalized MD5: {LOCK['base_rom_md5']}", flush=True)
    if args.check:
        print("Input is ready. Run make rom-docker, or make rom with a native MIPS toolchain.")
        return
    # Report missing native tools before downloading the engine or copying a ROM.
    make = native_make()
    engine = args.engine.resolve()
    mode = "control" if args.control_boot else ("oot" if args.oot_conversion else "poke")
    install(engine, boot_mode=mode)
    base = engine / "baseroms/ntsc-1.2/baserom.z64"
    if base.exists():
        if base.read_bytes() != data:
            raise RuntimeError(f"Refusing to overwrite an existing different base ROM at {base}")
    else:
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_bytes(data)
    jobs = max(1, args.jobs)
    common = [make, f"-j{jobs}", f"N_THREADS={jobs}", "VERSION=ntsc-1.2", "REGION=US", "DEBUG_FEATURES=0"]
    ensure_extracted(engine, common, refresh=args.refresh_setup)
    subprocess.run(common, cwd=engine, check=True)
    if args.oot_conversion:
        verify_pallet_segment_headers(
            engine / "build/ntsc-1.2/hackeroot-ntsc-1.2.map"
        )
    generated = engine / "build/ntsc-1.2/hackeroot-ntsc-1.2-compressed-yaz.z64"
    if compression_is_cached(engine, generated):
        print("Reusing up-to-date compressed ROM.", flush=True)
    else:
        # Upstream's compress recipe touches code/spec deliberately. Only run
        # that forced relink when the raw ROM changed or no compressed ROM exists.
        subprocess.run([*common, "compress"], cwd=engine, check=True)
    if not generated.exists():
        raise RuntimeError(f"Build returned success without expected output: {generated}")
    label = ("poke-n64-control" if args.control_boot else
             "poke-n64-oot" if args.oot_conversion else "poke-n64")
    target = ROOT / f"build/{label}.z64"
    shutil.copyfile(generated, target)
    # The ROM must be independently boot-checksummed before creating the patch.
    # Upstream already ships the ipl3checksum dependency in its virtualenv.
    inspector = ROOT / "tools/inspect_rom.py"
    python = engine / ".venv/bin/python3"
    if not python.is_file():
        raise RuntimeError(f"Engine Python environment missing: {python}")
    subprocess.run([str(python), str(inspector), str(target)], check=True)
    flips = engine / "tools/Flips/flips"
    patch = ROOT / f"build/{label}.bps"
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
