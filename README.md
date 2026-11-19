# Pokémon N64

A native Nintendo 64 Pokémon RPG built on pinned [HackerOoT](https://github.com/HackerN64/HackerOoT). The current `feat/pallet-town-native-scene` branch implements the first playable area: **wake in Red's bedroom, explore Pallet, follow Oak, choose a starter and battle Blue**.

**Verification status:** portable story/battle tests and real big-endian VR4300/MIPS object compilation pass. The new five-area opening has **not yet been linked and played in an emulator in this development environment**; the source ROM and working ParaLLEl installation are on the development Mac. Earlier outdoor/battle smoke results apply to the earlier build. Hardware performance and this opening's native transitions still require that live check.

## Build and play this opening

From your existing checkout, with the supported Zelda dump already in `roms/`:

```sh
git fetch origin
git switch feat/pallet-town-native-scene
git pull --ff-only
make rom-oot-play
```

This builds `build/poke-n64-oot.z64` through Docker, then opens it in the installed **ParaLLEl N64 (Parallel Launcher Edition)** with a fresh save directory. To build or launch separately:

```sh
make rom-oot-docker
make play-oot
```

The build detects Apple Silicon / Intel Docker architecture and reuses extracted assets on subsequent runs. A native host MIPS toolchain is unnecessary for the Docker build. Your private ROMs and generated Stadium assets stay local and ignored by Git.

## The opening

| Area | Playable content |
| --- | --- |
| Red's bedroom | Wake/get-up animation, PC Potion, TV/console, stairs |
| Red's downstairs | Mother dialogue and healing, working exterior door and stairs |
| Pallet Town | Original 20 × 18 walking-cell layout, three buildings, signs, flower beds, fences, water and north grass approach |
| Blue's house | Enterable room, Daisy and introductory dialogue |
| Oak's lab | Oak, Blue, aides, three physical starter balls, confirmation/cancellation and the first rival fight |

Oak stops Red at the north grass and leads him to the laboratory. The balls follow the original **left-to-right Charmander / Squirtle / Bulbasaur** order. Blue chooses the type-advantage starter. Both Pokémon start at level 5 with their initial physical/stat moves; the first fight does not add an early elemental attack.

**Winning and losing both advance the story.** Your Pokémon's HP and PP are restored, Blue leaves the scene, and you can explore the area again. This opening does not grant Poké Balls, the Pokédex or Daisy's Town Map. Route 1 and Route 21 are the next connected areas to implement.

### Controls

| N64 input | Action |
| --- | --- |
| Analog stick | Camera-relative native movement |
| D-pad | World cardinal movement; up/down selects battle commands |
| A | Wake, interact with the object/NPC Red faces, confirm dialogue or battle action |
| B | Cancel starter confirmation or back out of a battle submenu |
| L + R + Z + Start | Toggle the read-only diagnostic state panel for automation |
| L + R + B | Optional wild Rattata debug battle, **only after** completing the opening |

The player retains native OoT movement and collision. The original Link mesh and Navi behavior are suppressed in these five scenes. Red has an original 490-triangle model with a cap, vest, backpack, jeans, sneakers and a procedural walking rig. Oak, Blue and the other residents also have original low-poly meshes.

## Automated complete playthrough

```sh
# Existing ROM: wake -> every room -> starter -> rival -> return outside.
make test-opening

# Select a different starter, or run three independent fresh sessions.
make test-opening STARTER=charmander
make test-opening OPENING_ARGS=--all-starters

# Build first, then run the same complete test.
make rom-opening-e2e
```

`make test-rom`, `make test-battle` and `make rom-oot-e2e` now use the complete opening. The older instant-starter battle JSON fixtures target older ROMs and are marked as legacy.

The runner sends ordinary controller input to its own emulator process. It reads a versioned, CRC-protected panel from actual framebuffer screenshots to verify room, position, story stage, starter, rival, HP, battle turns and completion. It does **not** edit RAM, import a savestate or set story flags. Each run saves screenshots, `report.json`, `state-trace.json` and logs under `build/emulator-tests/` and exits nonzero on a failure. The new live run remains to be executed on the Mac.

Requirements: Python 3, Pillow, Xcode Command Line Tools (`swiftc`), the configured ParaLLEl installation and macOS permission for targeted keyboard events. The harness overrides keyboard bindings only in its temporary session, leaving the normal configuration intact.

See [ROM automation](docs/ROM_AUTOMATION.md) and [opening implementation](docs/PALLET_TOWN.md).

## Map and model sources

`assets/maps/pallet_opening.json` records semantic coordinates and static passability from [pret/pokered at ba9c0568](https://github.com/pret/pokered/tree/ba9c0568f64ae602fadda577a08c66639f93082a). All five cell grids have been compared to that reference. It contains no ROM bytes, Game Boy graphic assets or imported 3D mesh.

`tools/pallet_town.py` authors the 3D scenes. `tools/character_models.py` authors the characters and fallback Pokémon meshes. The visual direction for Red was informed by [Rodolfo Rubens' Gen 1 Red reference](https://sketchfab.com/3d-models/red-from-pokemon-1st-gen-02bbd11d0ab744d080d175e5ce0c321f); that artist's mesh is not included or downloaded.

An optional private Stadium pipeline can render your extracted Bulbasaur in battle:

```sh
# Only when you already have the compatible private source.dsm pack:
python3 tools/stadium_export.py --pack assets/private/stadium/001/source.dsm --species 1 --animated
make stadium-n64
make rom-oot-docker
```

Without the private asset, the build uses the original Bulbasaur fallback. Charmander, Squirtle and the debug Rattata currently use original proxy meshes. This is not a completed Stadium/Snap import for all species. See [Stadium export](docs/STADIUM_EXPORT.md).

For source-mesh previews, independently of the ROM:

```sh
python3 -m pip install Pillow numpy
python3 tools/preview_opening.py
```

These write authoring renders under `build/opening-previews/`. They are labelled as **source previews, not emulator captures**.

## Build requirements and local inputs

| Requirement | Value |
| --- | --- |
| Engine | HackerOoT `5fac42fa11278810ce9ca5b85d5d40b4136b5f57` |
| Base image | Ocarina of Time **US NTSC 1.2**, 32 MiB |
| Normalized big-endian MD5 | `57a9719ad547c516342e1a15d5c28c3d` |
| Input byte orders | `.z64`, `.v64`, `.n64`; normalized before verification |
| Hardware target | N64 with 8 MiB total RAM / Expansion Pak |
| Graphics | Upstream F3DEX3; appropriately configured ParaLLEl RDP/RSP |
| Build host | Docker on macOS/Linux, or GNU Make 4+ with a complete supported MIPS GCC/binutils toolchain |

`make check-rom` checks your input without building. Filenames containing spaces and parentheses work. To select an image outside `roms/`, use:

```sh
make rom-oot-docker ROM="/absolute/path/oot-ntsc-1.2.z64"
```

Docker's image context is the minimal `tools/docker-context` directory. The repository and ROM are mounted at container runtime; the ROM is mounted read-only. Generated engine checkouts are separated by architecture and mode, for example `build/docker-engine-arm64-oot/`. Do not edit those generated copies; change the source in this repository.

Repeated builds preserve extraction and unchanged file timestamps. The build verifies each replacement scene/room command header is at segment offset zero before packaging. To force extraction only when needed:

```sh
python3 tools/docker_rom.py --oot-conversion --refresh-setup
```

See [build performance](docs/BUILD_PERFORMANCE.md) for caching and future ROM slimming. The complete image still contains other upstream assets referenced by its tables.

## ROM-free checks

```sh
make test
make sanitize
make check-native-oot-docker
python3 tools/opening_e2e.py --check-only
```

`make test` covers the shared battle/save rules, the console journey, all three opening choices across 96 journeys (32 seeds per starter), both rival outcomes, direction-aware interactions, early lab entry, map/collision fidelity, generated N64 buffers, overlay installation, incremental builds and observer failures. `make sanitize` runs the C suites under AddressSanitizer and UndefinedBehaviorSanitizer.

To use an installed cross-compiler directly:

```sh
MIPS_CC=/path/to/mips-linux-gnu-gcc python3 tools/check_native.py \
  --require-mips --oot-conversion --engine build/engine-oot
```

This compiles real big-endian VR4300 objects against pinned upstream headers. Declaration-only prerequisites for one unextracted shared object live in the check directory; no substitute runtime assets are produced. **Object compilation does not link or execute a ROM.** CI's ROM-free jobs cannot establish a live playthrough or console performance.

## Shared-core console and standalone prototype

`make play` builds a development console without a ROM. It exercises the shared battle rules through the earlier small test map, including wild encounters, capture, healing, party management and a versioned save codec. It does **not** display the new native room sequence.

Console controls: WASD to move, `j`/Enter to confirm, `k` to go back, `p` for menus, `1`–`6` to select an option, `save`/`load`, and `q` to quit. For an isolated save:

```sh
make play ARGS="--seed 1 --save adventure.sav --no-clear"
```

`make rom-docker` and `make rom` still target that earlier standalone native prototype (`build/poke-n64.z64`), including its diagnostic blue boot screen and SRAM journal. **Use `make rom-oot-docker` for the new opening.** `make rom-control-docker` builds a separate pristine upstream boot diagnostic.

## Current limits

- The outdoor/interior **static walking grids and landmark positions** follow Red/Blue. The 3D elevation, camera, palettes and meshes are original interpretations. Bed wake-up is an addition; the Game Boy game begins with Red already standing.
- Oak's approach, indoor arrival and Blue's selection/departure movements are abbreviated. Background residents remain at their original initial positions. Some furniture uses short original dialogue rather than the complete original scripts.
- Shared combat remains a prototype: cubic XP, fixed DV 8 stats, simplified critical/capture rules and reduced learnsets. In particular, a first rival win currently leaves a level-5 starter at level 5; the original's Medium Slow curve would produce level 6. Species-specific growth and save migration are future work.
- Opening story/room progress survives scene changes but is **not yet saved to cartridge SRAM**. Fresh runs start in the bedroom. The separate console/standalone save codec remains tested.
- No Route 1/21 scenes, later quests, evolution, trading, full PC storage or new Pokémon soundtrack are implemented. These scenes disable the stock background music.
- The new opening awaits a linked ROM and controller playthrough on the development Mac. Timing, framing and performance on real N64 hardware remain unverified.

## Source structure

| Path | Purpose |
| --- | --- |
| `src/core.c`, `include/poke.h` | Portable battle, party and prototype progression rules |
| `src/intro.c`, `include/poke_intro.h` | Opening story, dialogue, starter selection and warp state |
| `src/save.c` | Versioned portable save codec |
| `native/oot_conversion.c` | Native input, scene transitions, cameras, characters, HUD and read-only observer |
| `native/red_actor.c` | Native mesh suppression/render setup |
| `assets/maps/pallet_opening.json` | Pinned semantic map data |
| `tools/kanto_layout.py`, `tools/pallet_town.py` | Shared map tables and native scene/collision generation |
| `tools/character_models.py` | Original character and fallback Pokémon meshes |
| `tools/bootstrap.py` | Guarded installation into the pinned engine checkout |
| `tools/opening_e2e.py` | Complete controller-driven native opening test |
| `tools/retroarch_e2e.py` | Emulator session ownership, capture and generic JSON diagnostic runner |

No ROM, extracted proprietary asset, save file or compiled game image is committed. Upstream attribution and terms remain with the respective projects.
