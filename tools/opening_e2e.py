#!/usr/bin/env python3
"""Play the complete opening in a fresh ParaLLEl N64 session on macOS.

Only normal controller input drives gameplay. A CRC-protected, opt-in pixel
panel reports real ROM state; screenshots never write RAM or skip story flags.
Offline checks: python3 tools/opening_e2e.py --check-only
Live:          python3 tools/opening_e2e.py --starter bulbasaur
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import zlib

from kanto_layout import CELL, ORDER, ROOMS, validate, walkable
import play_oot
from retroarch_e2e import ROOT, RUN_ROOT, Runner

STARTERS = {"bulbasaur": (1, 4, 8), "charmander": (4, 7, 6), "squirtle": (7, 1, 7)}
# Stable PokeIntroRoom/PokeIntroStage and PokeMode IDs from the C protocol.
PALLET, BEDROOM, HOME, BLUE_HOUSE, LAB = range(5)
WAKE, EXPLORE, OAK_WARNING, ESCORT, LAB_WELCOME, CHOOSE, CHOSEN, CHALLENGE, BATTLE, AFTER_BATTLE, COMPLETE = range(11)
TALK_NONE, TALK_WAKE, TALK_WARNING, TALK_WELCOME, TALK_BALL, TALK_CHOSEN, TALK_CHALLENGE, TALK_RESULT = range(8)
KEYS = {"up": 34, "left": 38, "down": 40, "right": 37, "a": 49, "b": 56}


class TelemetryError(ValueError):
    pass


@dataclass(frozen=True)
class State:
    room: int
    stage: int
    talk: int
    starter: int
    rival: int
    mode: int
    result: int
    hp: int
    enemy_hp: int
    max_hp: int
    enemy_max_hp: int
    x: float  # Original movement-cell coordinates, centers at n + 0.5.
    z: float
    frame: int
    cursor: int
    trainer: bool
    turns: int
    locked: bool
    warp: bool
    outcome: int
    facing: int  # North 0, east 1, south 2, west 3.
    transition: bool

    @property
    def tile(self) -> tuple[int, int]:
        return math.floor(self.x), math.floor(self.z)


def decode_packet(packet: bytes) -> State:
    if len(packet) != 32 or packet[:5] != b"PK64\x01":
        raise TelemetryError("Missing PK64 v1 telemetry header")
    if zlib.crc32(packet[:28]) != int.from_bytes(packet[28:], "big"):
        raise TelemetryError("Telemetry CRC mismatch; frame is unreadable")
    if packet[5] >= len(ORDER) or packet[6] > COMPLETE or packet[10] > 6:
        raise TelemetryError("Telemetry contains invalid room/stage/mode")
    return State(*packet[5:16],
                 int.from_bytes(packet[16:18], "big") / (CELL * 4),
                 int.from_bytes(packet[18:20], "big") / (CELL * 4),
                 int.from_bytes(packet[20:22], "big"), packet[22],
                 bool(packet[23]), packet[24], bool(packet[25]), bool(packet[26]&1), packet[27], (packet[26]>>1)&3, bool(packet[26]&8))


def decode_image(path: Path) -> State:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Install Pillow first: python3 -m pip install Pillow") from exc
    with Image.open(path) as source:
        width, height = source.size
        if width < 320 or height < 240 or width * 3 != height * 4:
            raise TelemetryError(f"Expected raw 4:3 N64 screenshot, got {width}x{height}")
        img = source.convert("RGB").resize((320, 240), Image.Resampling.NEAREST)
        r, g, b = img.getpixel((247, 5))
        if min(g, b) < 130 or max(g, b) - r < 80:
            raise TelemetryError("Diagnostic panel is not visible")
        packet = bytearray(32)
        for bit in range(256):
            x, y = 248 + bit % 16 * 4, 6 + bit // 16 * 4
            samples = [sum(img.getpixel((x + dx, y + dy))) / 3
                       for dx in (1, 2) for dy in (1, 2)]
            light = sum(samples) / 4
            if 90 < light < 160:
                raise TelemetryError(f"Ambiguous telemetry pixel at bit {bit}")
            if light >= 160:
                packet[bit // 8] |= 1 << (7 - bit % 8)
        return decode_packet(bytes(packet))


def world_view_visible(path: Path) -> bool:
    """Reject a blank world even when HUD/telemetry still render correctly.

    This is a basic rendering check, not visual approval of the map or model.
    The crop excludes both HUD panels and the diagnostic grid.
    """
    from PIL import Image, ImageStat
    with Image.open(path) as source:
        img=source.convert("RGB").resize((320,240),Image.Resampling.NEAREST)
        world=img.crop((16,76,240,126))
        spread=max(high-low for low,high in world.getextrema())
        return spread>=35 and max(ImageStat.Stat(world).stddev)>=4.5


def occupied(room: int, stage: int) -> set[tuple[int, int]]:
    if room == HOME:
        return {(5, 4)}
    if room == BLUE_HOUSE:
        return {(2, 3)}
    if room == PALLET:
        return {(3, 8), (11, 14)}
    if room == LAB:
        cells = {(1, 9), (2, 10), (8, 10)}
        if stage >= CHOOSE:
            cells.add((5, 2))
        if stage < COMPLETE:
            cells.add((4, 3))
        return cells
    return set()


def route(room: int, start: tuple[int, int], goal: tuple[int, int], stage: int) -> list[tuple[int, int]]:
    """Find a cardinal route, avoiding NPCs and every unintended doorway."""
    name = ORDER[room]
    if goal in occupied(room, stage):
        raise ValueError(f"NPC occupies target in {name}: {goal}")
    blocked = occupied(room, stage) | {tuple(w["at"]) for w in ROOMS[name]["warps"]}
    blocked.discard(goal)
    blocked.discard(start)
    if not walkable(name, *start) or not walkable(name, *goal):
        raise ValueError(f"Blocked route endpoint in {name}: {start} -> {goal}")
    queue = deque([start])
    previous = {start: None}
    while queue:
        here = queue.popleft()
        if here == goal:
            result = []
            while here != start:
                result.append(here)
                here = previous[here]
            return list(reversed(result))
        for dx, dz in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            cell = here[0] + dx, here[1] + dz
            if cell not in previous and cell not in blocked and walkable(name, *cell):
                previous[cell] = here
                queue.append(cell)
    raise ValueError(f"No controller route in {name}: {start} -> {goal}")


def direction(state: State, target: tuple[int, int]) -> tuple[str | None, float]:
    dx, dz = target[0] + 0.5 - state.x, target[1] + 0.5 - state.z
    if max(abs(dx), abs(dz)) <= 0.13:
        return None, 0
    if abs(dx) > abs(dz):
        return ("right" if dx > 0 else "left"), abs(dx)
    return ("down" if dz > 0 else "up"), abs(dz)


def observed_damage(initial: State, current: State) -> bool:
    # finish_battle clears the enemy allocation. Its terminal zero HP is not
    # evidence of an observed attack; require a live trainer-battle sample.
    return (current.stage == BATTLE and current.trainer and
            current.enemy_max_hp == initial.enemy_max_hp > 0 and
            current.max_hp == initial.max_hp > 0 and
            (current.hp < initial.hp or current.enemy_hp < initial.enemy_hp))


class OpeningRunner(Runner):
    def __init__(self, rom: Path, root: Path, starter: str):
        super().__init__({"name": f"Complete Pallet opening: {starter}",
                          "steps": [{"action": "wait", "seconds": 0}]}, rom, root)
        self.starter_name = starter
        self.starter, self.rival, self.ball_x = STARTERS[starter]
        self.trace: list[dict] = []
        self.last_state: State | None = None
        self.last_advance = time.monotonic()
        self.sequence = 0
        self.key_helper = self.session / "retroarch-keys"
        self.checkpoint = "startup"
        self.damage_seen = False
        self.turns_seen = 0

    def config_overlay(self, command_port: int, pad_port: int) -> str:
        # The bindings live ONLY in this disposable session. Mapping both
        # shoulder variants covers the core's standard and independent-C maps;
        # the extra C buttons are ignored by the ROM's telemetry chord.
        bindings = {
            "input_player1_up": "i", "input_player1_left": "j",
            "input_player1_down": "k", "input_player1_right": "l",
            "input_player1_b": "space", "input_player1_y": "lshift",
            "input_player1_select": "e", "input_player1_l": "e",
            "input_player1_r": "r", "input_player1_r2": "r",
            "input_player1_l2": "tab", "input_player1_start": "enter",
            "input_player1_analog_dpad_mode": "0",
            # Require an unused modifier for global emulator hotkeys. In
            # particular, Tab must be Z, not RetroArch fast-forward.
            "input_enable_hotkey": "f12",
            "input_remap_binds_enable": "false",
        }
        return super().config_overlay(command_port, pad_port) + "".join(
            f"{k} = {play_oot.quote_config(v)}\n" for k, v in bindings.items())

    def keys(self, codes: list[int], seconds: float = 0.12) -> None:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Test-owned emulator exited; inspect process.log")
        subprocess.run([str(self.key_helper), "hold", str(self.process.pid), str(seconds),
                        *(str(code) for code in codes)], timeout=seconds + 5, check=True)
        time.sleep(0.16)  # Allow the native release edge and deceleration.

    def tap(self, name: str = "a") -> None:
        self.keys([KEYS[name]])

    def face(self, key: str) -> None:
        desired={"up":0,"right":1,"down":2,"left":3}[key]
        for _ in range(15):
            state=self.observe()
            if state.facing==desired:
                return
            if state.locked or state.transition:
                raise AssertionError(f"Cannot face object while input is locked: {state}")
            self.keys([KEYS[key]], .10)
        raise AssertionError(f"Red did not face {key}; last state: {self.last_state}")

    def observe(self, *, timeout: float = 8) -> State:
        deadline = time.monotonic() + timeout
        last_error = "no capture"
        while time.monotonic() < deadline:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError("Emulator exited while observing game state")
            self.sequence += 1
            label = f"state-{self.sequence:05}"
            path = self.capture(label)
            try:
                state = decode_image(path)
            except TelemetryError as exc:
                last_error = str(exc)
                time.sleep(0.12)
                continue
            if self.last_state is None or state.frame != self.last_state.frame:
                self.last_advance = time.monotonic()
            elif time.monotonic() - self.last_advance > 6:
                raise AssertionError("ROM frame counter stopped advancing")
            self.last_state = state
            self.trace.append({"capture": label, "checkpoint": self.checkpoint, **asdict(state)})
            return state
        raise AssertionError(f"Cannot read ROM state: {last_error}")

    def wait_for(self, label: str, predicate, timeout: float = 20) -> State:
        self.checkpoint = label
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.observe()
            if not state.transition and predicate(state) and world_view_visible(self.images[f"state-{self.sequence:05}"]):
                self.steps.append({"action": label, "passed": True, "state": asdict(state)})
                self.images[label] = self.images[f"state-{self.sequence:05}"]
                print(f"PASS {label}: {ORDER[state.room]}, stage={state.stage}, frame={state.frame}", flush=True)
                return state
            time.sleep(0.15)
        raise AssertionError(f"Timed out at {label} (state mismatch or blank world view); last state: {self.last_state}")

    def walk_to(self, room: int, target: tuple[int, int], *, expect_room: int | None = None,
                expect_stage: int | None = None) -> State:
        self.checkpoint = f"walk-{ORDER[room]}-{target[0]}-{target[1]}"
        state = self.observe()
        deadline = time.monotonic() + 150
        stationary = 0
        while time.monotonic() < deadline:
            if expect_room is not None and state.room == expect_room:
                if not state.warp and not state.locked and not state.transition:
                    return state
                state = self.observe()
                continue
            if expect_stage is not None and state.stage == expect_stage:
                return state
            if state.room != room:
                raise AssertionError(f"Unexpected room while walking: {ORDER[state.room]}")
            if state.locked or state.warp or state.transition:
                if expect_room is not None or expect_stage is not None:
                    state = self.observe()
                    continue
                raise AssertionError(f"Unexpected dialogue/lock while walking: {state}")
            path = route(room, state.tile, target, state.stage)
            # First center the current cell when turning corners. This keeps
            # the player's collision cylinder away from neighboring walls.
            waypoint = path[0] if path else target
            if path:
                dx, dz = waypoint[0] - state.tile[0], waypoint[1] - state.tile[1]
                if (dx and abs(state.z - (state.tile[1] + .5)) > .13) or (
                    dz and abs(state.x - (state.tile[0] + .5)) > .13
                ):
                    waypoint = state.tile
            key, distance = direction(state, waypoint)
            if key is None:
                if state.tile == target:
                    if expect_room is None and expect_stage is None:
                        return state
                    state = self.observe()
                    continue
                state = self.observe()
                continue
            previous = state
            # Bounded closed-loop pulses, recalculated from actual position.
            # With native D-pad walking, <=0.45s stays below one 80-unit cell.
            self.keys([KEYS[key]], min(.45, max(.06, distance * .48)))
            state = self.observe()
            if state.room == previous.room and math.hypot(state.x-previous.x, state.z-previous.z) < .012:
                stationary += 1
                if stationary >= 10:
                    raise AssertionError(f"Controller made no movement toward {target}: {state}")
            else:
                stationary = 0
        raise AssertionError(f"Navigation timed out in {ORDER[room]} toward {target}: {state}")

    def play_opening(self) -> None:
        self.start()
        subprocess.run(["swiftc", "-O", str(ROOT / "tools/retroarch_keys.swift"),
                        "-o", str(self.key_helper)], timeout=60, check=True)
        # A cold core can still be booting after GET_STATUS says PLAYING.
        # Retry the chord only while no readable panel has appeared.
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            self.keys([14, 15, 48, 36], .2)  # L+R+Z+START
            try:
                self.observe(timeout=4)
                break
            except AssertionError as exc:
                if not str(exc).startswith("Cannot read ROM state:"):
                    raise
        else:
            raise AssertionError("Boot never exposed the PK64 observer; inspect screenshots and input permissions")
        self.wait_for("01-bedroom-wake", lambda s: s.room == BEDROOM and s.stage == WAKE)
        self.tap()
        self.wait_for("02-out-of-bed", lambda s: s.stage == EXPLORE and not s.locked)
        # Optional PC Potion, with no effect on the scripted battle strategy.
        self.walk_to(BEDROOM, (0, 2))
        self.face("up")
        self.tap()
        self.wait_for("03-pc-potion", lambda s: s.talk == 10)
        self.tap()
        self.walk_to(BEDROOM, (7, 1), expect_room=HOME)
        self.wait_for("04-downstairs", lambda s: s.room == HOME and not s.locked)
        self.walk_to(HOME, (5, 3))
        self.face("down")
        self.tap()
        self.wait_for("05-mom", lambda s: s.talk == 8)
        self.tap()
        self.walk_to(HOME, (3, 7), expect_room=PALLET)
        self.wait_for("06-pallet-town", lambda s: s.room == PALLET and not s.locked)
        # Exercise the other enterable home before the story interception.
        self.walk_to(PALLET, (13, 5), expect_room=BLUE_HOUSE)
        self.wait_for("07-blue-house", lambda s: s.room == BLUE_HOUSE and not s.locked)
        self.walk_to(BLUE_HOUSE, (2, 4))
        self.face("up")
        self.tap()
        self.wait_for("08-daisy", lambda s: s.talk == 15)
        self.tap()
        self.walk_to(BLUE_HOUSE, (3, 7), expect_room=PALLET)
        self.walk_to(PALLET, (10, 1), expect_stage=OAK_WARNING)
        self.wait_for("09-oak-warning", lambda s: s.stage == OAK_WARNING and s.talk == TALK_WARNING)
        self.tap()
        self.wait_for("10-oak-escort", lambda s: s.stage == ESCORT, timeout=8)
        self.wait_for("11-lab-welcome", lambda s: s.room == LAB and s.stage == LAB_WELCOME and s.talk == TALK_WELCOME, timeout=80)
        self.tap()
        self.wait_for("12-starter-choice", lambda s: s.stage == CHOOSE and not s.locked)
        self.walk_to(LAB, (self.ball_x, 4))
        self.face("up")
        self.tap()
        self.wait_for("13-ball-confirm", lambda s: s.talk == TALK_BALL and s.starter == 0)
        self.tap("b")
        self.wait_for("14-choice-cancelled", lambda s: s.stage == CHOOSE and s.starter == 0 and not s.locked)
        self.tap()
        self.wait_for("15-ball-reopened", lambda s: s.talk == TALK_BALL)
        self.tap()
        self.wait_for("16-starter-and-rival", lambda s: s.stage == CHOSEN and s.starter == self.starter and s.rival == self.rival)
        self.tap()
        self.walk_to(LAB, (4, 6), expect_stage=CHALLENGE)
        self.wait_for("17-rival-challenge", lambda s: s.stage == CHALLENGE and s.talk == TALK_CHALLENGE)
        self.tap()
        state = self.wait_for("18-trainer-battle", lambda s: s.stage == BATTLE and s.trainer and s.mode == 2)
        initial_state = state
        for _ in range(250):
            if state.stage == AFTER_BATTLE:
                break
            if state.stage != BATTLE or state.mode not in (2, 3) or not state.trainer:
                raise AssertionError(f"Unexpected battle state: {state}")
            if state.cursor != 0:
                raise AssertionError(f"First attack cursor moved unexpectedly: {state.cursor}")
            self.tap()  # Battle menu -> Fight -> first damaging move.
            state = self.observe()
            self.turns_seen = max(self.turns_seen, state.turns)
            self.damage_seen |= observed_damage(initial_state, state)
        else:
            raise AssertionError("Rival battle did not finish after 250 button presses")
        if not self.damage_seen or not self.turns_seen or state.outcome not in (1, 2):
            raise AssertionError("Battle completion lacked observed damage, turns or win/loss outcome")
        self.wait_for("19-rival-result", lambda s: s.stage == AFTER_BATTLE and s.talk == TALK_RESULT)
        self.tap()
        self.wait_for("20-opening-complete", lambda s: s.stage == COMPLETE and s.hp == s.max_hp and s.max_hp > 0 and not s.locked)
        self.walk_to(LAB, (4, 11), expect_room=PALLET)
        self.wait_for("21-return-to-pallet", lambda s: s.room == PALLET and s.stage == COMPLETE and s.starter == self.starter and not s.locked)

    def run(self) -> bool:
        try:
            self.play_opening()
            self.status = "passed"
        except (Exception, KeyboardInterrupt) as exc:
            self.status = "failed"
            self.steps.append({"action": self.checkpoint, "passed": False, "detail": str(exc)})
            print(f"FAIL {self.checkpoint}: {exc}", file=sys.stderr, flush=True)
            if self.session.exists():
                (self.session / "failure.txt").write_text(str(exc) + "\n")
        finally:
            # Swift's hold releases each key before returning; also release
            # everything explicitly if a timeout/interruption killed the helper.
            if self.key_helper.exists() and self.process is not None and self.process.poll() is None:
                try:
                    subprocess.run([str(self.key_helper), "up", str(self.process.pid),
                                    *(str(k) for k in (*KEYS.values(), 14, 15, 48, 36))], timeout=5, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self.close()
            if self.session.exists():
                report = {"scenario": self.scenario["name"], "rom": str(self.rom),
                          "status": self.status, "starter": self.starter_name,
                          "damage_observed": self.damage_seen, "battle_turns_observed": self.turns_seen,
                          "checkpoints": self.steps,
                          "screenshots": {k: str(v) for k, v in self.images.items() if not k.startswith("state-")}}
                (self.session / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                (self.session / "state-trace.json").write_text(json.dumps(self.trace, indent=2) + "\n")
                print("Evidence saved:", self.session, flush=True)
        return self.status == "passed"


def check_routes() -> None:
    validate()
    cases = [(BEDROOM, (1, 6), (0, 2), EXPLORE), (BEDROOM, (0, 2), (7, 1), EXPLORE),
             (HOME, (6, 1), (5, 3), EXPLORE), (HOME, (5, 3), (3, 7), EXPLORE),
             (PALLET, (5, 6), (13, 5), EXPLORE), (BLUE_HOUSE, (3, 6), (2, 4), EXPLORE),
             (BLUE_HOUSE, (2, 4), (3, 7), EXPLORE), (PALLET, (13, 6), (10, 1), EXPLORE),
             (LAB, (4, 6), (4, 11), COMPLETE)]
    for _, _, x in STARTERS.values():
        cases += [(LAB, (5, 3), (x, 4), CHOOSE), (LAB, (x, 4), (4, 6), CHOSEN)]
    for room, start, goal, stage in cases:
        route(room, start, goal, stage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=play_oot.ROM_DEFAULT)
    parser.add_argument("--runs-dir", type=Path, default=RUN_ROOT)
    parser.add_argument("--starter", choices=STARTERS, default="bulbasaur")
    parser.add_argument("--all-starters", action="store_true", help="three separate fresh emulator runs")
    parser.add_argument("--check-only", action="store_true", help="validate map routes without an emulator")
    args = parser.parse_args()
    check_routes()
    if args.check_only:
        print("Opening routes valid for all five areas and all three starters. No ROM was run.")
        return 0
    for starter in STARTERS if args.all_starters else (args.starter,):
        if not OpeningRunner(args.rom, args.runs_dir, starter).run():
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
