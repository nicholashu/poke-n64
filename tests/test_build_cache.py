"""Fast, ROM-free regression tests for incremental OoT builds."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_rom


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.engine = Path(self.work.name) / "engine"
        self.engine.mkdir()
        self.command = ["make", "VERSION=ntsc-1.2", "REGION=US", "DEBUG_FEATURES=0"]

    def make_setup_output(self):
        for path in build_rom.setup_prerequisites(self.engine):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".z64" or path.name == "python3":
                path.write_bytes(b"synthetic fixture only")
            else:
                path.mkdir(exist_ok=True)

    def test_linked_scene_and_room_header_must_be_at_segment_zero(self):
        # Minimal GNU ld map-shaped fixture. No proprietary Zelda data.
        record = "\n".join([
            "                0x02000000  _spot04_sceneSegmentStart = .",
            "                0x02000000  gPalletSceneHeader",
            "                0x02000100  gPalletCollision",
            "                0x03000000  _spot04_room_0SegmentStart = .",
            "                0x03000000  gPalletRoomHeader",
            "                0x03000100  gPalletWorldDl",
            "",
        ])
        file = self.engine / "synthetic.map"
        file.write_text(record)
        self.assertEqual(
            build_rom.linked_symbol_address(record, "gPalletSceneHeader"),
            0x02000000,
        )
        build_rom.verify_pallet_segment_headers(file)
        broken_scene = record.replace(
            "0x02000000  gPalletSceneHeader",
            "0x02001004  gPalletSceneHeader",
        )
        file.write_text(broken_scene)
        with self.assertRaisesRegex(RuntimeError, "spot04_scene header.*offset 0"):
            build_rom.verify_pallet_segment_headers(file)
        broken_room = record.replace(
            "0x03000000  gPalletRoomHeader",
            "0x03001004  gPalletRoomHeader",
        )
        file.write_text(broken_room)
        with self.assertRaisesRegex(RuntimeError, "spot04_room_0 header.*offset 0"):
            build_rom.verify_pallet_segment_headers(file)

    def test_missing_link_map_or_symbol_is_not_silently_accepted(self):
        file = self.engine / "missing.map"
        with self.assertRaisesRegex(RuntimeError, "link map missing"):
            build_rom.verify_pallet_segment_headers(file)
        file.write_text(
            "0x02000000 _spot04_sceneSegmentStart = .\n"
            "0x02000000 gPalletSceneHeader\n"
        )
        with self.assertRaisesRegex(RuntimeError, "missing _spot04_room_0SegmentStart"):
            build_rom.verify_pallet_segment_headers(file)

    def test_first_setup_runs_only_once_then_reuses_cached_extraction(self):
        calls = []

        def fake_setup(args, cwd, check):
            self.assertEqual(args[-1], "setup")
            self.assertEqual(cwd, self.engine)
            self.assertTrue(check)
            calls.append(args)
            self.make_setup_output()

        with patch.object(build_rom.subprocess, "run", side_effect=fake_setup):
            self.assertTrue(build_rom.ensure_extracted(self.engine, self.command))
            self.assertTrue(build_rom.setup_is_cached(self.engine))
            self.assertFalse(build_rom.ensure_extracted(self.engine, self.command))
        self.assertEqual(len(calls), 1)
        stamp = json.loads((self.engine / build_rom.SETUP_STAMP_NAME).read_text())
        self.assertEqual(stamp["base_md5"], build_rom.LOCK["base_rom_md5"])
        self.assertEqual(stamp["engine"], build_rom.LOCK["commit"])

    def test_deleted_extraction_invalidates_cache(self):
        self.make_setup_output()
        stamp = self.engine / build_rom.SETUP_STAMP_NAME
        stamp.write_text(json.dumps(build_rom.setup_identity()))
        self.assertTrue(build_rom.setup_is_cached(self.engine))
        deleted = self.engine / f"baseroms/{build_rom.LOCK['version']}/baserom-decompressed.z64"
        deleted.unlink()
        self.assertFalse(build_rom.setup_is_cached(self.engine))

    def test_refresh_forces_setup(self):
        self.make_setup_output()
        (self.engine / build_rom.SETUP_STAMP_NAME).write_text(
            json.dumps(build_rom.setup_identity())
        )
        with patch.object(build_rom.subprocess, "run") as runner:
            self.assertTrue(build_rom.ensure_extracted(self.engine, self.command, refresh=True))
        runner.assert_called_once()

    def test_failed_setup_never_creates_cache_stamp(self):
        with patch.object(build_rom.subprocess, "run",
                          side_effect=subprocess.CalledProcessError(1, self.command)):
            with self.assertRaises(subprocess.CalledProcessError):
                build_rom.ensure_extracted(self.engine, self.command)
        self.assertFalse((self.engine / build_rom.SETUP_STAMP_NAME).exists())

    def test_invalid_identity_invalidates_cache(self):
        self.make_setup_output()
        stamp = self.engine / build_rom.SETUP_STAMP_NAME
        identity = build_rom.setup_identity()
        identity["base_md5"] = "another game"
        stamp.write_text(json.dumps(identity))
        self.assertFalse(build_rom.setup_is_cached(self.engine))
        stamp.write_text("{invalid json")
        self.assertFalse(build_rom.setup_is_cached(self.engine))

    def test_compressed_rom_is_reused_only_when_newer_than_raw(self):
        version = build_rom.LOCK["version"]
        raw = self.engine / f"build/{version}/hackeroot-{version}.z64"
        zipped = self.engine / f"build/{version}/hackeroot-{version}-compressed-yaz.z64"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"raw")
        self.assertFalse(build_rom.compression_is_cached(self.engine, zipped))
        zipped.write_bytes(b"compressed")
        os.utime(raw, ns=(1_600_000_000_000_000_000,) * 2)
        os.utime(zipped, ns=(1_600_000_000_000_000_100,) * 2)
        self.assertTrue(build_rom.compression_is_cached(self.engine, zipped))
        os.utime(raw, ns=(1_600_000_000_000_000_200,) * 2)
        self.assertFalse(build_rom.compression_is_cached(self.engine, zipped))


if __name__ == "__main__":
    unittest.main()
