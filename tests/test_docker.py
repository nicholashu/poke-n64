"""Docker launch contracts without requiring Docker or proprietary ROM data."""
from __future__ import annotations

import contextlib
import csv
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import docker_rom


def mounts(command: list[str]) -> dict[str, dict[str, str]]:
    result = {}
    for index, argument in enumerate(command):
        if argument != "--mount":
            continue
        fields = next(csv.reader(io.StringIO(command[index + 1])))
        mount = dict(field.split("=", 1) if "=" in field else (field, "") for field in fields)
        result[mount["target"]] = mount
    return result


class DockerAvailabilityTests(unittest.TestCase):
    def test_missing_cli_does_not_run_commands(self) -> None:
        with patch.object(docker_rom.shutil, "which", return_value=None), \
             patch.object(docker_rom.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Install and open Docker Desktop"):
                docker_rom.docker_cli()
        run.assert_not_called()

    def test_unavailable_or_unresponsive_daemon_has_actionable_error(self) -> None:
        responses = [subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired("docker", 30)]
        for response in responses:
            with self.subTest(response=type(response).__name__), \
                 patch.object(docker_rom.shutil, "which", return_value="/usr/bin/docker"), \
                 patch.object(docker_rom.subprocess, "run") as run:
                if isinstance(response, Exception):
                    run.side_effect = response
                else:
                    run.return_value = response
                with self.assertRaisesRegex(RuntimeError, "Open Docker Desktop"):
                    docker_rom.docker_cli()
                self.assertLessEqual(run.call_args.kwargs["timeout"], 30)

    def test_ready_daemon_uses_literal_executable_path(self) -> None:
        executable = "/Docker App/$literal/docker"
        with patch.object(docker_rom.shutil, "which", return_value=executable), \
             patch.object(docker_rom.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(executable, docker_rom.docker_cli())
        self.assertEqual([executable, "info", "--format", "{{.ServerVersion}}"], run.call_args.args[0])
        self.assertFalse(run.call_args.kwargs.get("shell", False))


class DockerBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # These characters are meaningful to shells and to Docker's mount CSV.
        self.root = Path(self.temp.name) / 'project, spaces ($literal) "quoted"'
        self.root.mkdir()
        self.roms = self.root / "roms"
        self.roms.mkdir()
        self.base = Path(self.temp.name) / "outside roms, (Rev 2) $literal.z64"
        self.base.write_bytes(b"test fixture only")
        self.addCleanup(patch.stopall)
        patch.object(docker_rom, "ROOT", self.root).start()
        patch.object(docker_rom, "docker_cli", return_value="/usr/bin/docker").start()
        self.run = patch.object(docker_rom.subprocess, "run").start()

    def test_build_uses_isolated_engine_literal_mounts_and_small_context(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            docker_rom.run_in_docker(self.base, 3)
        self.assertEqual(2, self.run.call_count)
        build, launch = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual("build", build[1])
        self.assertEqual(str(self.root / "tools/docker-context"), build[-1])
        self.assertEqual(str(self.root / "Dockerfile"), build[build.index("--file") + 1])
        for command in (build, launch):
            self.assertEqual("linux/amd64", command[command.index("--platform") + 1])
        bindings = mounts(launch)
        self.assertEqual(str(self.root.resolve()), bindings["/project"]["source"])
        self.assertNotIn("readonly", bindings["/project"])
        self.assertEqual(str(self.roms.resolve()), bindings["/project/roms"]["source"])
        self.assertIn("readonly", bindings["/project/roms"])
        self.assertEqual(str(self.base.resolve()), bindings["/inputs/base.z64"]["source"])
        self.assertIn("readonly", bindings["/inputs/base.z64"])
        self.assertEqual("/inputs/base.z64", launch[launch.index("--rom") + 1])
        self.assertEqual("/project/build/docker-engine", launch[launch.index("--engine") + 1])
        self.assertEqual("3", launch[launch.index("--jobs") + 1])
        self.assertNotIn(str(self.base), launch)
        # Host toolchain/venv/make configuration must not leak into the container.
        self.assertNotIn("--env", launch)
        self.assertNotIn("--env-file", launch)
        for call in self.run.call_args_list:
            self.assertFalse(call.kwargs.get("shell", False))
            self.assertTrue(call.kwargs["check"])

    def test_native_check_needs_no_rom_and_uses_container_preflight(self) -> None:
        self.roms.rmdir()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            docker_rom.run_in_docker(None, 1, check_tools=True)
        build, preflight, compile_check, make_check = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual([docker_rom.IMAGE, "python3", "tools/build_env.py"], preflight[-3:])
        self.assertIn("--require-mips", compile_check)
        self.assertEqual("/project/build/docker-engine", compile_check[-1])
        self.assertEqual({"/project"}, set(mounts(compile_check)))
        self.assertIn("--dry-run", make_check)
        self.assertEqual("/project/build/docker-engine", make_check[make_check.index("--directory") + 1])
        self.assertEqual("venv", make_check[-1])
        self.assertIn("No ROM was linked or run", output.getvalue())

    def test_build_failure_stops_before_container_launch(self) -> None:
        self.run.side_effect = subprocess.CalledProcessError(1, ["docker", "build"])
        with self.assertRaises(subprocess.CalledProcessError):
            docker_rom.run_in_docker(self.base, 1)
        self.assertEqual(1, self.run.call_count)

    def test_container_failure_does_not_report_outputs(self) -> None:
        self.run.side_effect = [subprocess.CompletedProcess([], 0),
                               subprocess.CalledProcessError(2, ["docker", "run"])]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(subprocess.CalledProcessError):
                docker_rom.run_in_docker(self.base, 1)
        self.assertNotIn("Outputs:", output.getvalue())

    def test_missing_base_stops_before_docker(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "validated base ROM"):
            docker_rom.run_in_docker(None, 1)
        self.run.assert_not_called()
        docker_rom.docker_cli.assert_not_called()

    def test_invalid_input_stops_before_docker(self) -> None:
        with patch.object(docker_rom, "select_rom", side_effect=RuntimeError("Wrong base ROM")), \
             patch.object(docker_rom, "run_in_docker") as launch, \
             patch.object(sys, "argv", ["docker_rom.py"]):
            with self.assertRaisesRegex(RuntimeError, "Wrong base ROM"):
                docker_rom.main()
        launch.assert_not_called()
        self.run.assert_not_called()

    def test_make_environment_path_is_used_verbatim(self) -> None:
        with patch.dict(os.environ, {"POKE_N64_ROM": str(self.base)}), \
             patch.object(docker_rom, "select_rom", return_value=(self.base, b"fixture")) as select, \
             patch.object(docker_rom, "run_in_docker") as launch, \
             patch.object(sys, "argv", ["docker_rom.py", "--jobs", "2"]), \
             contextlib.redirect_stdout(io.StringIO()):
            docker_rom.main()
        select.assert_called_once_with(self.base, self.roms)
        launch.assert_called_once_with(self.base, 2)


if __name__ == "__main__":
    unittest.main()
