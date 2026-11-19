#!/usr/bin/env python3
"""Install the project overlay into an isolated, pinned HackerOoT checkout.

No ROM is required. Existing unknown edits are rejected, never reset or cleaned.
The manifest permits refreshing files installed by a previous invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from pallet_town import build as build_pallet_scene
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "native/upstream.json").read_text())
DEFAULT_ENGINE = ROOT / "build/engine"
MANIFEST = ".poke-overlay.json"


def run(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, file: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Pinned source anchor mismatch in {file}: {old!r}")
    return text.replace(old, new, 1)


def ensure_checkout(engine: Path) -> None:
    if not engine.exists():
        engine.parent.mkdir(parents=True, exist_ok=True)
        run("git", "init", str(engine))
        run("git", "remote", "add", "origin", LOCK["repository"], cwd=engine)
        run("git", "fetch", "--depth", "1", "origin", LOCK["commit"], cwd=engine)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=engine)
    if not (engine / ".git").is_dir():
        raise RuntimeError(f"{engine} is not an isolated git checkout")
    actual = run("git", "rev-parse", "HEAD", cwd=engine, capture=True)
    if actual != LOCK["commit"]:
        raise RuntimeError(f"Expected HackerOoT {LOCK['commit']}, found {actual}. Use a new --engine directory.")


def install(engine: Path, boot_mode: str = "poke") -> None:
    if boot_mode not in ("poke", "control", "oot"):
        raise ValueError("Unknown boot mode")
    ensure_checkout(engine)
    if boot_mode == "control":
        # A real baseline means *zero* Pokémon source, linker or header edits.
        # Earlier 'control' builds retained the custom game state and were
        # therefore unsuitable for isolating early boot failures.
        if (engine / MANIFEST).exists():
            raise RuntimeError(
                f"Control checkout {engine} already contains a Pokémon overlay. "
                "Use a fresh engine directory for the pristine upstream baseline."
            )
        changed = run("git", "status", "--porcelain", "--untracked-files=no",
                      cwd=engine, capture=True)
        if changed:
            raise RuntimeError(
                f"Control checkout {engine} has modified tracked files. "
                "Use a fresh engine directory; the existing checkout is not touched."
            )
        print(f"Verified clean upstream HackerOoT checkout at {engine}.")
        return
    old_manifest_path = engine / MANIFEST
    old_manifest = json.loads(old_manifest_path.read_text()) if old_manifest_path.exists() else {}
    # A previous overlay can leave stale source/object files. Never mix the
    # standalone prototype and OoT total conversion in one engine checkout.
    if boot_mode == "oot" and "src/code/poke_state.c" in old_manifest:
        raise RuntimeError("This checkout contains the legacy overlay. Use a new --engine directory.")
    if boot_mode == "poke" and "src/code/poke_oot.c" in old_manifest:
        raise RuntimeError("This checkout contains the OoT conversion. Use a new --engine directory.")
    original: dict[str, bytes] = {}
    outputs: dict[str, bytes] = {}

    def original_text(path: str) -> str:
        data = subprocess.run(["git", "show", f"{LOCK['commit']}:{path}"], cwd=engine,
                              check=True, stdout=subprocess.PIPE).stdout
        original[path] = data
        return data.decode()

    def patch(path: str, anchor: str, replacement: str) -> None:
        text = outputs[path].decode() if path in outputs else original_text(path)
        outputs[path] = replace_once(text, anchor, replacement, path).encode()

    if boot_mode == "oot":
        # Total conversion uses the REAL Zelda PlayState and camera, not
        # our custom standalone GameState. Kokiri Forest is temporary.
        patch("src/code/title_setup.c", '#include "save.h"',
              '#include "save.h"\n#include "play_state.h"\n#include "sram.h"\n#include "scene.h"')
        patch("src/code/title_setup.c", "    SaveContext_Init();",
              "    SaveContext_Init();\n"
              "    Sram_InitNewSave();\n"
              "    gSaveContext.fileNum = 0xFF; /* RAM-only engineering save */\n"
              "    gSaveContext.save.entranceIndex = ENTR_KOKIRI_FOREST_0;\n"
              "    gSaveContext.save.linkAge = LINK_AGE_CHILD;\n"
              "    gSaveContext.save.cutsceneIndex = CS_INDEX_NONE;\n"
              "    gSaveContext.save.dayTime = CLOCK_TIME(10, 0);\n"
              "    gSaveContext.gameMode = GAMEMODE_NORMAL;")
        patch("src/code/title_setup.c",
              "SET_NEXT_GAMESTATE(&this->state, ConsoleLogo_Init, ConsoleLogoState);",
              "SET_NEXT_GAMESTATE(&this->state, Play_Init, PlayState);")
        patch("src/code/z_play.c", '#include "play_state.h"',
              '#include "play_state.h"\n#include "poke_oot.h"')
        patch("src/code/z_play.c", "    this->gameplayFrames = 0;\n}",
              "    this->gameplayFrames = 0;\n"
              "    PokeOot_OnSceneEnter(this);\n}")
        patch("src/code/z_play.c",
              "        Play_Update(this);\n    }\n\n    PLAY_LOG(4583);",
              "        /* Keep the native OoT camera/actor update alive in battle.\n"
              "         * Suppress gameplay input only; Pokémon consumes the saved\n"
              "         * controller data after Play_Update returns.\n"
              "         */\n"
              "        if (PokeOot_BattleActive()) {\n"
              "            Input savedInput = this->state.input[0];\n"
              "            this->state.input[0].cur.button = 0;\n"
              "            this->state.input[0].press.button = 0;\n"
              "            this->state.input[0].cur.stick_x = 0;\n"
              "            this->state.input[0].cur.stick_y = 0;\n"
              "            Play_Update(this);\n"
              "            this->state.input[0] = savedInput;\n"
              "        } else {\n"
              "            Play_Update(this);\n"
              "        }\n"
              "        PokeOot_Update(this);\n"
              "    }\n\n    PLAY_LOG(4583);")
        patch("src/code/z_play.c",
              "    Play_Draw(this);\n\n    PLAY_LOG(4587);",
              "    Play_Draw(this);\n"
              "    PokeOot_Draw(this);\n\n"
              "    PLAY_LOG(4587);")
        patch("spec/spec", '    include "$(BUILD_DIR)/src/code/z_play.o"',
              '    include "$(BUILD_DIR)/src/code/z_play.o"\n'
              '    include "$(BUILD_DIR)/src/code/poke_core.o"\n'
              '    include "$(BUILD_DIR)/src/code/poke_save.o"\n'
              '    include "$(BUILD_DIR)/src/code/poke_oot.o"\n'
              '    include "$(BUILD_DIR)/src/code/poke_stadium_asset.o"')
        # Retain Kokiri's original scene ID and entrance for this first
        # integration, but load an entirely original Pallet Town scene/room
        # payload in place of Kokiri's ROM segments. Native OoT player,
        # collision, camera and room systems stay intact.
        patch("spec/scenes_n64.inc",
              'include "$(BUILD_DIR)/assets/scenes/overworld/spot04/spot04_scene.o"',
              'include "$(BUILD_DIR)/src/code/poke_pallet_scene.o"')
        patch("spec/scenes_n64.inc",
              'include "$(BUILD_DIR)/assets/scenes/overworld/spot04/spot04_room_0.o"',
              'include "$(BUILD_DIR)/src/code/poke_pallet_room.o"')
        pallet_scene, pallet_room, _ = build_pallet_scene()
        outputs["src/code/poke_pallet_scene.c"] = pallet_scene.encode()
        outputs["src/code/poke_pallet_room.c"] = pallet_room.encode()
        patch("src/makerom/rom_header.s", 'ROM_NAME("THE LEGEND OF ZELDA")',
              'ROM_NAME("POKEMON RED OOT")')
        patch("src/makerom/rom_header.s", 'GAME_ID("ZL")', 'GAME_ID("PO")')
    else:
        # Original standalone proof-of-concept remains unchanged while the
        # native OoT conversion is developed and tested separately.
        for path in ("src/code/graph.c", "src/code/z_game_dlftbls.c", "src/code/title_setup.c"):
            patch(path, '#include "setup_state.h"', '#include "setup_state.h"\n#include "poke_state.h"')
        patch("src/code/title_setup.c",
              "SET_NEXT_GAMESTATE(&this->state, ConsoleLogo_Init, ConsoleLogoState);",
              "SET_NEXT_GAMESTATE(&this->state, Poke_Init, PokeState);")
        path = "include/tables/gamestate_table.h"
        outputs[path] = (original_text(path).rstrip() +
                         "\n/* poke-n64: resident custom RPG state */\n"
                         "DEFINE_GAMESTATE_INTERNAL(Poke, GAMESTATE_POKE)\n").encode()
        patch("spec/spec", '    include "$(BUILD_DIR)/src/code/title_setup.o"',
              '    include "$(BUILD_DIR)/src/code/title_setup.o"\n'
              '    include "$(BUILD_DIR)/src/code/poke_core.o"\n'
              '    include "$(BUILD_DIR)/src/code/poke_save.o"\n'
              '    include "$(BUILD_DIR)/src/code/poke_state.o"')
        patch("src/makerom/rom_header.s", 'ROM_NAME("THE LEGEND OF ZELDA")',
              'ROM_NAME("POKE N64 MVP")')
        patch("src/makerom/rom_header.s", 'GAME_ID("ZL")', 'GAME_ID("PK")')
    # The upstream stdint header only supplies pointer-sized types. Extend it with
    # standard C fixed widths rather than changing the shared portable sources.
    patch("include/libc/stdint.h", "#define STDINT_H", "#define STDINT_H\n\n"
          "typedef signed char int8_t;\ntypedef unsigned char uint8_t;\n"
          "typedef signed short int16_t;\ntypedef unsigned short uint16_t;\n"
          "typedef signed int int32_t;\ntypedef unsigned int uint32_t;\n"
          "typedef signed long long int64_t;\ntypedef unsigned long long uint64_t;\n"
          "#define UINT32_C(value) value ## U\n#define INT32_C(value) value\n")
    if boot_mode == "poke":
        patch("include/config/config_memory.h", "#define POLY_OPA_BUFFER_SIZE 0x1A00",
              "#define POLY_OPA_BUFFER_SIZE 0x3000")
        patch("include/config/config_memory.h", "#define OVERLAY_BUFFER_SIZE 0x400",
              "#define OVERLAY_BUFFER_SIZE 0x2000")
    # Fixed hardware target and low-noise runtime. No asset-dependent map selects.
    outputs[".make_options.mk"] = b"VERSION=ntsc-1.2\nREGION=US\nDEBUG_FEATURES=0\nCOMPILER=gcc\n"
    if boot_mode == "oot":
        copies = {
            "native/oot_conversion.c": "src/code/poke_oot.c",
            "native/oot_conversion.h": "include/poke_oot.h",
            "native/stadium_asset.h": "include/stadium_asset.h",
            "include/poke.h": "include/poke.h",
            "src/core.c": "src/code/poke_core.c",
            "src/save.c": "src/code/poke_save.c",
        }
    else:
        copies = {
            "native/poke_state.c": "src/code/poke_state.c",
            "native/poke_state.h": "include/poke_state.h",
            "include/poke.h": "include/poke.h",
            "src/core.c": "src/code/poke_core.c",
            "src/save.c": "src/code/poke_save.c",
        }
    if boot_mode == "oot":
        # Real Bulbasaur assets remain outside Git, under assets/private/.
        # CI and the working test ROM link an original no-op implementation.
        generated_asset = ROOT / "assets/private/stadium/001/stadium_bulbasaur_n64.c"
        source = (generated_asset if generated_asset.is_file() else
                  ROOT / "native/stadium_asset_stub.c")
        outputs["src/code/poke_stadium_asset.c"] = source.read_bytes()
    for source, target in copies.items():
        outputs[target] = (ROOT / source).read_bytes()
    # Validate every write first: fail without partly applying an overlay.
    for path, desired in outputs.items():
        dest = engine / path
        if dest.exists():
            current = dest.read_bytes()
            known = current == desired or current == original.get(path) or sha(current) == old_manifest.get(path)
            if not known:
                raise RuntimeError(f"Refusing to overwrite unexpected changes in {dest}")
    # Preserve mtimes of identical sources. Make uses them as input to its
    # dependency graph, so unconditional rewrites caused substantial rebuilds
    # even when the project overlay had not changed.
    for path, desired in outputs.items():
        dest = engine / path
        if not dest.is_file() or dest.read_bytes() != desired:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(desired)
    manifest_data = json.dumps({path: sha(data) for path, data in outputs.items()}, indent=2) + "\n"
    if not old_manifest_path.is_file() or old_manifest_path.read_text() != manifest_data:
        old_manifest_path.write_text(manifest_data)
    print(f"Installed poke-n64 overlay at {engine} (HackerOoT {LOCK['commit'][:12]}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--boot-mode", choices=("poke", "control", "oot"), default="poke")
    args = parser.parse_args()
    try:
        install(args.engine.resolve(), boot_mode=args.boot_mode)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Bootstrap failed: {exc}")


if __name__ == "__main__":
    main()
