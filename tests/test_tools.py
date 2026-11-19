"""Guardrails for engine installation and user-supplied ROM handling.

Uses a small local git fixture to exercise overwrite protection. No ROM, network
or engine checkout is needed. Real engine integration is checked separately by
`tools/check_native.py --require-mips`.
"""
from __future__ import annotations
import contextlib
import hashlib
import io
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
import bootstrap
import build_rom


class OverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = self.root / "engine"
        self.project = self.root / "project"
        self.engine.mkdir()
        fixtures = {
            "src/code/graph.c": '#include "setup_state.h"\n',
            "src/code/z_game_dlftbls.c": '#include "setup_state.h"\n',
            "src/code/title_setup.c": '#include "setup_state.h"\n#include "save.h"\n    SaveContext_Init();\nSET_NEXT_GAMESTATE(&this->state, ConsoleLogo_Init, ConsoleLogoState);\n',
            "src/code/z_play.c": '#include "play_state.h"\n    this->gameplayFrames = 0;\n}\n        Play_Update(this);\n    }\n\n    PLAY_LOG(4583);\n    Play_Draw(this);\n\n    PLAY_LOG(4587);\n',
            "include/tables/gamestate_table.h": 'DEFINE_GAMESTATE_INTERNAL(Setup, GAMESTATE_SETUP)\n',
            "spec/spec": '    include "$(BUILD_DIR)/src/code/title_setup.o"\n'
                         '    include "$(BUILD_DIR)/src/code/z_play.o"\n',
            "src/makerom/rom_header.s": 'ROM_NAME("THE LEGEND OF ZELDA")\nGAME_ID("ZL")\n',
            "include/libc/stdint.h": '#ifndef STDINT_H\n#define STDINT_H\n#endif\n',
            "include/config/config_memory.h": '#define POLY_OPA_BUFFER_SIZE 0x1A00\n#define OVERLAY_BUFFER_SIZE 0x400\n',
        }
        for name, content in fixtures.items():
            target = self.engine / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        for name in ("native/poke_state.c", "native/poke_state.h", "native/oot_conversion.c",
                     "native/oot_conversion.h", "native/stadium_asset.h",
                     "native/stadium_asset_stub.c", "include/poke.h",
                     "src/core.c", "src/save.c"):
            target = self.project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name in ("native/stadium_asset.h", "native/stadium_asset_stub.c"):
                target.write_text((ROOT / name).read_text())
            else:
                target.write_text(f"/* project fixture: {name} */\n")
        subprocess.run(["git", "init", "-q", str(self.engine)], check=True)
        subprocess.run(["git", "add", "."], cwd=self.engine, check=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
                       cwd=self.engine, check=True)
        self.commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.engine, text=True).strip()
        self.addCleanup(patch.stopall)
        patch.object(bootstrap, "ROOT", self.project).start()
        patch.object(bootstrap, "LOCK", {"commit": self.commit, "repository": str(self.engine)}).start()

    def install(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine)

    def test_idempotent_install_registers_native_state(self) -> None:
        self.install()
        first = (self.engine / bootstrap.MANIFEST).read_bytes()
        self.install()
        self.assertEqual(first, (self.engine / bootstrap.MANIFEST).read_bytes())
        self.assertIn("Poke_Init, PokeState", (self.engine / "src/code/title_setup.c").read_text())
        self.assertIn("GAMESTATE_POKE", (self.engine / "include/tables/gamestate_table.h").read_text())
        for name in ("poke_core.o", "poke_save.o", "poke_state.o"):
            self.assertIn(name, (self.engine / "spec/spec").read_text())
        # Boot probe and frame counter are source contracts, checked independently
        # of the small mocked engine files used in these overlay tests.
        runtime = (ROOT / "native/poke_state.c").read_text()
        self.assertIn("static void DrawBoot(PokeState* self)", runtime)
        self.assertIn("self->bootSplash = 1;", runtime)
        # Heavy initialization is deliberately after the A-press branch, not
        # in Poke_Init before the first diagnostic framebuffer.
        init = runtime.split("void Poke_Init(GameState* state)", 1)[1].split("void Poke_Destroy(", 1)[0]
        self.assertNotIn("Matrix_Init(", init)
        self.assertNotIn("JournalLoad(", init)
        self.assertNotIn("poke_init(", init)
        self.assertIn("if (self->bootSplash)", runtime)
        self.assertIn("if (!(state->input[0].cur.button & BTN_Z)) JournalLoad(self);", runtime)
        self.assertEqual(runtime.count("self->drawBoxes = 0;"), 2)  # Frame and state initialization
        self.assertNotIn("self->drawBoxes = 0;", runtime.split("static void DrawWorld", 1)[1].split("static void Panel", 1)[0])
        self.assertIn("if (v == NULL) return;", runtime)
        # Native camera uses Zelda-like third-person tracking and has a
        # separate Stadium presentation. Keep Gen 1 rules/save codec untouched.
        self.assertIn("static u16 ReadFieldKeys(PokeState* self, const Input* input)", runtime)
        self.assertIn("static void FieldCamera(PokeState* self, Vec3f* eye, Vec3f* at)", runtime)
        self.assertIn("static void StadiumCamera(PokeState* self, Vec3f* eye, Vec3f* at)", runtime)
        self.assertIn("keys = ReadFieldKeys(self, &state->input[0]);", runtime)
        self.assertIn("if (held & BTN_Z)", runtime)
        self.assertIn("if (held & BTN_CLEFT)", runtime)
        self.assertIn("if (battle) {", runtime)
        self.assertIn("StadiumCamera(self, &eye, &at);", runtime)
        self.assertIn("FieldCamera(self, &eye, &at);", runtime)
        self.assertIn("self->cameraYaw = 0.0f;", runtime)
        self.assertIn("self->cameraReady = 0;", runtime)
        self.assertIn("self->wasInBattle = 0;", runtime)
        # The movement heading must remain stable while the camera rotates.
        self.assertIn("self->movementBasisYaw = self->cameraYaw;", runtime)
        self.assertIn("Math_CosF(self->movementBasisYaw)", runtime)
        self.assertIn("Math_SinF(self->movementBasisYaw)", runtime)
        self.assertIn("self->movementActive = 0;", runtime)
        # Camera eye and target now share one smoothed pivot and the wall
        # check accounts for roofs, rather than treating all tiles as infinite.
        self.assertIn("self->cameraFocusX = CameraApproach(", runtime)
        self.assertIn("self->cameraFocusZ = CameraApproach(", runtime)
        self.assertIn("rayHeight < 126.0f", runtime)
        self.assertIn("rayHeight < 113.0f", runtime)
        self.assertIn("freeDistance < self->cameraDistance", runtime)
        self.assertIn("Menus and battles end a stick gesture.", runtime)
        self.assertIn("The saved position may be elsewhere.", runtime)
        self.assertIn("if (self->wasInBattle) {", runtime)
        self.assertIn("static void PrintShort(", runtime)

    def test_oot_conversion_uses_stock_playstate_without_custom_gamestate(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot")
        entry = (self.engine / "src/code/title_setup.c").read_text()
        self.assertIn("Sram_InitNewSave();", entry)
        self.assertIn("ENTR_KOKIRI_FOREST_0", entry)
        self.assertIn("SET_NEXT_GAMESTATE(&this->state, Play_Init, PlayState);", entry)
        self.assertNotIn("Poke_Init, PokeState", entry)
        code = (self.engine / "src/code/z_play.c").read_text()
        for hook in ("PokeOot_OnSceneEnter(this);", "PokeOot_Update(this);", "PokeOot_Draw(this);"):
            self.assertIn(hook, code)
        spec = (self.engine / "spec/spec").read_text()
        self.assertIn("poke_oot.o", spec)
        self.assertIn("poke_core.o", spec)
        self.assertNotIn("poke_state.o", spec)
        self.assertNotIn("GAMESTATE_POKE", (self.engine / "include/tables/gamestate_table.h").read_text())
        self.assertTrue((self.engine / "include/poke_oot.h").exists())
        self.assertTrue((self.engine / "src/code/poke_oot.c").exists())
        self.assertIn("poke_stadium_asset.o", spec)
        self.assertIn("PokeStadium_DrawBulbasaur", (self.engine / "src/code/poke_stadium_asset.c").read_text())
        first = (self.engine / bootstrap.MANIFEST).read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot")
        self.assertEqual((self.engine / bootstrap.MANIFEST).read_bytes(), first)

    def test_conversion_never_overwrites_unrelated_source_edits(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="oot")
        target = self.engine / "src/code/z_play.c"
        target.write_text(target.read_text() + "/* local experimental change */\n")
        with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
            bootstrap.install(self.engine, boot_mode="oot")

    def test_control_boot_is_pristine_upstream_with_no_pokemon_overlay(self) -> None:
        original = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=self.engine, text=True,
        )
        self.assertEqual(original, "")
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.install(self.engine, boot_mode="control")
        self.assertFalse((self.engine / bootstrap.MANIFEST).exists())
        self.assertNotIn("poke_state", (self.engine / "spec/spec").read_text())
        self.assertNotIn("POKE", (self.engine / "src/makerom/rom_header.s").read_text())
        self.assertIn(
            "SET_NEXT_GAMESTATE(&this->state, ConsoleLogo_Init, ConsoleLogoState);",
            (self.engine / "src/code/title_setup.c").read_text(),
        )
        self.assertEqual(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=self.engine, text=True,
            ), "",
        )

    def test_control_boot_rejects_a_previous_pokemon_overlay(self) -> None:
        self.install()
        with self.assertRaisesRegex(RuntimeError, "already contains a Pokémon overlay"):
            bootstrap.install(self.engine, boot_mode="control")

    def test_control_boot_rejects_edited_upstream_files_without_overwriting(self) -> None:
        target = self.engine / "src/code/title_setup.c"
        target.write_text(target.read_text() + "/* local edit */\\n")
        before = target.read_text()
        with self.assertRaisesRegex(RuntimeError, "modified tracked files"):
            bootstrap.install(self.engine, boot_mode="control")
        self.assertEqual(target.read_text(), before)

    def test_refreshes_own_sources_but_keeps_unrelated_files(self) -> None:
        self.install()
        untouched = self.engine / "notes.txt"
        untouched.write_text("keep me")
        (self.project / "src/core.c").write_text("/* new core */\n")
        self.install()
        self.assertEqual("/* new core */\n", (self.engine / "src/code/poke_core.c").read_text())
        self.assertEqual("keep me", untouched.read_text())

    def test_unknown_edits_abort_before_any_write(self) -> None:
        self.install()
        changed = self.engine / "src/code/title_setup.c"
        changed.write_text(changed.read_text() + "/* user edit */\n")
        (self.project / "src/core.c").write_text("/* requested update */\n")
        old_core = (self.engine / "src/code/poke_core.c").read_bytes()
        old_manifest = (self.engine / bootstrap.MANIFEST).read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
            self.install()
        self.assertEqual(old_core, (self.engine / "src/code/poke_core.c").read_bytes())
        self.assertEqual(old_manifest, (self.engine / bootstrap.MANIFEST).read_bytes())
        self.assertIn("user edit", changed.read_text())

    def test_wrong_upstream_commit_is_rejected(self) -> None:
        with patch.object(bootstrap, "LOCK", {"commit": "0" * 40}):
            with self.assertRaisesRegex(RuntimeError, "Expected HackerOoT"):
                self.install()
        self.assertFalse((self.engine / bootstrap.MANIFEST).exists())


class RomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "input.rom"
        self.canonical = bytes.fromhex("80371240") + bytes(range(12))
        self.lock = {"base_rom_size": len(self.canonical),
                     "base_rom_md5": hashlib.md5(self.canonical).hexdigest()}
        self.override = patch.object(build_rom, "LOCK", self.lock)
        self.override.start()
        self.addCleanup(self.override.stop)

    def test_normalizes_all_three_n64_byte_orders_without_changing_input(self) -> None:
        v64 = b"".join(self.canonical[i:i+2][::-1] for i in range(0, len(self.canonical), 2))
        n64 = b"".join(self.canonical[i:i+4][::-1] for i in range(0, len(self.canonical), 4))
        for image in (self.canonical, v64, n64):
            self.path.write_bytes(image)
            self.assertEqual(self.canonical, build_rom.normalized_rom(self.path))
            self.assertEqual(image, self.path.read_bytes())

    def test_rejects_invalid_header_and_checksum(self) -> None:
        self.path.write_bytes(b"bad!" + self.canonical[4:])
        with self.assertRaisesRegex(RuntimeError, "header"):
            build_rom.normalized_rom(self.path)
        self.path.write_bytes(self.canonical[:-1] + b"\xff")
        with self.assertRaisesRegex(RuntimeError, "Wrong base ROM"):
            build_rom.normalized_rom(self.path)

    def test_bad_input_fails_before_engine_install(self) -> None:
        self.path.write_bytes(b"not a ROM")
        with patch.object(build_rom, "install") as installer:
            with patch.object(sys, "argv", ["build_rom.py", "--rom", str(self.path)]):
                with self.assertRaisesRegex(RuntimeError, "Expected a 32 MiB"):
                    build_rom.main()
            installer.assert_not_called()

    def test_missing_input_fails_before_engine_install(self) -> None:
        with patch.object(build_rom, "install") as installer:
            with patch.object(sys, "argv", ["build_rom.py", "--rom", str(self.path)]):
                with self.assertRaises(FileNotFoundError):
                    build_rom.main()
            installer.assert_not_called()

    def test_missing_native_tools_fail_before_engine_install_or_rom_copy(self) -> None:
        self.path.write_bytes(self.canonical)
        engine = Path(self.temp.name) / "engine"
        with patch.object(build_rom, "native_make", side_effect=RuntimeError("Run make rom-docker")), \
             patch.object(build_rom, "install") as installer, \
             patch.object(build_rom.subprocess, "run") as run, \
             patch.object(sys, "argv", ["build_rom.py", "--rom", str(self.path), "--engine", str(engine)]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "make rom-docker"):
                build_rom.main()
        installer.assert_not_called()
        run.assert_not_called()
        self.assertFalse(engine.exists())
        self.assertEqual(self.canonical, self.path.read_bytes())

    def test_auto_detection_uses_contents_with_mixed_games_and_spaces(self) -> None:
        directory = Path(self.temp.name) / "roms"
        directory.mkdir()
        wrong = directory / "A - Legend of Zelda (USA) (Rev 2).z64"
        stadium = directory / "Pokemon Stadium (USA) (Rev 2).z64"
        right = directory / "Legend of Zelda, The - Ocarina of Time (USA) (Rev 2).z64"
        wrong.write_bytes(self.canonical[:-1] + b"\xff")
        stadium.write_bytes(b"other game")
        right.write_bytes(self.canonical)
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        selected, data = build_rom.select_rom(None, directory)
        self.assertEqual(right, selected)
        self.assertEqual(self.canonical, data)
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_auto_detection_accepts_uppercase_swapped_image(self) -> None:
        swapped = b"".join(self.canonical[i:i+2][::-1] for i in range(0, len(self.canonical), 2))
        self.path = Path(self.temp.name) / "my dump.V64"
        self.path.write_bytes(swapped)
        selected, data = build_rom.select_rom(None, Path(self.temp.name))
        self.assertEqual(self.path, selected)
        self.assertEqual(self.canonical, data)
        self.assertEqual(swapped, self.path.read_bytes())

    def test_explicit_bad_input_does_not_fall_back_to_matching_neighbor(self) -> None:
        self.path.write_bytes(self.canonical)
        wrong = Path(self.temp.name) / "wrong.z64"
        wrong.write_bytes(self.canonical[:-1] + b"\xff")
        with self.assertRaisesRegex(RuntimeError, "Wrong base ROM"):
            build_rom.select_rom(wrong, Path(self.temp.name))

    def test_missing_empty_and_nonmatching_folders_explain_the_input_problem(self) -> None:
        directory = Path(self.temp.name) / "roms"
        with self.assertRaisesRegex(RuntimeError, "No local ROM folder"):
            build_rom.select_rom(None, directory)
        directory.mkdir()
        (directory / "archive.zip").write_bytes(b"not an extracted ROM")
        with self.assertRaisesRegex(RuntimeError, "archives must be extracted"):
            build_rom.select_rom(None, directory)
        (directory / "Pokemon Stadium.z64").write_bytes(self.canonical[:-1] + b"\xff")
        with self.assertRaisesRegex(RuntimeError, "No matching OoT"):
            build_rom.select_rom(None, directory)

    def test_check_only_does_not_install_build_or_write(self) -> None:
        self.path.write_bytes(self.canonical)
        with patch.object(build_rom, "install") as installer, \
             patch.object(build_rom, "native_make", side_effect=RuntimeError("no compiler")) as preflight, \
             patch.object(build_rom.subprocess, "run") as run, \
             patch.dict(os.environ, {"POKE_N64_ROM": ""}), \
             patch.object(sys, "argv", ["build_rom.py", "--roms-dir", self.temp.name, "--check"]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            build_rom.main()
        installer.assert_not_called()
        preflight.assert_not_called()
        run.assert_not_called()
        self.assertIn("Validated OoT US NTSC 1.2", output.getvalue())
        self.assertEqual([self.path], list(Path(self.temp.name).iterdir()))
        self.assertEqual(self.canonical, self.path.read_bytes())

    def test_make_environment_path_is_used_verbatim(self) -> None:
        self.path = Path(self.temp.name) / "space (Rev 2) $literal.z64"
        self.path.write_bytes(self.canonical)
        with patch.dict(os.environ, {"POKE_N64_ROM": str(self.path)}), \
             patch.object(sys, "argv", ["build_rom.py", "--check"]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            build_rom.main()
        self.assertIn(str(self.path), output.getvalue())


if __name__ == "__main__":
    unittest.main()
