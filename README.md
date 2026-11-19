# Pokémon N64

A native Nintendo 64 RPG prototype built on [HackerOoT](https://github.com/HackerN64/HackerOoT). The first slice is a small original Pallet / Route 1 test area: choose a starter, explore, battle wild Pokémon, catch them, heal and save.

**Current status:** the gameplay loop is implemented and tested on the host. The native renderer, controller adapter, SRAM journal and engine boot hooks compile into big-endian VR4300/MIPS objects against the pinned engine. A complete ROM has been linked locally using a user-supplied Ocarina of Time US NTSC 1.2 ROM, and the blue boot screen was verified in ParaLLEl N64 through RetroArch on 19 November 2026. **Native gameplay, cartridge saving and real hardware remain unverified.**

The 3D models are original, simple block models. Stadium/Snap models and animations have **not** been imported. This is an early playable rules prototype with native integration, not the full Kanto remake.

## Animated Stadium Bulbasaur: experimental OoT battle

A **private Stadium model and animation pipeline** is available on the
`feat/stadium-animated-bulbasaur` integration branch. It builds on the real
OoT `PlayState` total conversion and keeps the original standalone game on
`main` untouched.

After exporting Bulbasaur from your compatible Stadium ROM:

```sh
python3 tools/stadium_export.py --pack assets/private/stadium/001/source.dsm --species 1 --animated
make stadium-n64
make rom-oot-docker
```

Open `build/poke-n64-oot.z64` using ParaLLEl N64 with a working F3DEX3
configuration. The build uses the privately generated animation frames when
available, otherwise it safely links a no-op asset stub.

In Kokiri Forest, **L+C-left** selects Bulbasaur. Use **L+R+A** for an attack
preview and **L+R+B** to start a test encounter against a level-4 Rattata.
The native sub-camera frames the encounter while the existing Pokémon core
handles Fight/Bag/Party/Run, HP, PP and turns. Rattata and the test landscape
remain placeholders. No Pokémon assets are committed.

See [animated Stadium export and N64 battle test](docs/STADIUM_EXPORT.md).
These changes have MIPS object-compilation and synthetic-asset tests; actual
rendering and battle transitions still require testing against your local ROM.

## What is implemented

| System | In this slice |
| --- | --- |
| Exploration | Bounded 20 × 24 test map, buildings, trees, collision, OoT-style behind-Red chase camera and camera-relative controls |
| Starter | Oak interaction; Bulbasaur, Charmander or Squirtle at level 5 |
| Wild encounters | Pidgey and Rattata at levels 2–4; encounter rolls depend on actual movement in grass |
| Battles | Stadium-style separate 3D arena camera, idle bob and compact HP/command panels; Fight / Bag / Party / Run, speed order, accuracy, HP, PP, Attack/Defense stages, type effectiveness, STAB and simple critical hits |
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

### Put your local ROMs in `roms/`

Create a `roms` folder in the project root and put your unzipped game dumps there. Filenames with spaces and parentheses work. The entire directory is excluded from Git and the Docker image build context, including archives and other files.

```sh
make check-rom
```

This checks the image size, byte order and checksum without downloading tools, building or modifying any files. The builder selects the matching **OoT US NTSC 1.2** image by contents. Other images, including Pokémon Stadium, are skipped. A filename containing `USA (Rev 2)` is a useful label but is not a substitute for this validation.

`make rom-docker` builds from that folder using the supplied Linux toolchain. You can also select an explicit input with `make rom-docker ROM="/path/with spaces/oot.z64"`. The same selection works with the native `make rom` command. Stadium is not used by the current build; keep it for the later model-import work.

### Docker build (recommended on macOS)

Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/), open it, and wait until its engine is running. On Apple Silicon, use Docker Desktop's Apple Silicon installer. The wrapper reads the Docker daemon's architecture and builds natively as **`linux/arm64`** on an ARM daemon or **`linux/amd64`** on an Intel/AMD daemon. Docker Engine on Linux also works. Both platforms cross-compile the game for the same N64 CPU.

Run these commands from the project root with Python 3 and `make` available:

```sh
# Use the supported OoT image from roms/:
make rom-docker

# Or select an image elsewhere on your computer:
make rom-docker ROM="/absolute/path/with spaces/oot-ntsc-1.2.z64"
```

The wrapper validates the ROM before downloading or building anything, checks that Docker is running, builds the toolchain image and runs the build. You do not need a MIPS compiler or GNU Make 4 installed on the host for this command. Initial setup needs network access to fetch the image, pinned engine and build dependencies.

Docker receives only the minimal `tools/docker-context` directory as its image build context; repository source and ROM bytes are not sent to the image builder. At runtime, the project is mounted locally at `/project`, the selected ROM is mounted read-only at `/inputs/base.z64`, and `roms/` is also mounted read-only when present. An explicit ROM path outside the project works the same way.

The Docker build maintains a separate engine checkout, Linux tools and extracted assets for each architecture:

| Build environment | Generated engine directory |
| --- | --- |
| Docker ARM64 | `build/docker-engine-arm64` |
| Docker AMD64 | `build/docker-engine-amd64` |
| Native host toolchain | `build/engine` |

This separation prevents a build from reusing executables or Python environments made for another platform. Keep authored changes in this repository, outside these generated engine checkouts.

Both build methods write the same outputs:

```text
build/poke-n64.z64
build/poke-n64.bps
```

**This full build path is implemented but has not been exercised with a base ROM in this repository's initial delivery.** A successful object compile does not prove the final ROM links, boots or saves correctly on a console. The build exits with an error for a missing or wrong-version input; CI does not treat that as a successful ROM build.

### Native build without Docker

`make rom` requires **GNU Make 4 or newer**, a complete supported **big-endian MIPS GCC/binutils toolchain** on `PATH`, and [HackerOoT's other prerequisites](https://github.com/HackerN64/HackerOoT/blob/5fac42fa11278810ce9ca5b85d5d40b4136b5f57/INSTALLATION.md). The compiler, assembler, linker, `objcopy`, `objdump`, `nm` and `strip` must use the same supported prefix, such as `mips-linux-gnu-`. The builder checks these prerequisites before installing the engine or copying a ROM.

macOS's bundled Make is too old for the upstream build. `brew install make` supplies `gmake`, which the helper detects, but a complete MIPS cross toolchain is still required. Xcode Command Line Tools alone are sufficient for the development console, not for building the N64 ROM.

```sh
make rom
# Or provide a base image outside roms/:
make rom ROM="/absolute/path/to/oot-ntsc-1.2.z64"
```

The helper validates the base image, checks the host toolchain, installs the project overlay into `build/engine`, then runs engine setup/build/compression and produces a BPS patch. It rejects unexpected edits in files it manages instead of resetting your checkout.

### Native boot comparison (black-screen diagnostics)

The earlier *control* image still linked our modifications. It was not a clean baseline. The current `rom-control-docker` target creates a **new, unmodified HackerOoT checkout** in `build/docker-engine-arm64-stock` (or `-amd64-stock`), with all upstream sources, linker, ROM header and Zelda startup transition intact.

```sh
make rom-control-docker
make rom-docker
```

Load both images in **ares**, with the 4 MB Expansion Pak selected (8 MB total N64 RAM):

| ROM | Expected result | Meaning |
| --- | --- | --- |
| `build/poke-n64-control.z64` | Original Zelda logo/title sequence | The untouched HackerOoT build works with this base ROM and emulator |
| `build/poke-n64.z64` | Solid blue screen before pressing A | Our custom Pokémon game state reaches framebuffer setup |

The pristine control ROM retains Zelda's game ID and save format; use a separate emulator save slot from Pokémon. This control image is **not equivalent to the previous control image**, despite sharing the same output filename.

Before BPS packaging, `tools/inspect_rom.py` independently verifies the generated N64 header, IPL3 variant and boot CRC using the engine's `ipl3checksum` dependency. It prints title, game ID, entrypoint and computed CRCs or stops on a mismatch. A correct checksum is necessary but does not establish that the ROM will boot.

If **both** images are black, collect the brief on-screen fault text and the build's `ROM verified` output. If **only Pokémon** is black, investigate its custom boot path. Use a macOS screen recording or phone slow-motion video to capture text that flashes only for a frame. These checks cannot diagnose the exact fault without a capture or a runtime trace.

### Boot-screen diagnostic

The native build now starts on a **solid blue screen** before displaying the 3D scene. This is intentional: it exercises the minimal N64 framebuffer-clear path without running the map renderer, helping distinguish an early boot/link issue from a scene-rendering issue.

- Press **A** on the blue screen to load cartridge progress and enter Pallet Town.
- Hold **Z + A** on the blue screen to enter Pallet Town **without reading cartridge SRAM**, for diagnosing startup/save faults. This does not delete existing progress.
- If the screen stays **black** before ever showing blue, the game has not reached this diagnostic frame; investigate ROM linkage, boot state and emulator logs before changing models.
- If blue works but the game goes black after A, retry with Z + A. This separates the SRAM path from the full scene renderer.

The previous ROM build's boot status was unverified; this is a diagnostic instrument, not proof that the boot issue is resolved. The first frame intentionally does not include text or a logo, to avoid depending on the higher-level rendering path being debugged.

### N64 controls

| Controller | Action |
| --- | --- |
| Stick or D-pad | Camera-relative movement in the overworld; up/down to select menus |\n| Z | Recenter chase camera behind Red in the overworld |\n| C-left / C-right | Orbit the overworld camera (temporary prototype controls) |
| A | Talk / confirm |
| B | Back |
| Start | Field menu with Party, Save, Load and Continue |

The overworld camera sits behind Red at a low third-person angle and follows a single smoothed pivot. While the stick stays held, its movement direction is anchored to the camera's starting angle, so the chase camera can rotate behind Red without steering him into a circle. The temporary tile-based obstruction check accounts for roof height, pulls the camera inward when necessary, and eases it outward when clear. Release and re-press the stick to take a new camera-relative heading; Z recentres and C-left/C-right orbit. This is still a prototype, not OoT's full collision-raycast camera. Battles switch to an independent Pokémon Stadium-inspired arena presentation, with both Pokémon visible, gentle camera motion, idle bob and status/command panels. This is a **presentation prototype**, not a Stadium asset import. Original Stadium Pokémon models, move animation sequences, trainer throwing animations and stadium backdrops are still future work.

The native state loads a valid save after leaving the diagnostic boot screen. Saving is explicit. A forced replacement after fainting must select a healthy party member.

## Verify the code

```sh
make test
make sanitize
make check-native-docker
```

`make test` exercises gameplay, saves and a complete input-driven console journey. `make sanitize` repeats the C tests with AddressSanitizer and UndefinedBehaviorSanitizer.

**`make check-native-docker` needs no ROM.** With Docker running, it builds the actual toolchain image, checks GNU Make and the MIPS toolchain inside the container, installs the engine's Python dependencies, and builds its host tools. It also compiles six big-endian VR4300/MIPS objects against the pinned engine headers: the shared core, serializer, native state, setup hook, game-state table and dispatcher. It uses the same architecture-specific engine checkout as `make rom-docker`. This checks the container, tool setup and native integration without extracting a ROM, linking a game image or running the game.

For a host toolchain, `make check-native` uses `build/engine` and checks the same six sources. With no MIPS compiler it reports a weaker 32-bit host syntax check. To require actual target objects:

```sh
python3 tools/check_native.py --require-mips
# Or select an installed cross compiler explicitly:
MIPS_CC=/path/to/mips-linux-gnu-gcc python3 tools/check_native.py --require-mips
```

`MIPS_CC` selects a compiler for the object checker only; it does not configure the full upstream ROM build. CI includes direct MIPS compilation and Docker jobs running `make check-native-docker` on both `ubuntu-24.04` (AMD64) and `ubuntu-24.04-arm` (ARM64). These checks require no ROM. Nothing under `build/` is committed.

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
| `tools/build_env.py` | Native GNU Make and matching MIPS toolchain preflight |
| `tools/docker_rom.py` | Docker availability, isolated Linux build and ROM-free container check |
| `Dockerfile`, `tools/docker-context/` | Ubuntu toolchain image and minimal image build context |
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
