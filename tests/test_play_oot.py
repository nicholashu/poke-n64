"""Offline tests for the clean Pokémon N64 emulator launcher.

No user ROM, running emulator, installed core or external dependencies needed.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import play_oot


class CleanLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # macOS /var is a symlink to /private/var; match launcher Path.resolve().
        base = Path(self.tmp.name).resolve()
        self.app = base / "My RetroArch Launcher.app"
        executable = self.app / "Contents/MacOS/RetroArch"
        executable.parent.mkdir(parents=True)
        executable.write_text("fixture")
        self.executable = executable
        self.config = base / "base config.cfg"
        self.config.write_text('video_driver = "vulkan"\n')
        self.core = base / "parallel n64 next.dylib"
        self.core.write_bytes(b"synthetic")
        self.rom = base / "poke n64 oot.z64"
        self.rom.write_bytes(b"synthetic")
        self.sessions = base / "fresh sessions"
        self.saved = base / "old user saves"
        self.saved.mkdir()
        self.legacy_srm = self.saved / "poke-n64-oot.srm"
        self.legacy_srm.write_bytes(b"KEEP ME")
        self.argv = [
            "play_oot.py", "--rom", str(self.rom), "--app", str(self.app),
            "--config", str(self.config), "--core", str(self.core),
            "--sessions-root", str(self.sessions),
        ]

    def _run(self, additional=None, fake_ps="") -> tuple[str, list[list[str]]]:
        invoked = []

        def mocked_run(command, **kwargs):
            invoked.append(command)
            if command[0] == "ps":
                return subprocess.CompletedProcess(command, 0, stdout=fake_ps)
            if command[0] == "open":
                self.assertTrue(kwargs["check"])
                return subprocess.CompletedProcess(command, 0)
            raise AssertionError(f"Unexpected subprocess {command!r}")

        with patch.object(sys, "argv", self.argv + (additional or [])), \
                patch.object(play_oot.subprocess, "run", side_effect=mocked_run), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            play_oot.main()
        return output.getvalue(), invoked

    def test_config_isolation_preserves_video_driver_and_existing_saves(self):
        text = play_oot.session_overlay(
            Path("/temporary/new save folder"), Path("/temporary/new state folder")
        )
        self.assertIn('savefile_directory = "/temporary/new save folder"', text)
        self.assertIn('savestate_directory = "/temporary/new state folder"', text)
        self.assertIn('savestate_auto_load = "false"', text)
        self.assertIn('savestate_auto_save = "false"', text)
        self.assertIn('video_shader_enable = "false"', text)
        self.assertIn('video_filter = ""', text)
        self.assertIn('config_save_on_exit = "false"', text)
        self.assertNotIn("video_driver", text)
        self.assertNotIn("parallel-n64-", text)

    def test_paths_are_config_quoted_and_control_chars_are_rejected(self):
        self.assertEqual(play_oot.quote_config('a "quoted" path'),
                         '"a \\"quoted\\" path"')
        self.assertEqual(play_oot.quote_config("spaces and/slashes"),
                         '"spaces and/slashes"')
        with self.assertRaises(ValueError):
            play_oot.quote_config("path\nwrong")

    def test_process_detection_only_matches_this_rom_and_binary(self):
        table = (
            f"  100 {self.executable} -c cfg -L core {self.rom}\n"
            f"  101 {self.executable} -c cfg -L core /other/rom.z64\n"
            f"  102 /bin/zsh -c 'echo {self.executable} {self.rom}'\n"
            "  103 /Applications/RetroArch.app/Contents/MacOS/RetroArch other.z64\n"
        )
        self.assertEqual(
            play_oot.running_emulators(self.executable, self.rom, table), [100]
        )

    def test_dry_run_does_not_create_directories_or_launch(self):
        out, invoked = self._run(["--dry-run"])
        self.assertEqual(invoked, [])
        self.assertIn("--no-patch", out)
        self.assertIn("--appendconfig=", out)
        self.assertIn("unique session directory", out)
        self.assertFalse(self.sessions.exists())
        self.assertEqual(self.legacy_srm.read_bytes(), b"KEEP ME")

    def test_launch_creates_fresh_isolated_saves_and_states(self):
        out, invoked = self._run()
        self.assertEqual([x[0] for x in invoked], ["ps", "open"])
        sessions = list(self.sessions.iterdir())
        self.assertEqual(len(sessions), 1)
        self.assertTrue((sessions[0] / "saves").is_dir())
        self.assertTrue((sessions[0] / "states").is_dir())
        self.assertEqual(list((sessions[0] / "saves").iterdir()), [])
        self.assertEqual(list((sessions[0] / "states").iterdir()), [])
        overlay = (sessions[0] / "clean-launch.cfg").read_text()
        self.assertIn(str(sessions[0] / "saves"), overlay)
        self.assertIn(str(sessions[0] / "states"), overlay)
        command = invoked[1]
        self.assertEqual(command[:5], ["open", "-n", "-a", str(self.app), "--args"])
        self.assertEqual(command[-2:], ["--no-patch", str(self.rom)])
        self.assertIn("--appendconfig=" + str(sessions[0] / "clean-launch.cfg"), command)
        self.assertIn(str(sessions[0]), out)
        self.assertEqual(self.legacy_srm.read_bytes(), b"KEEP ME")
        self.assertEqual(self.config.read_text(), 'video_driver = "vulkan"\n')

    def test_second_launch_never_uses_first_launch_data(self):
        self._run()
        first = next(self.sessions.iterdir())
        old_save = first / "saves" / self.rom.with_suffix(".srm").name
        old_save.write_bytes(b"FIRST SESSION")
        self._run()
        dirs = list(self.sessions.iterdir())
        self.assertEqual(len(dirs), 2)
        second = next(x for x in dirs if x != first)
        self.assertEqual(list((second / "saves").iterdir()), [])
        self.assertEqual(list((second / "states").iterdir()), [])
        self.assertNotIn(str(first), (second / "clean-launch.cfg").read_text())
        self.assertEqual(old_save.read_bytes(), b"FIRST SESSION")
        self.assertEqual(self.legacy_srm.read_bytes(), b"KEEP ME")

    def test_running_game_refuses_duplicate_launch_without_touching_saves(self):
        table = f"  999 {self.executable} -c cfg -L core {self.rom}\n"
        with patch.object(sys, "argv", self.argv), \
                patch.object(play_oot.subprocess, "run",
                             return_value=subprocess.CompletedProcess(["ps"], 0,
                                                                        stdout=table)), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                play_oot.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(self.sessions.exists())
        self.assertEqual(self.legacy_srm.read_bytes(), b"KEEP ME")


if __name__ == "__main__":
    unittest.main()
