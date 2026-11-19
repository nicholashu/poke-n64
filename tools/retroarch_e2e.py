#!/usr/bin/env python3
"""Scripted native N64 end-to-end tests using RetroArch's local UDP interfaces.

Run locally on macOS with the ParaLLEl Launcher Edition installed:
    python3 tools/retroarch_e2e.py tests/rom_scenarios/pallet_smoke.json

No game assets, ROMs, screenshots or user saves are checked into Git.
Requires Pillow only for pixel assertions; macOS Vision provides optional OCR.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import time
import uuid

import play_oot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = ROOT / "tests/rom_scenarios/pallet_smoke.json"
RUN_ROOT = ROOT / "build/emulator-tests"

# From libretro's RETRO_DEVICE_ID_JOYPAD_* enumerations, not keyboard scancodes.
RETROPAD = {
    "b": 0, "y": 1, "select": 2, "start": 3,
    "up": 4, "down": 5, "left": 6, "right": 7,
    "a": 8, "x": 9, "l": 10, "r": 11,
    "l2": 12, "r2": 13, "l3": 14, "r3": 15,
}
# Default Parallel-N64 mapping: N64 A is RetroPad B; N64 B is RetroPad Y.
# Use raw retropad names for C buttons, whose mapping depends on core options.
BUTTON_ALIASES = {"n64_a": "b", "n64_b": "y", "n64_z": "l2",
                  "n64_l": "l", "n64_r": "r", "n64_start": "start"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
FAULT_PHRASES = (
    "TLB EXCEPTION", "ADDRESS ERROR", "BUS ERROR",
    "FLOATING POINT EXCEPTION", "UNHANDLED EXCEPTION",
)
ACTIONS = frozenset({
    "wait", "tap", "press", "release", "release_all", "stick", "screenshot",
    "assert_visible", "assert_changed", "assert_movement", "assert_text", "assert_no_fault",
    "assert_status", "pause", "resume", "frames", "key_hold",
})


def button_id(name: str) -> int:
    if not isinstance(name, str):
        raise ValueError("button name must be text")
    canonical = BUTTON_ALIASES.get(name.lower(), name.lower())
    if canonical not in RETROPAD:
        raise ValueError(f"Unknown RetroPad button {name!r}: {sorted(RETROPAD)}")
    return RETROPAD[canonical]


def encode_pad(player: int, device: int, index: int, item_id: int, state: int) -> bytes:
    """Exact 20-byte RetroArch remote_message struct on macOS (little endian)."""
    if not 0 <= player < 4 or device not in (1, 2):
        raise ValueError("Invalid player or device")
    if not -32768 <= state <= 32767:
        raise ValueError("RetroPad state outside signed int16")
    return struct.pack("<iiiihxx", player, device, index, item_id, state)


def release_all_packet() -> bytes:
    """The network receiver clears all latched state on a short datagram."""
    return b"\x00"


def choose_ports() -> tuple[int, int]:
    """Pick separate unused high UDP ports, never RetroArch's global defaults."""
    sockets = []
    try:
        for _ in range(2):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return sockets[0].getsockname()[1], sockets[1].getsockname()[1]
    finally:
        for sock in sockets:
            sock.close()


def validate_scenario(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Scenario must be a JSON object")
    name = raw.get("name")
    steps = raw.get("steps")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Scenario must provide a name")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        raise ValueError("Scenario requires 1 to 100 steps")
    known_images: set[str] = set()
    for n, step in enumerate(steps, 1):
        if not isinstance(step, dict) or step.get("action") not in ACTIONS:
            raise ValueError(f"Step {n}: unrecognized action")
        action = step["action"]
        if action in ("tap", "press", "release"):
            names = step.get("buttons")
            if not isinstance(names, list) or not 1 <= len(names) <= 16:
                raise ValueError(f"Step {n}: buttons must be a nonempty array")
            for name in names:
                button_id(name)
        if action in ("wait", "tap", "stick"):
            duration = step.get("seconds", 0.2 if action == "tap" else None)
            if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 <= duration <= 90:
                raise ValueError(f"Step {n}: seconds must be between 0 and 90")
        if action == "stick":
            if step.get("stick") not in ("left", "right"):
                raise ValueError(f"Step {n}: stick must be left or right")
            for axis in ("x", "y"):
                value = step.get(axis)
                if type(value) is not int or not -32768 <= value <= 32767:
                    raise ValueError(f"Step {n}: invalid {axis} axis")
        if action == "key_hold":
            if type(step.get("keycode")) is not int or not 0 <= step["keycode"] <= 127:
                raise ValueError(f"Step {n}: key_hold requires macOS virtual keycode (0..127)")
            duration = step.get("seconds")
            if (not isinstance(duration, (int, float)) or isinstance(duration, bool)
                    or not 0 < duration <= 90):
                raise ValueError(f"Step {n}: key_hold seconds must be in (0,90]")
        if action == "frames":
            if type(step.get("count")) is not int or not 1 <= step["count"] <= 600:
                raise ValueError(f"Step {n}: count must be 1 to 600")
        if action == "screenshot":
            label = step.get("name")
            if not isinstance(label, str) or not SAFE_NAME.fullmatch(label) or label in known_images:
                raise ValueError(f"Step {n}: screenshot name must be unique and safe")
            known_images.add(label)
        if action in ("assert_visible", "assert_no_fault", "assert_text"):
            if step.get("image") not in known_images:
                raise ValueError(f"Step {n}: screenshot must be captured before assertion")
        if action == "assert_changed":
            if step.get("before") not in known_images or step.get("after") not in known_images:
                raise ValueError(f"Step {n}: both screenshots must exist before diff")
        if action == "assert_movement":
            if any(step.get(key) not in known_images for key in ("idle_before", "before", "after")):
                raise ValueError(f"Step {n}: three screenshots must exist before movement assertion")
            ratio = step.get("ratio", 1.8)
            threshold = step.get("min_difference", 8)
            if not isinstance(ratio, (int, float)) or ratio <= 1 or ratio > 10:
                raise ValueError(f"Step {n}: movement ratio must be between 1 and 10")
            if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 255:
                raise ValueError(f"Step {n}: movement min_difference outside 0-255")
        if action == "assert_text" and (
            not isinstance(step.get("contains"), str) or not step["contains"].strip()
        ):
            raise ValueError(f"Step {n}: assert_text requires nonempty contains")
    return raw


def network_overlay(save: Path, state: Path, shots: Path,
                    command_port: int, pad_port: int) -> str:
    # Keep the user's GPU, RSP, controller mappings and global config unchanged.
    values = {
        "network_cmd_enable": "true",
        "network_cmd_port": str(command_port),
        "network_remote_enable": "true",
        "network_remote_enable_user_p1": "true",
        "network_remote_base_port": str(pad_port),
        "screenshot_directory": str(shots),
        "screenshot_raw": "true",
        # Screenshot notifications persist for multiple frames and can make
        # an idle screenshot differ from the next screenshot, falsely
        # resembling gameplay movement.
        "notification_show_screenshot": "false",
        "notification_show_screenshot_flash": "0",
        # Terminal-driven automation must keep the emulation clock running
        # even when another macOS app owns keyboard focus.
        "pause_nonactive": "false",
    }
    return play_oot.session_overlay(save, state) + "".join(
        f"{key} = {play_oot.quote_config(value)}\n" for key, value in values.items()
    )


class Remote:
    """Network Commands (NCI) and latching Remote RetroPad over localhost UDP."""

    def __init__(self, command_port: int, pad_port: int):
        self.command_port = command_port
        self.pad_port = pad_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.30)
        self.pad_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self) -> None:
        self.sock.close()
        self.pad_sock.close()

    def command(self, message: str, *, reply: bool = False) -> str | None:
        if not re.fullmatch(r"[A-Za-z_0-9 \-/\.]+", message):
            raise ValueError("Invalid network command")
        # Drain earlier unsolicited responses before sending next query.
        self.sock.setblocking(False)
        try:
            while True:
                self.sock.recvfrom(8192)
        except BlockingIOError:
            pass
        finally:
            self.sock.setblocking(True)
            self.sock.settimeout(0.30)
        self.sock.sendto(message.encode("ascii"), ("127.0.0.1", self.command_port))
        if not reply:
            return None
        try:
            return self.sock.recvfrom(8192)[0].decode("utf-8", errors="replace").strip()
        except socket.timeout:
            return None

    def pad(self, buttons: list[str], pressed: bool) -> None:
        for name in buttons:
            self.pad_sock.sendto(
                encode_pad(0, 1, 0, button_id(name), int(pressed)),
                ("127.0.0.1", self.pad_port),
            )

    def stick(self, name: str, x: int, y: int) -> None:
        index = {"left": 0, "right": 1}[name]
        for axis, state in ((0, x), (1, y)):
            self.pad_sock.sendto(
                encode_pad(0, 2, index, axis, state),
                ("127.0.0.1", self.pad_port),
            )

    def release_all(self) -> None:
        self.pad_sock.sendto(release_all_packet(), ("127.0.0.1", self.pad_port))


def image_stats(path: Path) -> dict:
    try:
        from PIL import Image, ImageStat
    except ImportError as exc:
        raise RuntimeError("Pixel assertions require Pillow: python3 -m pip install Pillow") from exc
    with Image.open(path) as img:
        img = img.convert("RGB").resize((96, 72))
        channel_range = [high - low for low, high in img.getextrema()]
        means = ImageStat.Stat(img).mean
        return {
            "color_spread": round(max(channel_range), 2),
            "brightness": round(sum(means) / 3, 2),
        }


def image_difference(first: Path, second: Path) -> float:
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise RuntimeError("Image comparisons require Pillow: python3 -m pip install Pillow") from exc
    with Image.open(first) as a, Image.open(second) as b:
        a = a.convert("RGB").resize((160, 120))
        b = b.convert("RGB").resize((160, 120))
        return round(sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3, 3)


def recognize_text(path: Path) -> str:
    """Use built-in macOS Vision; do not guess text from a dark screenshot."""
    script = ROOT / "tools/retroarch_ocr.swift"
    result = subprocess.run(
        ["swift", str(script), str(path)], capture_output=True, text=True,
        timeout=45, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("macOS Vision OCR failed: " + result.stderr.strip()[-600:])
    return result.stdout


class Runner:
    def __init__(self, scenario: dict, rom: Path, root: Path):
        self.scenario = validate_scenario(scenario)
        self.rom = rom.expanduser().resolve()
        self.root = root.expanduser().resolve()
        self.session = self.root / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        self.remote: Remote | None = None
        self.process: subprocess.Popen | None = None
        self.log = None
        self.images: dict[str, Path] = {}
        self.steps: list[dict] = []
        self.status = "pending"

    def start(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("Live RetroArch E2E tests require macOS (offline tests run anywhere)")
        app = play_oot.RETROARCH_APP.resolve()
        core = play_oot.RETROARCH_CORE.resolve()
        config = play_oot.RETROARCH_CONFIG.resolve()
        play_oot.validate_inputs(self.rom, app, config, core)
        binary = app / "Contents/MacOS/RetroArch"
        play_oot.ensure_not_running(binary, self.rom)
        command_port, pad_port = choose_ports()
        self.session.mkdir(parents=True)
        for sub in ("saves", "states", "screenshots"):
            (self.session / sub).mkdir()
        overlay = self.session / "test-config.cfg"
        overlay.write_text(network_overlay(
            self.session / "saves", self.session / "states",
            self.session / "screenshots", command_port, pad_port,
        ), encoding="utf-8")
        self.remote = Remote(command_port, pad_port)
        argv = [
            str(binary), "-v", "--log-file=" + str(self.session / "retroarch.log"),
            "-c", str(config), "--appendconfig=" + str(overlay),
            "-L", str(core), "--no-patch", str(self.rom),
        ]
        self.log = (self.session / "process.log").open("w")
        print("Starting isolated ParaLLEl N64, session:", self.session, flush=True)
        self.process = subprocess.Popen(argv, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 35
        response = None
        unpause_attempted = False
        paused_checks = 0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"RetroArch exited during startup ({self.process.returncode}); inspect process.log")
            response = self.remote.command("GET_STATUS", reply=True)
            if response and response.startswith("GET_STATUS PLAYING"):
                break
            if response and response.startswith("GET_STATUS PAUSED"):
                paused_checks += 1
                if paused_checks >= 3 and not unpause_attempted:
                    # Some installations launch in the paused state even with
                    # pause_nonactive=false. Resume only after status proves
                    # it is actually paused, never blindly toggle on startup.
                    self.remote.command("PAUSE_TOGGLE")
                    unpause_attempted = True
            time.sleep(0.30)
        else:
            raise RuntimeError(f"RetroArch never reported PLAYING on isolated port {command_port}; last response: {response!r}")
        # Fail safe: never interact with a running emulator whose save path did
        # not resolve to the isolated test directory.
        actual = self.remote.command("GET_CONFIG_PARAM savefile_directory", reply=True)
        if actual is None or str(self.session / "saves") not in actual:
            raise RuntimeError(f"Isolated SRAM directory not confirmed by RetroArch: {actual!r}")
        self.status = "running"
        print("Connected to live game:", response, flush=True)

    def capture(self, label: str) -> Path:
        assert self.remote is not None
        directory = self.session / "screenshots"
        existing = set(directory.iterdir())
        self.remote.command("SCREENSHOT")
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            for candidate in directory.iterdir():
                if candidate in existing or candidate.suffix.lower() != ".png":
                    continue
                size1 = candidate.stat().st_size
                if size1 > 80:
                    time.sleep(0.12)
                    if candidate.exists() and candidate.stat().st_size == size1:
                        path = directory / (label + ".png")
                        if candidate != path:
                            candidate.rename(path)
                        self.images[label] = path
                        return path
            time.sleep(0.10)
        raise RuntimeError("RetroArch did not write a PNG screenshot into the isolated directory")

    def step(self, item: dict) -> str:
        assert self.remote is not None
        action = item["action"]
        remote = self.remote
        if action == "wait":
            time.sleep(item["seconds"])
            return f"waited {item['seconds']}s"
        if action == "tap":
            remote.pad(item["buttons"], True)
            time.sleep(item.get("seconds", 0.2))
            remote.pad(item["buttons"], False)
            time.sleep(0.06)
            return f"tapped {item['buttons']}"
        if action == "press":
            remote.pad(item["buttons"], True)
            time.sleep(0.07)
            return f"pressed {item['buttons']}"
        if action == "release":
            remote.pad(item["buttons"], False)
            time.sleep(0.07)
            return f"released {item['buttons']}"
        if action == "release_all":
            remote.release_all()
            time.sleep(0.07)
            return "released all inputs"
        if action == "stick":
            remote.stick(item["stick"], item["x"], item["y"])
            time.sleep(item["seconds"])
            remote.stick(item["stick"], 0, 0)
            time.sleep(0.06)
            return f"moved {item['stick']} stick ({item['x']}, {item['y']})"
        if action == "key_hold":
            # The network Remote RetroPad analog path can be unreliable on
            # this ParaLLEl build. Post the keyboard key to the exact owned
            # emulator PID; leave global input bindings untouched.
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError("Test-owned RetroArch process is not running")
            helper = ROOT / "tools/retroarch_keys.swift"
            if not helper.is_file():
                raise RuntimeError(f"Missing keyboard input helper: {helper}")
            subprocess.run([
                "swift", str(helper), "hold", str(self.process.pid),
                str(item["seconds"]), str(item["keycode"]),
            ], timeout=item["seconds"] + 25, check=True)
            time.sleep(0.10)
            return f"held macOS keycode {item['keycode']} for {item['seconds']}s"
        if action == "screenshot":
            path = self.capture(item["name"])
            return f"captured {path.relative_to(self.session)}"
        if action == "assert_status":
            reply = remote.command("GET_STATUS", reply=True)
            if not reply or "PLAYING" not in reply:
                raise AssertionError(f"Game is not PLAYING: {reply!r}")
            return reply
        if action == "assert_visible":
            stats = image_stats(self.images[item["image"]])
            threshold = item.get("min_color_spread", 30)
            if stats["color_spread"] < threshold:
                raise AssertionError(f"Screen looks blank: spread {stats['color_spread']}, required {threshold}")
            return f"visible screen {stats}"
        if action == "assert_changed":
            difference = image_difference(self.images[item["before"]], self.images[item["after"]])
            threshold = item.get("min_difference", 1.5)
            if difference < threshold:
                raise AssertionError(f"Images did not change enough ({difference} < {threshold})")
            return f"screen changed {difference} average RGB units"
        if action == "assert_movement":
            # Distinguish camera/player movement from Bulbasaur idle animation,
            # changing lighting, or a title-card fade. Measure the latter first.
            idle = image_difference(self.images[item["idle_before"]], self.images[item["before"]])
            moving = image_difference(self.images[item["before"]], self.images[item["after"]])
            required = max(item.get("min_difference", 8), idle * item.get("ratio", 1.8))
            if moving < required:
                raise AssertionError(
                    f"No clear movement: moving difference {moving}, idle difference "
                    f"{idle}, required >={required:.2f}"
                )
            return f"movement confirmed: {moving} RGB units versus {idle} idle"
        if action in ("assert_no_fault", "assert_text"):
            visible = recognize_text(self.images[item["image"]])
            if action == "assert_text":
                if item["contains"].casefold() not in visible.casefold():
                    raise AssertionError(f"Text {item['contains']!r} not seen; OCR: {visible[:500]!r}")
                return f"text matched {item['contains']!r}"
            found = [text for text in FAULT_PHRASES if text.casefold() in visible.casefold()]
            if found:
                raise AssertionError("N64 exception screen detected: " + ", ".join(found))
            return "no recognized N64 fault text"
        if action in ("pause", "resume"):
            status = remote.command("GET_STATUS", reply=True) or ""
            paused = "PAUSED" in status
            if (action == "pause" and not paused) or (action == "resume" and paused):
                remote.command("PAUSE_TOGGLE")
                time.sleep(0.1)
            return action
        if action == "frames":
            status = remote.command("GET_STATUS", reply=True) or ""
            if "PAUSED" not in status:
                raise AssertionError("FRAMEADVANCE requires pause action first")
            for _ in range(item["count"]):
                remote.command("FRAMEADVANCE")
                time.sleep(0.025)
            return f"advanced {item['count']} emulated frames"
        raise ValueError(f"Unsupported action: {action}")

    def run(self) -> bool:
        try:
            self.start()
            for index, item in enumerate(self.scenario["steps"], 1):
                start = time.monotonic()
                label = f"{index:02} {item['action']}"
                try:
                    outcome = self.step(item)
                    self.steps.append({"step": index, "action": item["action"],
                                       "passed": True, "detail": outcome,
                                       "elapsed": round(time.monotonic()-start, 3)})
                    print("PASS", label, outcome, flush=True)
                except Exception as exc:
                    self.steps.append({"step": index, "action": item["action"],
                                       "passed": False, "detail": str(exc)})
                    raise
            self.status = "passed"
        except Exception as exc:
            self.status = "failed"
            print(f"FAIL {self.scenario['name']}: {exc}", file=sys.stderr, flush=True)
            if self.session.exists():
                (self.session / "failure.txt").write_text(str(exc) + "\n")
        finally:
            self.close()
            if self.session.exists():
                (self.session / "report.json").write_text(json.dumps({
                    "scenario": self.scenario["name"],
                    "rom": self.rom.name,
                    "status": self.status,
                    "steps": self.steps,
                    "screenshots": {key: str(value) for key, value in self.images.items()},
                }, indent=2) + "\n")
                print("Evidence saved:", self.session, flush=True)
        return self.status == "passed"

    def close(self) -> None:
        if self.remote is not None:
            try:
                self.remote.release_all()
                self.remote.command("QUIT")
            except OSError:
                pass
            self.remote.close()
        if self.process is not None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
        if self.log is not None:
            self.log.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path, nargs="?", default=DEFAULT_SCENARIO)
    parser.add_argument("--rom", type=Path, default=play_oot.ROM_DEFAULT)
    parser.add_argument("--runs-dir", type=Path, default=RUN_ROOT)
    parser.add_argument("--check-only", action="store_true",
                        help="validate scenario JSON without launching an emulator")
    args = parser.parse_args()
    try:
        scenario = validate_scenario(json.loads(args.scenario.read_text(encoding="utf-8")))
        if args.check_only:
            print(f"Valid scenario: {scenario['name']} ({len(scenario['steps'])} steps)")
            return 0
        return 0 if Runner(scenario, args.rom, args.runs_dir).run() else 1
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"E2E configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
