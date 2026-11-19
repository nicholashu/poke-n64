# Pallet Town ROM converter

`feat/pallet-rom-converter` adds an optional import stage to the existing HackerOoT total conversion. The supplied Pokémon ROM is the source of map layout, collision data, object placement, doors, connections and dialogue. The repository contains format bindings, original procedural art rules and an authored event adapter.

The branch started at `dada720` on `feat/pallet-town-native-scene` and incorporates the subsequent five-room opening commit `7681952`. The ordinary authored opening, standalone prototype and existing private Stadium asset path are retained. Imported mode is a separate outdoor slice; it does not yet feed extracted events into the full indoor story.

## Run it

Python 3 is sufficient to extract and generate assets. The importer has no third-party Python dependencies and does not need an emulator, OoT ROM, Stadium ROM, or network access for this stage.

```sh
make import-pallet POKEMON_ROM="/absolute/path/Pokemon Red.gb"
```

Equivalent direct invocation, with a validation-only option:

```sh
python3 tools/pallet_rom.py --rom "/absolute/path/Pokemon Red.gb"
python3 tools/pallet_rom.py --rom "/absolute/path/Pokemon Red.gb" --check
```

`--check` validates and compiles in memory without creating output files. Unsupported versions, truncated data, bad pointers and unsupported tile interpretations fail explicitly. The command does not download any ROM or disassembly and has no switch to bypass ROM identification.

To build the actual native game, use the existing OoT and optional privately generated Stadium assets:

```sh
make rom-pallet-docker \
  ROM="/absolute/path/Ocarina of Time US 1.2.z64" \
  POKEMON_ROM="/absolute/path/Pokemon Blue.gb"
```

The output is `build/poke-n64-pallet.z64`. Its Docker engine checkout is `build/docker-engine-<architecture>-pallet`; it does not overwrite the older `poke-n64-oot.z64` build. Both input ROMs are mounted read-only, including files outside the repository. Stadium's existing private generated model is linked through the same optional asset path; this converter does not repeat that extraction.

On the configured development Mac, launch the imported image with the existing clean-session launcher:

```sh
python3 tools/play_oot.py --rom build/poke-n64-pallet.z64
```

That launcher creates a fresh save/savestate directory and clears saved filters for the session. The older `make play-oot` default still selects the older `poke-n64-oot.z64` image, so use the explicit filename above for the import.

With a host MIPS toolchain, the equivalent build is:

```sh
python3 tools/build_rom.py --oot-conversion \
  --rom "/absolute/path/oot.z64" --pokemon-rom "/absolute/path/red.gb"
```

This uses `build/engine-pallet` by default. To compile native objects without linking a game, supply the same GB input to `tools/check_native.py --require-mips --oot-conversion --pokemon-rom ...`.

## Supported input

Only these exact unmodified English 1 MiB retail images are accepted:

| Version | SHA-1 |
| --- | --- |
| Red | `ea9bcae617fdf159b045185467ae58b2e4a48b9a` |
| Blue | `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2` |

The full-image identity check is followed by cartridge-header and checksum checks. Yellow, translations, other revisions and modified ROMs need separate verified profiles. A filename alone never identifies the version. Source files are never modified.

## What the pipeline does

1. **Identify and parse.** `tools/gen1_rom.py` follows the map bank/pointer tables, reads Pallet's header and object records, and resolves the tileset's block and collision tables. One map block contains sixteen 8-pixel graphic tiles, making four 16-pixel walking cells. Static walking passability uses each cell's bottom-left graphic tile and the ROM's collision whitelist.
2. **Extract behavior data.** Read dialogue through simple text/far-pointer commands, preserve name tokens, decode NPC visibility, and retain both escort movement streams. Oak's text entry contains assembly; two verified data targets are selected by the authored adapter instead of executing that assembly.
3. **Interpret the map in 3D.** `tools/pallet_rom.py` groups building tiles into connected rectangular footprints and binds each to an extracted door. Original roofs, walls, grass, fences and boundary posts supply height and visual style. Unknown tile meanings or unsupported footprints are rejected rather than silently guessed.
4. **Emit native assets.** Generate scene headers, render geometry, grid-boundary collision, immutable NPC/sign/warp/text tables and diagnostics. The existing header-first scene/room linker layout is preserved. Each display-list vertex batch stays below the RSP limit.
5. **Install and build.** `tools/bootstrap.py` installs generated sources through the existing guarded overlay manifest. The normal upstream OoT build links the native game. Runtime and data objects are explicitly listed in the resident linker spec and native compilation checks.

World coordinates use **80 N64 units per walking cell**. The map is centred at the origin; increasing Game Boy X becomes increasing world X, increasing Game Boy Y becomes increasing world Z, and world Y remains height. The player spawns one cell south of Red's extracted exterior door.

Generated maps share the existing scene slot, input handling, camera and optional Stadium asset interface. The import adds a separate portable outdoor event runner, without introducing a second battle or Pokémon-model system.

## Event adapter and current boundaries

The original Pallet story routines are assembly. This slice deliberately translates the known opening behavior into `src/pallet_import.c`:

- Oak begins hidden. Reaching the north approach triggers the extracted greeting and locks player movement.
- Oak becomes visible and walks over passable cells to the player. The warning text comes from the supplied ROM.
- After the final dialogue page, Oak escorts the player along a bounded path through the extracted collision grid to the lab warp.
- Because the lab interior is not part of this branch, the runtime shows an explicit destination message. It does not load an unrelated Zelda room or set the original “followed Oak into lab” completion flag.

The portable runner supports directional NPC/sign interactions, paginated dialogue, object occupancy, scripted movement, and destination boundary messages. The native adapter renders original simple NPC proxies and forwards ordinary controller input. Default player/rival name tokens render as RED/BLUE in this preview.

**Not implemented:** the Game Boy script as a general VM; the exact original escort timing/path; wandering residents; indoors; starter selection; the rival battle; later Pallet/Daisy/Pokédex events; music; or persistent story saves. Raw movement bytes are extracted into the JSON for the later fidelity pass. The current escort uses a deterministic path through passable cells.

Route connection records and door destinations are retained even when their imported transitions are unavailable. Static collision seals the map bounds. Boundary messages avoid making unsupported transitions look successful. The ordinary `make rom-oot-docker` mode, without `POKEMON_ROM`, builds the authored bedroom-to-rival opening. Its indoor scenes do not automatically make their source-game event/data adapters complete for imported mode.

## Generated output

`make import-pallet` writes to the ignored directory `build/gen1/pallet/`:

| File | Purpose |
| --- | --- |
| `pallet.json` | Extracted source data, exact input identity and source provenance |
| `report.json` | Geometry counts, passability, generated building bounds and feature coverage |
| `preview.svg` | Walking-grid diagnostic with blocked cells, NPCs, warps and spawn; not emulator output |
| `poke_pallet_scene_header.c`, `poke_pallet_scene.c` | Scene commands, spawn and collision |
| `poke_pallet_room_header.c`, `poke_pallet_room.c` | Room commands and render geometry |
| `poke_pallet_data.c` | Runtime content, including dialogue read from the supplied ROM |
| `manifest.json` | Source identity and SHA-256 hashes of generated files |

Given the same supported ROM and converter code, these files are deterministic. No timestamps or machine paths enter the contents. Repeating a conversion preserves unchanged file timestamps. Output files are replaced individually through temporary files, and symlink outputs are refused. An interrupted bundle can be regenerated; the manifest is written last.

ROMs, extracted assets, generated source, built images, local patches and saves stay outside Git. The JSON/text/scene outputs contain source-game data and belong with private build artifacts, not the converter's source files.

## Source references

The format reference is [pret/pokered at ba9c0568](https://github.com/pret/pokered/tree/ba9c0568f64ae602fadda577a08c66639f93082a):

- `macros/scripts/maps.asm` and `macros/coords.asm`: records, coordinate bias and warp-return displacements.
- `data/tilesets/tileset_headers.asm`, `home/overworld.asm`, `engine/overworld/player_state.asm`: bank selection, block expansion and collision sampling.
- `data/maps/objects/PalletTown.asm`, `data/maps/toggleable_objects.asm`: object and visibility formats.
- `scripts/PalletTown.asm`, `engine/overworld/auto_movement.asm`: state flow, conditional dialogue and movement streams.

Both Red and Blue addresses were checked against the [symbols branch at c88672bb](https://github.com/pret/pokered/tree/c88672bb44df548ac21d7f6651047ffc43fd3750). The extractor records that immutable reference and each symbol-file blob SHA in its output. The converter needs neither checkout at run time.

## Verification

```sh
make test
make sanitize
python3 tools/check_native.py --require-mips --oot-conversion --engine build/engine-oot
```

Synthetic tests exercise the banked format, all cell quadrants, pointer bounds, malformed records, strict version checks, text controls, visibility, and movement ordering. End-to-end tests change an invented ROM map byte and verify that actual scene geometry and collision change. Generated content is compiled and accepted by the portable C runtime. Runtime tests cover interaction direction, multi-page text, walking bounds, the Oak event, path failures and unsupported lab completion.

Build tests check read-only external ROM mounts, validation before engine writes, explicit resident linkage, unchanged-file timestamps and restoration of the default stub when switching modes. Sanitizers check portable memory handling. Native compilation verifies the actual pinned HackerOoT interfaces and big-endian MIPS object generation.

These checks do **not** establish a successful extraction from a real user ROM, a linked imported ROM, an emulator playthrough or hardware performance. Those remain the next live checks when the supplied inputs and emulator are available.

### Checks completed for this branch

- `make test`: passed after integrating the five-room opening, including 181 Python tests, four portable C suites and the console journey test. The opening suite completes 96 journeys across all three starters and both rival outcomes.
- ASan/UBSan: passed with `ASAN_OPTIONS=detect_leaks=0 make sanitize`. LeakSanitizer cannot run under this workspace's process tracing; address and undefined-behavior checks ran. The added portable runner has no heap allocations.
- Real MIPS object compilation: passed against pinned HackerOoT for the full five-room default mode and generated synthetic imported scene/data, including the shared Red renderer. Objects were confirmed ELF32 big-endian MIPS-III.
- Source-data cross-check: the pinned Pallet map/blockset produces three rectangular buildings, 221 passable cells, 2,490 visual triangles and 394 collision polygons. A host driver using this reference collision grid and synthetic dialogue completed the escort from both north exit cells without crossing blocked cells or setting the lab-entered flag. This was not a ROM or emulator run.
