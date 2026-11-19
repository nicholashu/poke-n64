#!/usr/bin/env python3
"""Inspect a built big-endian N64 ROM and verify its IPL3-dependent boot CRCs.

Run with HackerOoT's own Python virtualenv (it includes ipl3checksum).
This does NOT require or alter the original input ROM.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

MIN_ROM_BYTES = 0x101000
N64_MAGIC = b"\x80\x37\x12\x40"


def inspect_bytes(data: bytes, checksum_module: object) -> dict[str, object]:
    if len(data) < MIN_ROM_BYTES:
        raise ValueError(f"ROM truncated: {len(data)} bytes; need at least {MIN_ROM_BYTES}")
    if data[:4] != N64_MAGIC:
        raise ValueError("Not a big-endian N64 .z64 image (expected 80371240 magic)")
    entry = int.from_bytes(data[8:12], "big")
    if not (0x80000000 <= entry <= 0x807FFFFF):
        raise ValueError(f"Unexpected N64 entrypoint 0x{entry:08X}")
    if not any(data[0x40:0x1000]):
        raise ValueError("N64 IPL3 boot region is all zero")
    cic = checksum_module.detectCIC(data)
    if cic is None:
        raise ValueError("IPL3 boot code is not recognized by ipl3checksum")
    calculated = checksum_module.calculateChecksum(data, cic)
    if calculated is None:
        raise ValueError("IPL3 checksum calculation rejected this ROM")
    stored = (int.from_bytes(data[0x10:0x14], "big"),
              int.from_bytes(data[0x14:0x18], "big"))
    expected = (int(calculated[0]), int(calculated[1]))
    if stored != expected:
        raise ValueError(
            f"Incorrect boot CRC: header=({stored[0]:08X}, {stored[1]:08X}), "
            f"calculated=({expected[0]:08X}, {expected[1]:08X}), CIC={cic}"
        )
    title = data[0x20:0x34].decode("ascii", errors="replace").rstrip("\x00 ")
    game_id = data[0x3C:0x3E].decode("ascii", errors="replace")
    return {"bytes": len(data), "title": title, "game_id": game_id,
            "entrypoint": entry, "cic": str(cic), "crc1": stored[0],
            "crc2": stored[1]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path, help="locally generated .z64 ROM")
    args = parser.parse_args()
    try:
        import ipl3checksum
        info = inspect_bytes(args.rom.read_bytes(), ipl3checksum)
    except (OSError, ValueError, ImportError) as exc:
        sys.exit(f"ROM integrity check failed: {exc}")
    print(f"ROM verified: {args.rom}")
    print(f"  Title: {info['title']}   ID: {info['game_id']}")
    print(f"  Size: {info['bytes']} bytes   Entry: 0x{info['entrypoint']:08X}")
    print(f"  IPL3: {info['cic']}   CRC: {info['crc1']:08X} {info['crc2']:08X}")


if __name__ == "__main__":
    main()
