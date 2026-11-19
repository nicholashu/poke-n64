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
from bootstrap import DEFAULT_ENGINE, ROOT, install


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--require-mips", action="store_true")
    args = parser.parse_args()
    engine = args.engine.resolve()
    install(engine)
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
             "-Wall", "-Wextra", "-Wno-unused-parameter", "-Wno-unused-variable", "-Wno-unknown-pragmas",
             "-Werror=implicit-function-declaration", "-Werror=incompatible-pointer-types",
             "-Werror=int-conversion"]
    output = ROOT / "build/native-check"
    output.mkdir(parents=True, exist_ok=True)
    if native:
        flags += ["-EB", "-G0", "-march=vr4300", "-mfix4300", "-mabi=32", "-mno-abicalls", "-fno-PIC", "-c"]
    else:
        flags += ["-m32", "-fsyntax-only"]
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
