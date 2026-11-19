"""ROM-driven Pallet build boundaries using synthetic data only."""
from __future__ import annotations

import contextlib
import csv
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import bootstrap
import build_rom
import check_native
import docker_rom
import test_tools as overlay_fixtures


def compiled_fixture(tag="A"):
    """Original fake compiler output: no game data or Nintendo source."""
    return {
        "scene_header": f"/* synthetic {tag} scene header */\n",
        "scene": f"/* synthetic {tag} scene */\n",
        "room_header": f"/* synthetic {tag} room header */\n",
        "room": f"/* synthetic {tag} room */\n",
        "data_source": f"/* synthetic {tag} imported runtime data */\n",
        "metadata": {"fixture": tag},
        "world": {},
    }


class PalletInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = self.root / 'Pokemon, Red ($literal) "quoted".gb'

    def test_size_is_checked_before_loading_or_compiling(self):
        self.rom.write_bytes(b"synthetic truncated input")
        module = types.ModuleType("pallet_rom")
        module.compile_pallet = Mock()
        with patch.dict(sys.modules, {"pallet_rom": module}):
            with self.assertRaisesRegex(RuntimeError, "1 MiB"):
                bootstrap.compile_pokemon_rom(self.rom)
        module.compile_pallet.assert_not_called()

    def test_supported_size_does_not_bypass_compiler_identity_validation(self):
        data = bytes(1024 * 1024)
        self.rom.write_bytes(data)
        module = types.ModuleType("pallet_rom")
        module.compile_pallet = Mock(side_effect=ValueError("unsupported ROM checksum"))
        with patch.dict(sys.modules, {"pallet_rom": module}):
            with self.assertRaisesRegex(RuntimeError, "unsupported ROM checksum"):
                bootstrap.compile_pokemon_rom(self.rom)
        module.compile_pallet.assert_called_once_with(data)
        self.assertEqual(self.rom.read_bytes(), data)

    def test_wrong_mode_and_invalid_rom_fail_before_checkout(self):
        self.rom.write_bytes(b"bad input")
        with patch.object(bootstrap, "ensure_checkout") as checkout:
            with self.assertRaisesRegex(RuntimeError, "requires.*OoT"):
                bootstrap.install(self.root / "engine", pokemon_rom=self.rom)
            with self.assertRaisesRegex(RuntimeError, "1 MiB"):
                bootstrap.install(self.root / "engine", boot_mode="oot", pokemon_rom=self.rom)
        checkout.assert_not_called()
        self.assertFalse((self.root / "engine").exists())

    def test_native_build_rejects_gb_input_before_tools_or_writes(self):
        self.rom.write_bytes(b"bad input")
        with patch.object(sys, "argv", ["build_rom.py", "--oot-conversion", "--pokemon-rom", str(self.rom)]), \
             patch.object(build_rom, "install") as install, \
             patch.object(build_rom, "native_make") as native, \
             patch.object(build_rom, "select_rom") as base:
            with self.assertRaisesRegex(RuntimeError, "1 MiB"):
                build_rom.main()
        install.assert_not_called()
        native.assert_not_called()
        base.assert_not_called()

    def test_check_only_validates_both_inputs_without_installing(self):
        with patch.object(sys, "argv", ["build_rom.py", "--oot-conversion", "--check"]), \
             patch.dict(os.environ, {"POKE_POKEMON_ROM": str(self.rom)}), \
             patch.object(build_rom, "compile_pokemon_rom", return_value=compiled_fixture()) as compile_rom, \
             patch.object(build_rom, "select_rom", return_value=(self.root / "oot.z64", b"synthetic")), \
             patch.object(build_rom, "install") as install, \
             patch.object(build_rom, "native_make") as native, \
             contextlib.redirect_stdout(io.StringIO()):
            build_rom.main()
        compile_rom.assert_called_once_with(self.rom)
        install.assert_not_called()
        native.assert_not_called()

    def test_compile_check_rejects_invalid_input_without_checkout(self):
        self.rom.write_bytes(b"bad input")
        with patch.object(sys, "argv", ["check_native.py", "--oot-conversion", "--pokemon-rom", str(self.rom)]), \
             patch.object(bootstrap, "ensure_checkout") as checkout:
            with self.assertRaisesRegex(RuntimeError, "1 MiB"):
                check_native.main()
        checkout.assert_not_called()


class PalletOverlayTests(unittest.TestCase):
    # Reuse only the fixture factory, not its other TestCase methods.
    setUp = overlay_fixtures.OverlayTests.setUp

    def test_import_installs_generated_assets_and_all_runtime_objects(self):
        compiled = compiled_fixture()
        source = self.root / "private source.gb"
        with patch.object(bootstrap, "compile_pokemon_rom", return_value=compiled) as compile_rom, \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot", pokemon_rom=source)
        compile_rom.assert_called_once_with(source)
        for path, key in (
            ("poke_pallet_scene_header.c", "scene_header"),
            ("poke_pallet_scene.c", "scene"),
            ("poke_pallet_room_header.c", "room_header"),
            ("poke_pallet_room.c", "room"),
            ("poke_pallet_data.c", "data_source"),
        ):
            self.assertEqual((self.engine / "src/code" / path).read_text(), compiled[key])
        spec = (self.engine / "spec/spec").read_text()
        for name in ("poke_pallet_import", "poke_pallet_native", "poke_pallet_data"):
            self.assertIn(f'include "$(BUILD_DIR)/src/code/{name}.o"', spec)
            self.assertTrue((self.engine / f"src/code/{name}.c").is_file())
        self.assertTrue((self.engine / "include/poke_pallet_import.h").is_file())
        self.assertTrue((self.engine / "include/poke_pallet_native.h").is_file())
        self.assertIn("PokeOot_InputLocked()", (self.engine / "src/code/z_play.c").read_text())

    def test_refresh_and_return_to_default_do_not_retain_imported_data(self):
        source = self.root / "private source.gb"
        with patch.object(bootstrap, "compile_pokemon_rom", return_value=compiled_fixture()), \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot", pokemon_rom=source)
            generated = self.engine / "src/code/poke_pallet_data.c"
            timestamp = 1_600_000_000_000_000_000
            os.utime(generated, ns=(timestamp, timestamp))
            bootstrap.install(self.engine, boot_mode="oot", pokemon_rom=source)
            self.assertEqual(generated.stat().st_mtime_ns, timestamp)
        with patch.object(bootstrap, "compile_pokemon_rom", return_value=compiled_fixture("B")), \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot", pokemon_rom=source)
        self.assertEqual(generated.read_text(), compiled_fixture("B")["data_source"])
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot")
        self.assertEqual(generated.read_bytes(), (self.project / "native/pallet_import_stub.c").read_bytes())
        scene = (self.engine / "src/code/poke_pallet_scene.c").read_text()
        self.assertNotIn("synthetic B", scene)
        self.assertIn("gPalletCollision", scene)

    def test_invalid_reimport_keeps_previous_manifest_and_assets(self):
        source = self.root / "private source.gb"
        with patch.object(bootstrap, "compile_pokemon_rom", return_value=compiled_fixture()), \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot", pokemon_rom=source)
        tracked = [self.engine / bootstrap.MANIFEST, self.engine / "src/code/poke_pallet_data.c"]
        previous = [path.read_bytes() for path in tracked]
        with patch.object(bootstrap, "compile_pokemon_rom", side_effect=RuntimeError("unsupported ROM")):
            with self.assertRaisesRegex(RuntimeError, "unsupported ROM"):
                bootstrap.install(self.engine, boot_mode="oot", pokemon_rom=source)
        self.assertEqual(previous, [path.read_bytes() for path in tracked])


class PalletDockerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = self.root / 'Pokemon, Red ($literal) "quoted".gb'
        self.base = self.root / "oot.z64"
        self.project = self.root / "project"
        self.project.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(docker_rom, "ROOT", self.project).start()
        self.compile = patch.object(docker_rom, "compile_pokemon_rom", return_value=compiled_fixture()).start()
        self.environment = patch.object(docker_rom, "docker_environment", return_value=("docker", "linux/arm64")).start()
        self.run = patch.object(docker_rom.subprocess, "run").start()

    def mounts(self, command):
        result = {}
        for index, argument in enumerate(command):
            if argument == "--mount":
                fields = next(csv.reader(io.StringIO(command[index + 1])))
                mount = dict(field.split("=", 1) if "=" in field else (field, "") for field in fields)
                result[mount["target"]] = mount
        return result

    def test_external_rom_is_read_only_and_forwarded_with_container_path(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            docker_rom.run_in_docker(self.base, 2, oot_conversion=True, pokemon_rom=self.rom)
        self.compile.assert_called_once_with(self.rom)
        command = self.run.call_args_list[-1].args[0]
        mounted = self.mounts(command)["/inputs/pokemon.gb"]
        self.assertEqual(mounted["source"], str(self.rom.resolve()))
        self.assertIn("readonly", mounted)
        self.assertEqual(command[command.index("--pokemon-rom") + 1], "/inputs/pokemon.gb")
        self.assertEqual(command[command.index("--engine") + 1], "/project/build/docker-engine-arm64-pallet")
        self.assertIn("poke-n64-pallet.z64", output.getvalue())
        self.assertNotIn(str(self.rom), command)
        for call in self.run.call_args_list:
            self.assertFalse(call.kwargs.get("shell", False))

    def test_bad_rom_fails_before_docker_is_contacted(self):
        self.compile.side_effect = RuntimeError("unsupported ROM")
        with self.assertRaisesRegex(RuntimeError, "unsupported ROM"):
            docker_rom.run_in_docker(self.base, 2, oot_conversion=True, pokemon_rom=self.rom)
        self.environment.assert_not_called()
        self.run.assert_not_called()

    def test_check_native_passes_imported_rom_to_real_compile_check(self):
        with contextlib.redirect_stdout(io.StringIO()):
            docker_rom.run_in_docker(None, 2, check_tools=True, oot_conversion=True, pokemon_rom=self.rom)
        command = next(call.args[0] for call in self.run.call_args_list if "tools/check_native.py" in call.args[0])
        self.assertEqual(command[command.index("--pokemon-rom") + 1], "/inputs/pokemon.gb")
        self.assertIn("readonly", self.mounts(command)["/inputs/pokemon.gb"])

    def test_wrong_mode_and_missing_required_input_never_build_default(self):
        with self.assertRaisesRegex(RuntimeError, "requires --oot-conversion"):
            docker_rom.run_in_docker(self.base, 1, pokemon_rom=self.rom)
        with patch.dict(os.environ, {"POKE_POKEMON_ROM": ""}), \
             patch.object(sys, "argv", ["docker_rom.py", "--oot-conversion", "--require-pokemon-rom"]):
            with self.assertRaisesRegex(RuntimeError, "requires POKEMON_ROM"):
                docker_rom.main()
        self.environment.assert_not_called()
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
