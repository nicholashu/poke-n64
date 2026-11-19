"""Docker launch contracts without requiring Docker or proprietary ROM data."""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
from pathlib import Path
import platform as client_platform
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
                docker_rom.docker_environment()
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
                    docker_rom.docker_environment()
                self.assertLessEqual(run.call_args.kwargs["timeout"], 30)

    def test_ready_daemon_uses_literal_executable_path(self) -> None:
        executable = "/Docker App/$literal/docker"
        with patch.object(docker_rom.shutil, "which", return_value=executable), \
             patch.object(docker_rom.subprocess, "run", return_value=subprocess.CompletedProcess(
                 [], 0, stdout='{"os":"linux","arch":"aarch64"}')) as run:
            self.assertEqual((executable, "linux/arm64"), docker_rom.docker_environment())
        template = '{"os":{{json .OSType}},"arch":{{json .Architecture}}}'
        self.assertEqual([executable, "info", "--format", template], run.call_args.args[0])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_linux_architecture_aliases_use_daemon_not_client(self) -> None:
        aliases = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
        for reported, normalized in aliases.items():
            # Deliberately report a client architecture opposite to the daemon.
            client = "arm64" if normalized == "amd64" else "x86_64"
            with self.subTest(reported=reported), \
                 patch.object(client_platform, "machine", return_value=client), \
                 patch.object(docker_rom.shutil, "which", return_value="/usr/bin/docker"), \
                 patch.object(docker_rom.subprocess, "run", return_value=subprocess.CompletedProcess(
                     [], 0, stdout=json.dumps({"os": "linux", "arch": reported}))):
                self.assertEqual(("/usr/bin/docker", f"linux/{normalized}"), docker_rom.docker_environment())

    def test_malformed_or_unsupported_daemon_data_cannot_fall_back_to_building(self) -> None:
        invalid = [
            "", "not JSON", "null", "[]", "42", "true", "{}",
            '{"os":"linux"}', '{"arch":"arm64"}',
            '{"os":null,"arch":"arm64"}', '{"os":false,"arch":"arm64"}',
            '{"os":["linux"],"arch":"arm64"}',
            '{"os":"linux","arch":null}', '{"os":"linux","arch":64}',
            '{"os":"linux","arch":true}', '{"os":"linux","arch":["arm64"]}',
            '{"os":"windows","arch":"amd64"}', '{"os":"darwin","arch":"arm64"}',
            '{"os":"","arch":"amd64"}', '{"os":"linux","arch":""}',
            '{"os":"linux","arch":"mips"}', '{"os":"linux","arch":"ppc64le"}',
            '{"os":"linux","arch":"arm/v7"}',
            '{"os":"linux","arch":"../../host"}',
        ]
        for output in invalid:
            with self.subTest(output=output), \
                 patch.object(docker_rom.shutil, "which", return_value="/usr/bin/docker"), \
                 patch.object(docker_rom.subprocess, "run", return_value=subprocess.CompletedProcess(
                     [], 0, stdout=output)) as run:
                with self.assertRaises(RuntimeError):
                    docker_rom.run_in_docker(None, 1, check_tools=True)
                run.assert_called_once()
                self.assertEqual("info", run.call_args.args[0][1])


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
        self.environment = patch.object(docker_rom, "docker_environment",
                                        return_value=("/usr/bin/docker", "linux/amd64")).start()
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
        self.assertEqual("/project/build/docker-engine-amd64", launch[launch.index("--engine") + 1])
        self.assertEqual("poke-n64-build-amd64", build[build.index("--tag") + 1])
        self.assertIn("poke-n64-build-amd64", launch)
        self.assertEqual("3", launch[launch.index("--jobs") + 1])
        self.assertNotIn(str(self.base), launch)
        # Host toolchain/venv/make configuration must not leak into the container.
        self.assertNotIn("--env", launch)
        self.assertNotIn("--env-file", launch)
        for call in self.run.call_args_list:
            self.assertFalse(call.kwargs.get("shell", False))
            self.assertTrue(call.kwargs["check"])

    def test_control_boot_runs_separately_with_verified_input(self) -> None:
        self.environment.return_value = ("/usr/bin/docker", "linux/arm64")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            docker_rom.run_in_docker(self.base, 2, control_boot=True)
        build, launch = [call.args[0] for call in self.run.call_args_list]
        self.assertIn("--control-boot", launch)
        self.assertEqual("/project/build/docker-engine-arm64-control", launch[launch.index("--engine") + 1])
        self.assertEqual("poke-n64-build-arm64", build[build.index("--tag") + 1])
        self.assertIn("poke-n64-control.z64", output.getvalue())

    def test_native_check_needs_no_rom_and_uses_container_preflight(self) -> None:
        self.roms.rmdir()
        self.environment.return_value = ("/usr/bin/docker", "linux/arm64")
        engine = "/project/build/docker-engine-arm64"
        image = "poke-n64-build-arm64"
        with contextlib.redirect_stdout(io.StringIO()) as output:
            docker_rom.run_in_docker(None, 0, check_tools=True)
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual("build", commands[0][1])
        self.assertEqual(image, commands[0][commands[0].index("--tag") + 1])
        launches = [command for command in commands if command[1] == "run"]
        programs = [command[command.index(image) + 1:] for command in launches]
        self.assertIn(["python3", "tools/build_env.py"], programs)
        compile_check = next(program for program in programs if "tools/check_native.py" in program)
        self.assertIn("--require-mips", compile_check)
        self.assertEqual(engine, compile_check[compile_check.index("--engine") + 1])
        venv = next(program for program in programs if program[0] == "make" and program[-1] == "venv")
        self.assertEqual(engine, venv[venv.index("--directory") + 1])
        for setting in ("VERSION=ntsc-1.2", "REGION=US", "DEBUG_FEATURES=0", "N_THREADS=1"):
            self.assertIn(setting, venv)
        tools = next(program for program in programs if program[0] == "make"
                     and "--directory" in program and program[program.index("--directory") + 1] == engine + "/tools")
        self.assertIn("-j1", tools)
        imports = next(program for program in programs if program[0] == engine + "/.venv/bin/python3")
        self.assertIn("-c", imports)
        python_code = imports[imports.index("-c") + 1]
        for module in ("crunch64", "ipl3checksum", "pygfxd", "rabbitizer"):
            self.assertIn(module, python_code)
        # The pinned Flips implementation explicitly supports this flag and returns 0.
        self.assertIn([engine + "/tools/Flips/flips", "--version"], programs)
        for command in launches:
            self.assertEqual({"/project"}, set(mounts(command)))
            self.assertEqual("linux/arm64", command[command.index("--platform") + 1])
            self.assertNotIn("--dry-run", command)
        for call in self.run.call_args_list:
            self.assertTrue(call.kwargs["check"])
            self.assertFalse(call.kwargs.get("shell", False))
        self.assertIn("No ROM was linked or run", output.getvalue())

    def test_image_and_engine_caches_are_separated_by_daemon_architecture(self) -> None:
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch), contextlib.redirect_stdout(io.StringIO()):
                self.run.reset_mock()
                self.environment.return_value = ("/usr/bin/docker", f"linux/{arch}")
                docker_rom.run_in_docker(self.base, 2)
                build, launch = [call.args[0] for call in self.run.call_args_list]
                image = f"poke-n64-build-{arch}"
                self.assertEqual(image, build[build.index("--tag") + 1])
                self.assertIn(image, launch)
                self.assertEqual(f"/project/build/docker-engine-{arch}", launch[launch.index("--engine") + 1])
                self.assertNotIn("/project/build/docker-engine", launch)
                self.assertNotIn("poke-n64-build", launch)
                for command in (build, launch):
                    self.assertEqual(f"linux/{arch}", command[command.index("--platform") + 1])

    def test_build_environment_ignores_builder_override_without_changing_user_context(self) -> None:
        inherited = {
            "BUILDX_BUILDER": "custom-remote-builder",
            "DOCKER_CONTEXT": "desktop-linux",
            "DOCKER_HOST": "ssh://unit-test-daemon",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": "/certificate path with spaces",
        }
        with patch.dict(os.environ, inherited), contextlib.redirect_stdout(io.StringIO()):
            docker_rom.run_in_docker(self.base, 2)
            self.assertEqual("custom-remote-builder", os.environ["BUILDX_BUILDER"])
            for name, value in inherited.items():
                self.assertEqual(value, os.environ[name])
            build = self.run.call_args_list[0]
            child = build.kwargs["env"]
            self.assertIsNot(child, os.environ)
            self.assertNotIn("BUILDX_BUILDER", child)
            for name in ("DOCKER_CONTEXT", "DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                self.assertEqual(inherited[name], child[name])
            self.assertNotIn("--builder", build.args[0])

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
        self.environment.assert_not_called()

    def test_tool_check_cli_does_not_select_or_validate_a_rom(self) -> None:
        with patch.object(docker_rom, "select_rom") as select, \
             patch.object(docker_rom, "run_in_docker") as launch, \
             patch.object(sys, "argv", ["docker_rom.py", "--check-tools", "--jobs", "2"]):
            docker_rom.main()
        select.assert_not_called()
        launch.assert_called_once_with(None, 2, check_tools=True)

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
