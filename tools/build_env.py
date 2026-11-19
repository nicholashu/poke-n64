"""Read-only native build preflight for the pinned HackerOoT toolchain.

This checks executables on PATH before engine installation or ROM copying. It
does not install anything and does not use MIPS_CC, which belongs to the separate
object-compilation checker rather than HackerOoT's actual build system.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys


# Keep this order identical to the pinned engine's .make_hackeroot.mk. That file
# chooses a prefix by its linker alone, even if another prefix is more complete.
MIPS_PREFIXES = (
    "mips-n64-",
    "mips64-",
    "mips-linux-gnu-",
    "mips64-linux-gnu-",
    "mips-",
    "mips64-elf-",
)
MIPS_TOOLS = ("gcc", "as", "ld", "objcopy", "objdump", "nm", "strip")

GUIDANCE = (
    "Run make rom-docker for the managed Linux build with Docker running. "
    "For a native build, install GNU Make 4 or newer (brew install make provides "
    "gmake on macOS) and a complete big-endian MIPS GCC/binutils toolchain on PATH. "
    "A host C compiler alone cannot build the N64 ROM."
)


def _gnu_make() -> str:
    rejected = []
    for name in ("gmake", "make"):
        executable = shutil.which(name)
        if executable is None:
            continue
        try:
            result = subprocess.run(
                [executable, "--version"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            rejected.append(f"{executable}: could not inspect version ({exc})")
            continue
        match = re.search(r"^GNU Make\s+(\d+)(?:\.(\d+))?", result.stdout or "", re.MULTILINE)
        if result.returncode == 0 and match is not None and int(match.group(1)) >= 4:
            return executable
        if result.returncode != 0:
            rejected.append(f"{executable}: --version exited with status {result.returncode}")
        elif match is None:
            rejected.append(f"{executable}: not recognized as GNU Make")
        else:
            rejected.append(f"{executable}: GNU Make {match.group(1)}.{match.group(2) or '0'} is too old")
    detail = "; ".join(rejected) if rejected else "Neither gmake nor make is executable on PATH"
    raise RuntimeError(f"GNU Make 4 or newer is required. {detail}. {GUIDANCE}")


def _mips_toolchain() -> None:
    prefix = next((p for p in MIPS_PREFIXES if shutil.which(p + "ld") is not None), None)
    if prefix is None:
        linkers = ", ".join(p + "ld" for p in MIPS_PREFIXES)
        raise RuntimeError(
            "No HackerOoT-compatible MIPS linker was found on PATH. "
            f"Expected one of: {linkers}. {GUIDANCE}"
        )
    missing = [prefix + name for name in MIPS_TOOLS if shutil.which(prefix + name) is None]
    if missing:
        raise RuntimeError(
            f"HackerOoT selects the {prefix} toolchain because {prefix}ld is on PATH, "
            f"but required tools are missing: {', '.join(missing)}. "
            "Complete that toolchain or adjust PATH so the first detected prefix is complete. "
            f"A lower-priority toolchain will not override this selection. {GUIDANCE}"
        )


def native_make() -> str:
    """Return a supported GNU make executable after read-only prerequisite checks.

    Raises RuntimeError with an actionable native/Docker alternative if the host
    cannot run the project's supported native build. Run before any build writes.
    """
    executable = _gnu_make()
    _mips_toolchain()
    return executable


def main() -> int:
    try:
        executable = native_make()
    except RuntimeError as exc:
        print(f"Native build preflight failed: {exc}", file=sys.stderr)
        return 1
    print(f"GNU Make and MIPS toolchain preflight passed.\nSelected Make: {executable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
