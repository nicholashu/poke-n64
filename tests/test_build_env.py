"""Native preflight tests: no real toolchain, engine checkout or ROM required."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_env


class NativeEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executables: dict[str, str] = {"make": "/usr/bin/make"}
        self.versions: dict[str, tuple[int, str] | Exception] = {
            "/usr/bin/make": (0, "GNU Make 4.3\nBuilt for x86_64-pc-linux-gnu\n"),
        }
        self.which = patch.object(build_env.shutil, "which", side_effect=self.executables.get).start()
        self.run = patch.object(build_env.subprocess, "run", side_effect=self.run_version).start()
        self.addCleanup(patch.stopall)

    def run_version(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.assertIsInstance(command, list)
        self.assertEqual(command[1:], ["--version"])
        self.assertIs(kwargs.get("shell"), False)
        self.assertFalse(kwargs.get("check"))
        self.assertEqual(kwargs.get("timeout"), 10)
        result = self.versions[command[0]]
        if isinstance(result, Exception):
            raise result
        code, text = result
        return subprocess.CompletedProcess(command, code, stdout=text)

    def add_toolchain(self, prefix: str = "mips-linux-gnu-") -> None:
        for name in build_env.MIPS_TOOLS:
            self.executables[prefix + name] = "/opt/toolchain/bin/" + prefix + name

    def test_accepts_complete_toolchain_and_gnu_make(self) -> None:
        self.add_toolchain()
        self.assertEqual(build_env.native_make(), "/usr/bin/make")
        self.run.assert_called_once()

    def test_cli_reports_selected_make_on_success(self) -> None:
        self.add_toolchain()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build_env.main(), 0)
        self.assertIn("preflight passed", output.getvalue())
        self.assertIn("Selected Make: /usr/bin/make", output.getvalue())

    def test_cli_reports_actionable_error_and_nonzero_status(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as error, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(build_env.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Native build preflight failed", error.getvalue())
        self.assertIn("make rom-docker", error.getvalue())

    def test_prefers_valid_gmake_and_passes_its_path_without_a_shell(self) -> None:
        self.add_toolchain()
        path = "/opt/GNU Tools (local) $literal/bin/gmake"
        self.executables["gmake"] = path
        self.versions[path] = (0, "GNU Make 4.4.1\n")
        self.assertEqual(build_env.native_make(), path)
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0], [path, "--version"])
        self.assertIs(self.run.call_args.kwargs["shell"], False)

    def test_tries_make_when_available_gmake_is_not_supported(self) -> None:
        self.add_toolchain()
        self.executables["gmake"] = "/usr/local/bin/gmake"
        self.versions["/usr/local/bin/gmake"] = (0, "GNU Make 3.81\n")
        self.assertEqual(build_env.native_make(), "/usr/bin/make")
        self.assertEqual(self.run.call_count, 2)

    def test_missing_make_explains_gnu_make_and_docker(self) -> None:
        self.executables.clear()
        with self.assertRaisesRegex(RuntimeError, "GNU Make 4.*make rom-docker") as caught:
            build_env.native_make()
        self.assertIn("gmake", str(caught.exception))
        self.assertIn("MIPS GCC/binutils", str(caught.exception))
        self.run.assert_not_called()

    def test_old_apple_make_and_non_gnu_make_are_rejected(self) -> None:
        self.add_toolchain()
        for banner, expected in (
            ("GNU Make 3.81\nCopyright (C) 2006 Free Software Foundation\n", "3.81 is too old"),
            ("BSD make 20261119\n", "not recognized as GNU Make"),
        ):
            with self.subTest(banner=banner):
                self.versions["/usr/bin/make"] = (0, banner)
                with self.assertRaisesRegex(RuntimeError, expected) as caught:
                    build_env.native_make()
                self.assertIn("brew install make", str(caught.exception))
                self.assertIn("make rom-docker", str(caught.exception))

    def test_failing_or_hanging_make_version_does_not_proceed(self) -> None:
        self.add_toolchain()
        for failure in (
            (1, "GNU Make 4.4\n"),
            OSError("cannot execute"),
            subprocess.TimeoutExpired(["make", "--version"], 10),
        ):
            with self.subTest(failure=failure):
                self.which.reset_mock()
                self.versions["/usr/bin/make"] = failure
                with self.assertRaisesRegex(RuntimeError, "make rom-docker"):
                    build_env.native_make()
                self.assertFalse(any(call.args[0].endswith("-ld") for call in self.which.call_args_list))

    def test_missing_mips_linker_explains_native_compiler_requirement(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "No HackerOoT-compatible MIPS linker") as caught:
            build_env.native_make()
        message = str(caught.exception)
        for prefix in build_env.MIPS_PREFIXES:
            self.assertIn(prefix + "ld", message)
        self.assertIn("make rom-docker", message)
        self.assertIn("A host C compiler alone", message)

    def test_mips_cc_override_does_not_change_engine_detection(self) -> None:
        self.executables["custom-cross-gcc"] = "/opt/custom-cross-gcc"
        with patch.dict(os.environ, {"MIPS_CC": "custom-cross-gcc"}):
            with self.assertRaisesRegex(RuntimeError, "MIPS linker"):
                build_env.native_make()
        self.assertNotIn("custom-cross-gcc", [call.args[0] for call in self.which.call_args_list])

    def test_each_missing_matching_compiler_or_binutil_is_reported(self) -> None:
        prefix = "mips-linux-gnu-"
        self.add_toolchain(prefix)
        for tool in ("gcc", "as", "objcopy", "objdump", "nm", "strip"):
            with self.subTest(tool=tool):
                executable = self.executables.pop(prefix + tool)
                try:
                    with self.assertRaisesRegex(RuntimeError, "required tools are missing") as caught:
                        build_env.native_make()
                    self.assertIn(prefix + tool, str(caught.exception))
                    self.assertIn("make rom-docker", str(caught.exception))
                finally:
                    self.executables[prefix + tool] = executable

    def test_incomplete_preferred_prefix_does_not_fall_back_to_complete_one(self) -> None:
        self.add_toolchain("mips-linux-gnu-")
        self.executables["mips-n64-ld"] = "/opt/partial/bin/mips-n64-ld"
        with self.assertRaisesRegex(RuntimeError, "mips-n64-gcc") as caught:
            build_env.native_make()
        self.assertIn("lower-priority toolchain will not override", str(caught.exception))
        self.assertNotIn("mips-linux-gnu-gcc", [call.args[0] for call in self.which.call_args_list])

    def test_engine_prefix_priority_is_linker_led_and_in_exact_order(self) -> None:
        expected = (
            "mips-n64-", "mips64-", "mips-linux-gnu-", "mips64-linux-gnu-", "mips-", "mips64-elf-",
        )
        self.assertEqual(build_env.MIPS_PREFIXES, expected)
        for preferred in range(len(expected)):
            with self.subTest(preferred=expected[preferred]):
                self.executables = {"make": "/usr/bin/make"}
                # The mock's bound dict.get must point at the new mapping.
                self.which.side_effect = self.executables.get
                for prefix in expected[preferred:]:
                    self.add_toolchain(prefix)
                self.which.reset_mock()
                self.assertEqual(build_env.native_make(), "/usr/bin/make")
                queried = [call.args[0] for call in self.which.call_args_list]
                self.assertIn(expected[preferred] + "gcc", queried)
                for lower in expected[preferred + 1:]:
                    self.assertNotIn(lower + "gcc", queried)


if __name__ == "__main__":
    unittest.main()
