# Automated native opening test

`tools/opening_e2e.py` plays the **actual ROM** in the installed macOS ParaLLEl N64 (Parallel Launcher Edition). It uses ordinary controller events, actual framebuffer captures and a read-only state panel. This live runner is distinct from the portable C tests and the MIPS object compiler check.

**Current evidence:** offline protocol/route/failure tests pass. The new complete opening runner has not yet been executed against a newly linked ROM on the development Mac. The older successful outdoor and wild-battle smoke runs do not establish this new flow.

## Run it

Close any instance already playing the same ROM, then:

```sh
# Pillow is required to decode screenshots; Swift comes with Xcode tools.
python3 -m pip install Pillow

# Build once and run the complete opening.
make rom-opening-e2e

# Reuse the built ROM.
make test-opening
make test-opening STARTER=charmander
make test-opening STARTER=squirtle

# Three independent runs, each with empty save/state directories.
make test-opening OPENING_ARGS=--all-starters

# Validate paths without launching an emulator or reading a ROM.
python3 tools/opening_e2e.py --check-only
```

`make test-rom` and `make test-battle` are aliases of `test-opening`. `make rom-oot-e2e` builds and runs the complete opening. A custom ROM path can be supplied directly:

```sh
python3 tools/opening_e2e.py --rom /absolute/path/poke-n64-oot.z64 --starter bulbasaur
```

The native build is `build/poke-n64-oot.z64`, not the earlier standalone `build/poke-n64.z64`.

## What the test proves when it passes

The runner waits for and records 21 checkpoints:

1. Bedroom wake prompt.
2. Red out of bed and movement unlocked.
3. One-time PC Potion dialogue.
4. Successful stairs transition downstairs.
5. Mother interaction.
6. Successful door transition to Pallet.
7. Entry into Blue's house.
8. Daisy interaction.
9. Oak's north-grass warning.
10. Outdoor escort state.
11. Lab scene loaded and welcome dialogue active.
12. Starter choice unlocked.
13. Ball confirmation with no starter yet.
14. Cancellation leaves the choice uncommitted.
15. Ball confirmation reopened.
16. Correct starter and type-advantage rival selected.
17. Lab aisle triggers Blue's challenge.
18. Actual trainer battle with command menu.
19. Battle finishes with a recorded win/loss.
20. Opening completed, Pokémon healed and movement restored.
21. Exit back to Pallet with the chosen starter retained.

During the battle, repeated A presses choose Fight and the first damaging move. The test requires a positive turn count and an HP decrease **observed during an active trainer battle**. It does not treat the cleared enemy allocation after battle as evidence of damage. Accuracy rolls are allowed to miss; the fight continues instead of requiring a hit on its first turn. Either victory or defeat is a valid opening outcome.

Navigation uses a cardinal path through the original passability grid, excludes current NPC cells and unintended doorways, and corrects each controller pulse from the ROM's measured position. No controller event teleports the player or modifies a story flag. Scripted Oak movement is ordinary game behavior reached through the same interaction as a manual playthrough.

## Session ownership and evidence

Every run creates a unique folder under `build/emulator-tests/` with:

| Output | Purpose |
| --- | --- |
| `report.json` | Pass/fail, selected starter, checkpoints, damage and turn evidence |
| `state-trace.json` | Every decoded state, associated capture and current navigation checkpoint |
| `screenshots/` | Raw framebuffer PNGs, including intermediate observations |
| `failure.txt` | Failure detail, when applicable |
| `retroarch.log`, `process.log` | Emulator diagnostics |
| `test-config.cfg` | Temporary input/network/save overrides |
| `saves/`, `states/` | Initially empty cartridge-save and savestate directories |

The harness starts and owns one emulator PID. It refuses to start if the same ROM is already running, confirms RetroArch is playing and reports the isolated save directory, and quits only the instance it started. Cleanup releases held inputs even after a failure or interruption. Existing saves and other emulator sessions are not reused or removed.

Graphics/RDP/RSP configuration comes from the existing working installation. `config_save_on_exit=false` prevents temporary settings from replacing normal preferences. Shaders/filters and screenshot notifications are disabled for readable captures. Normal emulator hotkeys require an unused F12 modifier during the run, so Tab cannot accidentally invoke fast-forward.

Controller bindings are local to the session:

| macOS key | Scripted control |
| --- | --- |
| I / J / K / L | N64 D-pad north / west / south / east |
| Space | N64 A |
| Left Shift | N64 B |
| E / R / Tab / Return together | N64 L + R + Z + Start, observer toggle |

The L/R mappings cover the core's standard and independent-C layouts; extra C-button bits are ignored by the game. The Swift event helper is compiled once per run and posts to the exact owned process. macOS permission for those events is required. A missing permission or ineffective binding causes a timeout/no-movement failure, never a successful test.

## Read-only screen protocol

Holding N64 **L + R + Z** and pressing **Start** toggles a diagnostic panel. It is absent during normal play. The panel contains 32 bytes in a 16 × 16 bit grid, each bit a 4 × 4 rectangle. Its origin is `(248,6)` on the 320 × 240 framebuffer, inside a cyan border. The native renderer separates fill-color batches with RDP pipeline syncs.

| Byte offset | Meaning |
| --- | --- |
| 0–3 | ASCII `PK64` |
| 4 | Protocol version, currently 1 |
| 5 | Room: Pallet 0, bedroom 1, downstairs 2, Blue's house 3, lab 4 |
| 6 | Opening stage, declared in `include/poke_intro.h` |
| 7 | Dialogue ID |
| 8–9 | Player starter and rival species IDs |
| 10–11 | Shared game mode and battle result |
| 12–15 | Own HP, enemy HP, own max HP, enemy max HP |
| 16–19 | x and z, unsigned big-endian 16-bit quarter-world-units from the map's west/north edge |
| 20–21 | Native update frame counter, low 16 bits, big-endian |
| 22–27 | Menu cursor, trainer flag, battle turns, input lock, warp/facing flags, opening outcome |
| 28–31 | Big-endian CRC32 of the first 28 bytes |

Byte 26 bit 0 indicates a pending warp; bits 1–2 report facing (north 0, east 1, south 2, west 3), and bit 3 indicates an active native scene fade. Checkpoints wait for that fade to finish before sending the next interaction. The controller waits for that measured heading before interacting.

The decoder samples the interior of each bit to avoid edge filtering, then validates the magic, version, CRC, ranges and frame progression. A separate crop check rejects a blank world even if the HUD and observer still render. It accepts raw 4:3 framebuffer images at native or scaled resolution. Wrong aspect ratio, missing panel, ambiguous bits, a checksum mismatch, a stopped frame counter, unexpected room, navigation obstruction or story timeout all fail the run.

This is observation only. No command channel, RAM write, seed override, battle bypass, imported savestate or injected story completion exists in the panel. It stays usable through room changes and can remain visible over fades for diagnostics.

## Generic JSON diagnostics

`tools/retroarch_e2e.py` remains available for focused, bounded input/capture experiments:

```sh
make test-scripted-rom
python3 tools/retroarch_e2e.py tests/rom_scenarios/pallet_smoke.json --check-only
```

The current `pallet_smoke.json` is a short bedroom wake/walk diagnostic using the installed analog W binding. It is weaker than the state-aware opening test and does not establish the complete quest.

The `battle_smoke.json` and `battle_probe.json` fixtures are labelled **legacy**. They reproduce the earlier ROM's instant-starter/debug encounter flow and should not be run against the new bedroom-opening ROM.

JSON scenarios accept these actions:

| Actions | Purpose |
| --- | --- |
| `wait`, `frames` | Time-based wait or paused frame stepping |
| `tap`, `press`, `release`, `release_all`, `stick` | Local Remote RetroPad input |
| `key_hold`, `key_chord` | Keyboard events posted to the owned macOS PID |
| `screenshot` | Capture actual raw framebuffer PNG |
| `assert_visible`, `assert_changed`, `assert_movement` | Pixel checks, including movement exceeding idle drift |
| `assert_text`, `assert_hp_decreased`, `assert_no_fault` | macOS Vision OCR checks |
| `assert_status`, `pause`, `resume` | Emulator status/control |

`Network Commands` and `Remote RetroPad` are separate local UDP interfaces. The full opening uses Network Commands for status/capture and targeted keyboard input for reliable movement. See [RetroArch's command API](https://github.com/libretro/RetroArch/blob/master/command.h), [libretro input IDs](https://github.com/libretro/libretro-common/blob/master/include/libretro.h) and [ParaLLEl core options](https://docs.libretro.com/library/parallel_n64/).

## Limits

The controller pulses are wall-clock-driven and corrected from observed position; this is not a frame-perfect deterministic input movie. It exercises a locally supplied ROM and configured emulator, not real hardware. CI runs offline protocol, route and failure tests plus native compilation; it does not download a ROM or claim a live emulator pass.

A passing state trace proves the named sequence occurred in the ROM, but final camera framing, artwork, audio and performance also need visual/hardware review. The screenshots are kept for that purpose.
