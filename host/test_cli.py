#!/usr/bin/env python3
"""Exercise the executable frontend and filesystem persistence without a ROM."""

from pathlib import Path
import re
import subprocess
import sys
import tempfile


def run(binary: Path, save: Path, commands: str, *args: str):
    return subprocess.run(
        [str(binary), "--no-clear", "--seed", "7", "--save", str(save), *args],
        input=commands,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 host/test_cli.py PATH_TO_EXECUTABLE")
    binary = Path(sys.argv[1]).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="poke-cli-") as directory:
        save = Path(directory) / "journey.sav"

        # Initial location is one step south-east of Oak. Select Bulbasaur.
        result = run(binary, save, "w\nj\n1\nsave\nq\n")
        assert result.returncode == 0, result.stderr
        assert "Bulbasaur" in result.stdout, result.stdout
        assert "Progress saved." in result.stdout, result.stdout
        assert save.is_file() and save.stat().st_size == 256
        first = save.read_bytes()
        assert not list(save.parent.glob("*.tmp.*"))

        result = run(binary, save, "q\n")
        assert result.returncode == 0, result.stderr
        assert "Existing progress loaded." in result.stdout, result.stdout
        assert "Bulbasaur" in result.stdout
        assert save.read_bytes() == first, "Quitting must not rewrite progress"

        # Files with a good payload and extra bytes must still be rejected.
        save.write_bytes(first + b"unexpected trailing data")
        damaged = save.read_bytes()
        result = run(binary, save, "w\nj\n1\nsave\nload\nq\n")
        assert result.returncode == 0, result.stderr
        assert "Existing save is invalid" in result.stdout, result.stdout
        assert "Current game unchanged" in result.stdout, result.stdout
        assert save.read_bytes() == damaged, "Invalid input file was overwritten"
        assert not list(save.parent.glob("*.tmp.*"))

        result = run(binary, save, "", "--seed", "-1")
        assert result.returncode == 2

        result = run(binary, save, "", "--help")
        assert result.returncode == 0
        assert "same C rules" in result.stdout
        assert save.read_bytes() == damaged

        # Real traversal, not a direct encounter/test hook: leave Oak, enter grass,
        # weaken Pidgey, catch it, return via the path, heal and select it as lead.
        journey_save = Path(directory) / "full-journey.sav"
        commands = (
            ["w", "j", "1"]
            + ["w"] * 6
            + ["a"]
            + ["w"] * 5
            + ["1", "1", "2", "1", "2", "1"]
            + ["d"]
            + ["s"] * 12
            + ["d"] * 3
            + ["j", "p", "1", "2", "save", "q"]
        )
        result = run(binary, journey_save, "\n".join(commands) + "\n", "--seed", "1")
        assert result.returncode == 0, result.stderr
        assert "A wild Pidgey appeared!" in result.stdout
        assert "Bulbasaur used Tackle" in result.stdout
        assert "It broke free!" in result.stdout
        assert "Caught Pidgey!" in result.stdout
        assert "HP and PP restored." in result.stdout
        assert "Go, Pidgey!" in result.stdout
        assert "Progress saved." in result.stdout
        assert journey_save.stat().st_size == 256
        result = run(binary, journey_save, "q\n")
        assert result.returncode == 0, result.stderr
        assert "Existing progress loaded." in result.stdout
        assert "Caught 1" in result.stdout
        assert re.search(r"\* 2\. Pidgey\s+Lv2 HP 13/13", result.stdout), result.stdout

    print("host CLI: exploration/battle/capture/heal/party/save/restart and invalid-file preservation passed")


if __name__ == "__main__":
    main()
