# Pokémon N64

A native Nintendo 64 RPG prototype built on [HackerOoT](https://github.com/HackerN64/HackerOoT). The first slice is a small original Pallet / Route 1 test area: choose a starter, explore, battle wild Pokémon, catch them, heal and save.

**Current status:** the gameplay loop is implemented and tested on the host. The native renderer, controller adapter, SRAM journal and engine boot hooks compile into big-endian VR4300/MIPS objects against the pinned engine. **A complete ROM has not been linked or played in an emulator or on hardware yet.** That step needs a user-supplied Ocarina of Time US NTSC 1.2 ROM.

The 3D models are original, simple block models. Stadium/Snap models and animations have **not** been imported. This is an early playable rules prototype with native integration, not the full Kanto remake.

## What is implemented

| System | In this slice |
| --- | --- |
| Exploration | Bounded 20 × 24 test map, buildings, trees, collision, elevated tracking camera in native code |
| Starter | Oak interaction; Bulbasaur, Charmander or Squirtle at level 5 |
| Wild encounters | Pidgey and Rattata at levels 2–4; encounter rolls depend on actual movement in grass |
| Battles | Fight / Bag / Party / Run, speed order, accuracy, HP, PP, Attack/Defense stages, type effectiveness, STAB and simple critical hits |
| Moves | Tackle, Growl, Scratch, Tail Whip, Gust, Vine Whip, Ember, Water Gun; Struggle when PP is exhausted |
| Progression | Experience, level increases and a starter elemental move at level 7 |
| Catching | Poke Balls, failure/success turns, six-member party and selected lead |
| Recovery | Healing NPC restores HP/PP and basic supplies; full-party faint returns to the station |
| Persistence | Versioned 256-byte save codec with CRC and semantic checks; atomic host saves; native two-slot SRAM journal with readback |
| Native engine integration | Dedicated resident game state, boot routing, controller input, original 3D scene/proxies, HUD and explicit linker entries |
| Development | Shared-core console, deterministic tests, sanitizers, Linux/macOS CI and native object compilation without a ROM |

## Play the development console now

Requires a C compiler, make and Python 3. It works on macOS and Linux without an N64 ROM.

```sh
git clone https://github.com/nicholashu/poke-n64.git
cd poke-n64
make play
```

On macOS, install the Command Line Tools if a compiler is not already available:

```sh
xcode-select --install
```

The console runs **the same gameplay code and input state machine** as the native target. It is intended for rapid development and testing; it does not emulate the N64 renderer.

| Console command | Action |
| --- | --- |
| `w` / `a` / `s` / `d` | Walk one tile; `w` / `s` navigate menus |
| `j` or Enter | Talk / confirm |
| `k` | Back |
| `p` | Open the field menu |
| `1` through `6` | Select and confirm a visible option |
| `save` / `load` | Save/load while in the field |
| `q` | Quit without saving |

Start by talking to Oak, the `O` near you. Choose a partner, head north along the central path, and step left or right into `:` grass. The `+` east of your starting location restores the party. In battle, choose Fight to select a move, or Bag to throw a ball. After catching something, return to heal, select a party member and save.

The default save is `poke-n64.sav` in the working directory. A valid save loads on startup. An invalid existing save is preserved; use a different path to start another save.

```sh
make play ARGS="--seed 1 --save adventure.sav --no-clear"
```

## Build the native N64 target

### Input and hardware target

- **Engine:** HackerOoT commit `5fac42fa11278810ce9ca5b85d5d40b4136b5f57`, recorded in `native/upstream.json`.
- **Base ROM:** Ocarina of Time **US NTSC 1.2**, 32 MiB. Normalized big-endian MD5: `57a9719ad547c516342e1a15d5c28c3d`.
- **Input formats:** `.z64`, `.v64` and `.n64` byte order are detected and normalized before the checksum is verified.
- **RAM:** 8 MiB Expansion Pak.
- **Graphics:** upstream F3DEX3; use an LLE-capable emulator such as ares or a suitably configured parallel-rdp/parallel-rsp setup.
- **Save type:** explicitly select **SRAM, 32 KiB** if the emulator or flashcart does not detect it. This ROM uses game ID `PK` and its own save layout.

No ROM, extracted Nintendo asset or compiled game image is included in this repository. The build reads your local input, copies it into the ignored build directory, and never uploads it. Use a separate emulator save file for this project.

### Container build

The Dockerfile supplies the Linux cross compiler and native tool dependencies. On Apple Silicon, use the `linux/amd64` platform for the upstream build tools.

```sh
docker build --platform linux/amd64 -t poke-n64-build .
docker run --rm --platform linux/amd64 \
  -v "$PWD:/project" \
  -v "/absolute/path/to/oot-ntsc-1.2.z64:/inputs/oot.z64:ro" \
  poke-n64-build make rom ROM=/inputs/oot.z64
```

The expected outputs are:

```text
build/poke-n64.z64
build/poke-n64.bps
```

**This full build path is implemented but has not been exercised with a base ROM in this repository's initial delivery.** A successful object compile does not prove the final ROM links, boots or saves correctly on a console. The build exits with an error for a missing or wrong-version input; CI does not treat that as a successful ROM build.

### Existing Linux toolchain

With the cross compiler and [HackerOoT's prerequisites](https://github.com/HackerN64/HackerOoT/blob/5fac42fa11278810ce9ca5b85d5d40b4136b5f57/INSTALLATION.md) installed:

```sh
make rom ROM=/absolute/path/to/oot-ntsc-1.2.z64
```

The helper installs the project overlay into `build/engine`, validates the base image, runs engine setup/build/compression and produces a BPS patch. It rejects unexpected edits in files it manages instead of resetting your checkout. Keep authored changes in this repository, outside `build/engine`.

### N64 controls

| Controller | Action |
| --- | --- |
| Stick or D-pad | Walk; up/down select a menu entry |
| A | Talk / confirm |
| B | Back |
| Start | Field menu with Party, Save, Load and Continue |

The native state loads a valid save at boot. Saving is explicit. A forced replacement after fainting must select a healthy party member.

## Verify the code

```sh
make test
make sanitize
make check-native
```

`make test` exercises gameplay, saves and a complete input-driven console journey. `make sanitize` repeats the C tests with AddressSanitizer and UndefinedBehaviorSanitizer.

`make check-native` bootstraps the pinned engine and compiles the shared core, serializer, native state, setup hook, game-state table and dispatcher against the real engine headers. With no MIPS compiler it reports a weaker 32-bit host syntax check. To require actual target objects:

```sh
python3 tools/check_native.py --require-mips
# Or select an installed cross compiler explicitly:
MIPS_CC=/path/to/mips-linux-gnu-gcc python3 tools/check_native.py --require-mips
```

CI requires MIPS compilation and does not need or handle a ROM. Nothing under `build/` is committed.

## Architecture

| Path | Responsibility |
| --- | --- |
| `include/poke.h` | Portable game state, stable IDs, input and persistence contracts |
| `src/core.c` | World collision, encounters, battle rules, parties, progression and menus |
| `src/save.c` | Byte-exact save encoding, CRC and validated load |
| `native/poke_state.c` | HackerOoT graphics/input and cartridge SRAM integration |
| `native/poke_state.h` | Resident native game state |
| `native/upstream.json` | Engine revision and supported base image |
| `tools/bootstrap.py` | Safe, repeatable engine overlay installation |
| `tools/check_native.py` | Real-header/native object compilation without game assets |
| `tools/build_rom.py` | Base validation, ROM build and patch packaging |
| `host/` | Console frontend and full command-driven journey test |
| `tests/` | Gameplay, persistence and build-tool regression checks |
| `assets/manifest.json` | Documented species/model slots for later asset conversion |
| `docs/MVP.md` | Acceptance criteria, limitations and next milestones |

Gameplay has no heap allocation, engine pointers, file APIs or floating point. Native rendering owns those platform concerns. State is resident rather than tied to an actor overlay that can unload between scenes.

## Deliberate simplifications

This is **not a bit-accurate Red/Blue implementation**. All species use cubic XP growth, fixed stats with DV 8 and no stat experience. Starter elemental moves are granted at level 7. Critical hits use a flat 1/16 chance and double computed damage. Capture uses a documented HP/catch-rate formula with a bounded chance. Escape is guaranteed by the third battle turn. Elemental moves do not inflict status ailments yet, and the available movesets are reduced for the slice. There are no trainer battles, evolution, PC storage, trading, audio, scripted story quests or full Kanto maps yet.

The first art pass is simple original geometry. The native scene does not contain extracted Stadium/Snap meshes, skeletal animation, attack effects or a faithful Red model. The model manifest documents future work; it does not pretend to be an exporter.

When the party is full, throwing a ball is rejected without consuming an item or turn. The healing station provides free basic supplies so testing does not reach a dead end. Invalid actions do not consume turns, fainted Pokémon cannot attack, and all-zero PP falls back to Struggle.

## References

- [HackerOoT pinned source](https://github.com/HackerN64/HackerOoT/tree/5fac42fa11278810ce9ca5b85d5d40b4136b5f57): native engine and build interfaces.
- [pret/pokered](https://github.com/pret/pokered): reference for the original game's mechanics and data. This slice is a separately written approximation.
- [Fast64](https://github.com/Fast-64/fast64): planned Blender workflow for authored scenes and converted models.
- [Stadium Animation Inspector](https://github.com/Nexhas28/stadium-animation-inspector): asset-format research reference, not a completed import dependency.

Upstream project attribution and terms remain with their respective projects. No upstream contribution is made by this repository.
