"""Offline tests for the real RetroArch automation harness.

No ROM, emulator, GUI, proprietary assets or installed N64 core required.
"""
from __future__ import annotations

import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import retroarch_e2e as e2e


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads(
            (ROOT / "tests/rom_scenarios/pallet_smoke.json").read_text()
        )

    def test_pallet_smoke_scenario_is_valid(self):
        scenario = e2e.validate_scenario(self.example)
        self.assertEqual(len(scenario["steps"]), 14)
        self.assertEqual(scenario["steps"][-1]["action"], "assert_status")

    def test_rejects_unknown_steps(self):
        bad = {"name": "unsafe", "steps": [{"action": "shell", "command": "rm -rf ~"}]}
        with self.assertRaisesRegex(ValueError, "unrecognized action"):
            e2e.validate_scenario(bad)

    def test_assertions_require_existing_captures(self):
        scenario = {"name": "invalid", "steps": [
            {"action": "assert_changed", "before": "a", "after": "b"},
        ]}
        with self.assertRaisesRegex(ValueError, "both screenshots must exist"):
            e2e.validate_scenario(scenario)

    def test_movement_checks_require_prior_three_screenshots(self):
        with self.assertRaisesRegex(ValueError, "three screenshots"):
            e2e.validate_scenario({"name": "bad", "steps": [
                {"action": "screenshot", "name": "before"},
                {"action": "assert_movement", "idle_before": "missing",
                 "before": "before", "after": "missing"},
            ]})

    def test_rejects_traversal_in_screenshot_name(self):
        with self.assertRaisesRegex(ValueError, "unique and safe"):
            e2e.validate_scenario({"name": "bad", "steps": [
                {"action": "screenshot", "name": "../notes"},
            ]})

    def test_button_mapping_and_time_limits(self):
        self.assertEqual(e2e.button_id("n64_a"), 0)
        self.assertEqual(e2e.button_id("n64_b"), 1)
        self.assertEqual(e2e.button_id("n64_z"), 12)
        self.assertEqual(e2e.button_id("r"), 11)
        self.assertEqual(e2e.button_id("start"), 3)
        with self.assertRaisesRegex(ValueError, "Unknown RetroPad"):
            e2e.button_id("invalid")
        for bad in (-1, 91, "forever", True):
            with self.assertRaises(ValueError):
                e2e.validate_scenario({"name": "bad", "steps": [
                    {"action": "wait", "seconds": bad},
                ]})

    def test_key_hold_requires_valid_keycode_and_bounded_duration(self):
        good = {"name": "key", "steps": [
            {"action": "key_hold", "keycode": 13, "seconds": 2.5},
        ]}
        self.assertEqual(e2e.validate_scenario(good)["steps"][0]["keycode"], 13)
        for code in (-1, 128, "13", None, True):
            with self.assertRaisesRegex(ValueError, "macOS virtual keycode"):
                e2e.validate_scenario({"name": "bad", "steps": [
                    {"action": "key_hold", "keycode": code, "seconds": 1},
                ]})
        for seconds in (-1, 0, 91, True, "1"):
            with self.assertRaisesRegex(ValueError, "key_hold seconds"):
                e2e.validate_scenario({"name": "bad", "steps": [
                    {"action": "key_hold", "keycode": 13, "seconds": seconds},
                ]})

    def test_stick_coordinates_and_frame_limits(self):
        for bad in (32768, -32769, 1.2, None):
            with self.assertRaises(ValueError):
                e2e.validate_scenario({"name": "bad", "steps": [
                    {"action": "stick", "stick": "left", "x": bad, "y": 0, "seconds": 1},
                ]})
        for bad in (0, 601, "2"):
            with self.assertRaises(ValueError):
                e2e.validate_scenario({"name": "bad", "steps": [
                    {"action": "frames", "count": bad},
                ]})


class NetworkTests(unittest.TestCase):
    def test_retropad_struct_matches_native_layout(self):
        msg = e2e.encode_pad(0, 1, 0, 8, 1)
        self.assertEqual(len(msg), 20)
        self.assertEqual(struct.unpack("<iiiihxx", msg), (0, 1, 0, 8, 1))
        analog = e2e.encode_pad(0, 2, 0, 1, -25000)
        self.assertEqual(struct.unpack("<iiiihxx", analog)[-1], -25000)
        self.assertEqual(e2e.release_all_packet(), b"\x00")
        with self.assertRaises(ValueError):
            e2e.encode_pad(0, 2, 0, 1, -32769)

    def test_local_nci_status_query(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        def respond():
            server.settimeout(2)
            data, addr = server.recvfrom(256)
            if data == b"GET_STATUS":
                server.sendto(b"GET_STATUS PLAYING n64,poke-n64-oot,crc32=12345678", addr)
        worker = threading.Thread(target=respond)
        worker.start()
        client = e2e.Remote(port, port + 1)
        try:
            reply = client.command("GET_STATUS", reply=True)
            self.assertIn("GET_STATUS PLAYING", reply)
        finally:
            client.close()
            worker.join(timeout=3)
            server.close()

    def test_analog_and_button_datagrams_are_local_and_well_formed(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        client = e2e.Remote(port + 1, port)
        try:
            client.pad(["n64_a"], True)
            client.stick("left", 2000, -28000)
            client.release_all()
            packets = []
            server.settimeout(2)
            for _ in range(4):
                packets.append(server.recvfrom(256)[0])
            self.assertEqual(struct.unpack("<iiiihxx", packets[0]),
                             (0, 1, 0, 0, 1))
            self.assertEqual(struct.unpack("<iiiihxx", packets[1]),
                             (0, 2, 0, 0, 2000))
            self.assertEqual(struct.unpack("<iiiihxx", packets[2]),
                             (0, 2, 0, 1, -28000))
            self.assertEqual(packets[3], b"\x00")
        finally:
            client.close()
            server.close()

    def test_overlay_isolates_saves_and_network_ports(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            config = e2e.network_overlay(
                root / "new saves", root / "new states",
                root / "screens", 58001, 58002,
            )
            self.assertIn('network_cmd_port = "58001"', config)
            self.assertIn('network_remote_base_port = "58002"', config)
            self.assertIn('network_remote_enable_user_p1 = "true"', config)
            self.assertIn('pause_nonactive = "false"', config)
            self.assertIn('notification_show_screenshot = "false"', config)
            self.assertIn('screenshot_directory = "', config)
            self.assertIn('savestate_auto_load = "false"', config)
            self.assertIn('savefile_directory = "', config)
            self.assertNotIn("video_driver", config)
            self.assertNotIn("parallel-n64-rspplugin", config)


class VisualTests(unittest.TestCase):
    def test_movement_assertion_uses_idle_drift_as_baseline(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is optional at runtime")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b, c = (root / f"{label}.png" for label in ("idle1", "idle2", "walk"))
            Image.new("RGB", (50, 50), (40, 40, 40)).save(a)
            Image.new("RGB", (50, 50), (43, 43, 43)).save(b)
            Image.new("RGB", (50, 50), (120, 60, 20)).save(c)
            runner = e2e.Runner({"name": "fake", "steps": [
                {"action": "screenshot", "name": "placeholder"},
            ]}, root / "rom.z64", root)
            runner.images = {"idle1": a, "idle2": b, "walk": c}
            # Use only this assertion, without invoking real RetroArch.
            runner.remote = object()
            response = runner.step({
                "action": "assert_movement", "idle_before": "idle1",
                "before": "idle2", "after": "walk", "ratio": 2,
                "min_difference": 8,
            })
            self.assertIn("movement confirmed", response)
            with self.assertRaisesRegex(AssertionError, "No clear movement"):
                runner.step({
                    "action": "assert_movement", "idle_before": "idle1",
                    "before": "idle2", "after": "walk", "ratio": 2,
                    "min_difference": 240,
                })

    def test_synthetic_image_difference_and_blank_detection(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is an optional runtime dependency")
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "black.png"
            b = Path(tmp) / "green.png"
            Image.new("RGB", (200, 150), (0, 0, 0)).save(a)
            Image.new("RGB", (200, 150), (100, 190, 50)).save(b)
            self.assertEqual(e2e.image_stats(a)["color_spread"], 0)
            self.assertGreater(e2e.image_difference(a, b), 50)


if __name__ == "__main__":
    unittest.main()
