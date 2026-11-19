#!/usr/bin/env python3
"""Check integration against real pinned engine headers, without a base ROM.

MIPS GCC builds real big-endian VR4300 objects. With only a host GCC, perform a
32-bit freestanding syntax check and explicitly report that weaker evidence.
Neither mode links a ROM or substitutes for emulator/hardware testing.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re
import xml.etree.ElementTree as ET
from bootstrap import DEFAULT_ENGINE, ROOT, install
from kanto_layout import ORDER, ROOMS


def declaration_include(engine: Path, output: Path) -> Path:
    """Generate declaration-only compile prerequisites from pinned XML.

    These live exclusively in the check output directory, never the engine's
    real asset tree. A real ROM build still extracts its authoritative headers
    and data. No fake definitions or replacement runtime assets are created.
    """
    include = output / "declarations"
    relative = Path("assets/objects/gameplay_keep/gameplay_keep.h")
    if (engine / relative).exists():
        return include
    source = (engine / "src/code/z_player_lib.c").read_text()
    used = set(re.findall(r"\bg[A-Z][A-Za-z0-9_]*\b", source))
    xml = ET.parse(engine / "assets/xml/objects/gameplay_keep.xml")
    lines = ['/* Compile-only declarations from pinned extraction XML. */',
             '#include "ultra64.h"', '#include "animation.h"']
    for node in xml.iter():
        name = node.get("Name")
        if name not in used:
            continue
        if node.tag == "Texture":
            lines.append(f"extern u64 {name}[];")
        elif node.tag == "DList":
            lines.append(f"extern Gfx {name}[];")
        elif node.tag == "PlayerAnimation":
            lines.append(f"extern LinkAnimationHeader {name};")
        elif node.tag == "Array" and node.find("Vector") is not None:
            vector = node.find("Vector")
            if vector.get("Type") != "s16" or vector.get("Dimensions") != "3":
                raise RuntimeError(f"Unsupported XML vector declaration: {name}")
            lines.append(f"extern Vec3s {name}[{node.get('Count')}];")
        else:
            raise RuntimeError(f"Unsupported compile-only XML declaration: {node.tag} {name}")
    target = include / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n")
    return include


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--require-mips", action="store_true")
    parser.add_argument("--oot-conversion", action="store_true",
                        help="check native PlayState total-conversion sources")
    args = parser.parse_args()
    engine = args.engine.resolve()
    install(engine, boot_mode="oot" if args.oot_conversion else "poke")
    compiler = os.environ.get("MIPS_CC")
    if compiler and not shutil.which(compiler):
        sys.exit(f"MIPS_CC does not exist: {compiler}")
    if not compiler:
        compiler = next((c for c in ("mips-linux-gnu-gcc", "mips64-elf-gcc", "mips-n64-gcc") if shutil.which(c)), None)
    native = bool(compiler)
    if not native:
        if args.require_mips:
            sys.exit("MIPS compiler missing. Install gcc-mips-linux-gnu or set MIPS_CC.")
        compiler = shutil.which("cc")
        if not compiler:
            sys.exit("No C compiler found.")
    flags = ["-std=gnu11", "-nostdinc", "-ffreestanding", "-fno-builtin", "-funsigned-char",
             "-Iinclude", "-Iinclude/libc", "-Isrc", "-I.",
             "-D_LANGUAGE_C", "-DOOT_VERSION=NTSC_1_2", "-DDEBUG_FEATURES=0", "-DF3DEX_GBI_2",
             "-DPLATFORM_N64=1", "-DPLATFORM_GC=0", "-DPLATFORM_IQUE=0",
             "-DNDEBUG", "-DOOT_REGION=REGION_US", "-DOOT_REVISION=15", "-DLIBULTRA_PATCH=1",
             "-DLIBULTRA_VERSION=LIBULTRA_VERSION_I", "-DCOMPILER_GCC", "-DNON_MATCHING", "-DAVOID_UB",
             "-Wall", "-Wextra", "-Wno-unused-parameter", "-Wno-unused-variable", "-Wno-unknown-pragmas", "-Wno-missing-braces",
             "-Werror=implicit-function-declaration", "-Werror=incompatible-pointer-types",
             "-Werror=int-conversion"]
    output = ROOT / "build/native-check"
    output.mkdir(parents=True, exist_ok=True)
    if args.oot_conversion:
        flags += ["-I" + str(declaration_include(engine, output))]
    if native:
        flags += ["-EB", "-G0", "-march=vr4300", "-mfix4300", "-mabi=32", "-mno-abicalls", "-fno-PIC", "-c"]
    else:
        flags += ["-m32", "-fsyntax-only"]
    if args.oot_conversion:
        sources = ["src/code/poke_core.c", "src/code/poke_save.c", "src/code/poke_oot.c",
                   "src/code/poke_stadium_asset.c",
                   "src/code/poke_pallet_scene_header.c",
                   "src/code/poke_pallet_scene.c",
                   "src/code/poke_pallet_room_header.c",
                   "src/code/poke_pallet_room.c",
                   "src/code/poke_pallet_unused_room_1.c",
                   "src/code/poke_pallet_unused_room_2.c",
                   "src/code/title_setup.c", "src/code/z_play.c",
                   "src/code/z_camera.c", "src/code/z_player_lib.c",
                   "src/code/poke_intro.c", "src/code/poke_world.c",
                   "src/code/poke_red_actor.c", "src/code/poke_red_mesh.c"]
        for name in ORDER[1:]:
            stem="src/code/poke_"+ROOMS[name]["segment"]
            sources.extend(stem+suffix+".c" for suffix in
                           ("_scene_header", "_scene", "_room_header", "_room"))
    else:
        sources = ["src/code/poke_core.c", "src/code/poke_save.c", "src/code/poke_state.c",
                   "src/code/title_setup.c", "src/code/z_game_dlftbls.c", "src/code/graph.c"]
    for source in sources:
        command = [compiler, *flags, source]
        if native:
            command += ["-o", str(output / (Path(source).stem + ".o"))]
        subprocess.run(command, cwd=engine, check=True)
    print("MIPS objects compiled successfully against pinned HackerOoT headers." if native else
          "Host 32-bit syntax check passed against pinned HackerOoT headers. MIPS code generation NOT tested.")
    print("No ROM linked. No emulator or hardware execution claimed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Native check failed: {exc}")
