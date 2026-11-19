"""Synthetic N64 header-check tests; no proprietary ROM is required."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import inspect_rom


class FakeChecksum:
    @staticmethod
    def detectCIC(data: bytes) -> str:
        return "CIC_6105"

    @staticmethod
    def calculateChecksum(data: bytes, cic: str) -> tuple[int, int]:
        assert cic == "CIC_6105"
        return (0x12345678, 0x9ABCDEF0)


class RomIntegrityTests(unittest.TestCase):
    def make_rom(self) -> bytes:
        data = bytearray(inspect_rom.MIN_ROM_BYTES)
        data[:4] = inspect_rom.N64_MAGIC
        data[8:12] = (0x80000400).to_bytes(4, "big")
        data[0x10:0x18] = bytes.fromhex("123456789ABCDEF0")
        data[0x40] = 0xAA
        data[0x20:0x2C] = b"POKE N64 MVP"
        data[0x3C:0x3E] = b"PK"
        return bytes(data)

    def test_accepts_consistent_header_and_crc(self) -> None:
        info = inspect_rom.inspect_bytes(self.make_rom(), FakeChecksum)
        self.assertEqual(info["title"], "POKE N64 MVP")
        self.assertEqual(info["game_id"], "PK")
        self.assertEqual(info["entrypoint"], 0x80000400)
        self.assertEqual(info["crc1"], 0x12345678)

    def test_rejects_checksum_mismatch(self) -> None:
        rom = bytearray(self.make_rom())
        rom[0x10] ^= 1
        with self.assertRaisesRegex(ValueError, "Incorrect boot CRC"):
            inspect_rom.inspect_bytes(bytes(rom), FakeChecksum)

    def test_rejects_bad_magic_truncation_boot_and_entrypoint(self) -> None:
        base = self.make_rom()
        bad = [
            (base[:0x400], "truncated"),
            (b"NOPE" + base[4:], "Not a big-endian"),
            (base[:8] + b"\\x00" * 4 + base[12:], "Unexpected N64 entrypoint"),
            (base[:0x40] + b"\\x00" * (0x1000 - 0x40) + base[0x1000:], "IPL3 boot region"),
        ]
        for rom, message in bad:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    inspect_rom.inspect_bytes(rom, FakeChecksum)


if __name__ == "__main__":
    unittest.main()
