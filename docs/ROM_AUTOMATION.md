# Automated N64 gameplay tests

This harness drives the **real** OoT conversion ROM in the user's installed
ParaLLEl N64 (Parallel Launcher Edition), with controller inputs and screenshots.
It is not a simulated gameplay test or a static MIPS compiler check.

## Commands (macOS)

```sh
# Build and run normal unit tests, no ROM or emulator required.
make test

# Validate the scripted scenario without launching anything.
python3 tools/retroarch_e2e.py --check-only

# Launch the existing ROM, test boot and move Link with an analogue stick.
make test-rom

# Rebuild the ROM from the locally provided Zelda dump, then test it.
make rom-oot-e2e

# Choose a different scenario:
make test-rom ROM_SCENARIO=tests/rom_scenarios/pallet_smoke.json
```

The native test uses `build/poke-n64-oot.z64`, the local ParaLLEl Launcher
Edition core and the user's existing Vulkan / ParaLLEl RSP configuration.
Python 3 is required. **Pillow** is needed for pixel assertions (installed on
the development Mac; otherwise `python3 -m pip install Pillow`). Screenshot
text checks use the built-in **macOS Vision** framework through Swift, with no
network or cloud OCR.

## How it works

Each run creates a unique folder in `build/emulator-tests/`, including fresh
`saves/`, `states/`, `screenshots/`, a per-run `test-config.cfg`, process
and RetroArch logs and a machine-readable `report.json`. The harness:

1. Refuses to start if the same ROM is already running, so it won't terminate
   or hijack a game you're playing.
2. Starts the installed RetroArch executable **itself** (not the menu window)
   with the correct core, existing graphics settings, `--no-patch` and an
   isolated `--appendconfig`. It tracks that process for safe cleanup.
3. Allocates unique UDP ports for RetroArch's Network Control Interface
   and Remote RetroPad. Control requests and controller inputs go to
   `127.0.0.1` (never a hosted service).
4. Waits for a `GET_STATUS PLAYING` response and confirms the configured
   cartridge SRAM path is the fresh session directory.
5. Sends real latched RetroPad button and analog stick states. It can
   request native framebuffer PNG screenshots, assert pixel changes, check
   the displayed text or look for N64 fault overlays.
6. Releases all inputs and quits **only the RetroArch process it started**.
   It writes a pass/fail report even when a step fails.

Your normal `.srm` saves and savestates are neither opened nor deleted.
Graphics/RSP settings are left alone. All generated artifacts remain untracked
under `build/`.

Network Control commands (GET_STATUS, SCREENSHOT, PAUSE_TOGGLE, FRAMEADVANCE)
and Remote RetroPad input are separate, documented RetroArch UDP protocols.
Since Remote RetroPad messages persist until released, the harness always
sends an explicit release, including in exception cleanup.

## Scenario format

Scenarios are restricted JSON (no arbitrary Python, shell commands, paths
outside the run directory or arbitrary memory writes). Each step has an
`action`:

| Action | Example | Behaviour |
| --- | --- | --- |
| `wait` | `{"action":"wait","seconds":3}` | Wait for emulation |
| `tap` | `{"action":"tap","buttons":["n64_a"],"seconds":0.2}` | Button down, then up |
| `press` | `{"action":"press","buttons":["l","r"]}` | Latch multiple buttons down |
| `release` | `{"action":"release","buttons":["l","r"]}` | Release specified buttons |
| `release_all` | `{"action":"release_all"}` | Center axes, release every button |
| `stick` | `{"action":"stick","stick":"left","x":0,"y":-25000,"seconds":1.5}` | Move joystick (int16 X/Y) then center |
| `screenshot` | `{"action":"screenshot","name":"walk"}` | Save native screenshot in the run directory |
| `assert_visible` | `{"action":"assert_visible","image":"walk","min_color_spread":35}` | Reject blank/uniform images |
| `assert_changed` | `{"action":"assert_changed","before":"spawn","after":"walk","min_difference":1.5}` | Detect image movement |
| `assert_no_fault` | `{"action":"assert_no_fault","image":"walk"}` | OCR and reject recognizable N64 exception screens |
| `assert_text` | `{"action":"assert_text","image":"walk","contains":"PALLET"}` | Assert readable HUD/menu text |
| `assert_status` | `{"action":"assert_status"}` | Check emulator still playing |
| `pause` / `resume` | `{"action":"pause"}` | Toggle pause only if needed |
| `frames` | `{"action":"frames","count":5}` | Advance while paused |

All button names are **RetroPad names** (`b`, `y`, `start`, `l`,
`r`, etc.), or high-level aliases `n64_a`, `n64_b`, `n64_z`,
`n64_l`, `n64_r`, `n64_start`. The default Parallel N64 core maps N64
A to RetroPad B and N64 B to RetroPad Y. The C-buttons can differ with
`parallel-n64-alt-map`; use raw RetroPad controls and verify before
claiming a deterministic battle scenario.

`tests/rom_scenarios/pallet_smoke.json` is the first end-to-end fixture.
It boots, captures a reference frame, moves Link forward, captures again,
checks for a material visual change, and checks both screenshots for
OoT's exception overlays.

### Limitations and future precision

Analog movement uses real wall-clock durations rather than an exact frame
counter. The harness supports paused `FRAMEADVANCE` for finer experiments,
but RetroArch applies remote input datagrams one per frame, so simultaneous
presses are delivered across successive frames. Screenshots and OCR test
visible behaviour, not Link's exact coordinates; adding a read-only RAM
bridge for `Player.actor.world.pos` would enable coordinate and collision
assertions once the core's memory map is verified.

This is a **local native integration test**, not a GitHub Actions emulator
job. CI still runs the ROM-free protocol tests; real-ROM gameplay assertions
run against the licensed local dump and can be invoked by Luna or the
developer on their Mac.
