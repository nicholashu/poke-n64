# Red/Blue ROM-driven opening: Pallet Town through the first rival fight

`feat/pallet-rom-converter` is a user-ROM import stage for the existing
HackerOoT N64 game. It reads data from a verified Pokémon Red/Blue cartridge,
translates it into native C/scene resources, and reuses the existing five-area
opening, OoT movement/rendering and optional private Stadium model pipeline.

**Status: draft and not yet tested with a real Game Boy ROM in this workspace.**
No extracted copyrighted content is committed. Authoring rules and verified
format/symbol addresses live in the source; actual game data is read locally.

## Build and play

```sh
# Use an absolute path to the user-supplied, unmodified ROM.
make import-pallet POKEMON_ROM="/absolute/path/Pokemon Red.gb"

make rom-pallet-docker \
  ROM="/absolute/path/Ocarina of Time US 1.2.z64" \
  POKEMON_ROM="/absolute/path/Pokemon Red.gb"

python3 tools/play_oot.py --rom build/poke-n64-pallet.z64
# Or: make play-pallet
```

The importer only needs Python 3 and the GB ROM. The N64 build additionally
needs the existing Zelda US NTSC 1.2 ROM and supported Docker/MIPS toolchain.
The original source files are never modified. ROM paths are mounted read-only
into Docker; generated content is ignored by Git. The output is
`build/poke-n64-pallet.z64`. The ordinary `make rom-oot-docker` remains the
hand-authored, ROM-free test build.

```sh
# Strict ROM verification and conversion without writing outputs:
python3 tools/pallet_rom.py --rom "/absolute/path/Pokemon Red.gb" --check

# Native fresh-session full opening test, once compiled and locally available:
make test-pallet-opening STARTER=bulbasaur
```

## Supported cartridges

Only these exact **English, unmodified 1 MiB** Red/Blue images are supported:

| Edition | SHA-1 |
| --- | --- |
| Red | `ea9bcae617fdf159b045185467ae58b2e4a48b9a` |
| Blue | `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2` |

Both full SHA-1 and cartridge header/global checksums are validated. Modified
ROMs, Yellow, translations and unsupported revisions fail rather than falling
back to guessed offsets.

## What actually comes from the source cartridge?

| Source system | Extracted | Remaining translation/limitation |
| --- | --- | --- |
| Five maps | Pallet Town, Red's 2F and 1F, Blue's house, Oak's lab; block IDs, tile graphics IDs and static walking collision | 3D props and furnishings still use our art interpretation and are **not** extracted models |
| Scene transitions | Original map warp destinations and object records | N64 entrance/spawn mapping is a known-version adapter |
| People/signs | Object IDs, positions, sprite IDs, visibility toggles and sign positions | Custom N64 models; script-driven object movement/visibility not universally translated |
| Dialogue | Original Pallet signs/NPCs, house, lab, starter, Oak and rival passages at verified symbol offsets | `TX_START` and simple `TX_FAR` only. `text_asm` calls need explicit adapters. Some background interactions remain unsupported |
| Text presentation | Source bytes and original player/rival tokens | ASCII conversion, 2x36 pagination and source-passage splitting for our N64 UI |
| First battle data | Supported species' base stats, types, catch rates, base XP, initial moves; supported moves' type/power/accuracy/PP | Battle **mechanics** remain our simpler C interpreter; later level-up learnsets, status/effects and full move coverage not yet converted |
| Opening story | Source-derived event states and trigger interpretation (Oak, Lab, starter, first rival fight) | Explicitly authored C adapters for GB assembly, not a general GB bytecode or CPU translator |

The import path never deliberately uses the hand-written dialogue of
`src/intro.c` for an unavailable mapped text interaction. However, this does
not mean every original interaction has an equivalent: missing adapters may
result in no dialogue until implemented. The normal authored build is retained
for comparison and for tests without a Pokémon ROM.

## Implementation

- `tools/gen1_rom.py` identifies ROM revisions, parses banked map headers and
  five areas' tilemaps, passability, warps, sign/NPC records and map visibility.
- `tools/opening_rom.py` looks up verified disassembly symbol addresses and
  decodes the corresponding source-cartridge dialogue, including distinct
  starter and win/loss branches.
- `tools/battle_rom.py` extracts the five supported Pokémon species and nine
  supported moves. It generates replacement data tables and initial move lists
  for the native core. Unsupported move/type data fails explicitly.
- `tools/pallet_rom.py` generates Pallet's exterior scene, collision, private
  text and object C tables, plus a JSON manifest and SVG walking-grid preview.
- `tools/kanto_layout.py` generates native playable collision/warp/object/sign
  data from all five maps in import mode; in ROM-free mode it retains fixtures.
- `tools/pallet_town.py` uses imported interior passability for collision but
  continues to draw our original low-poly furniture and environment.
- `src/intro.c` implements known opening story transitions, ROM-backed
  interaction lookup and paginated text. `native/oot_conversion.c` renders
  imported NPC positions and the existing battle UI/actors.
- `tools/bootstrap.py` installs the generated overlay into a pinned,
  independent HackerOoT checkout before linking the separate imported ROM.

All five maps use **80 N64 world units per walking cell**, centred with GB X
mapped to world X, GB Y mapped to world Z and world Y reserved for height.

## Generated private output

`make import-pallet` writes under ignored `build/gen1/pallet/`:

| Artifact | Meaning |
| --- | --- |
| `pallet.json` | Parsed source content, including all five room records, dialogue and battle data |
| `preview.svg` | Outdoor map/walking-grid diagnostic (not an emulator screenshot) |
| `report.json` | Geometry budgets and explicit converter coverage |
| `poke_pallet_scene_header.c`, `poke_pallet_scene.c` | Native scene and static collision |
| `poke_pallet_room_header.c`, `poke_pallet_room.c` | Native render geometry |
| `poke_pallet_data.c` | Source-derived NPC/sign/dialogue runtime tables |
| `manifest.json` | Original image hashes and deterministic generated-file hashes |

Native builds also generate the imported five-room collision/warp tables and
replace the supported Pokémon data tables in a private engine worktree.
Changing source bytes in tests changes emitted data. Generation doesn't commit
or upload any original game text, graphics or ROM bytes.

## Reference and fidelity constraints

Sources: [pret/pokered pinned disassembly](https://github.com/pret/pokered/tree/ba9c0568f64ae602fadda577a08c66639f93082a),
plus [verified Red and Blue symbol files](https://github.com/pret/pokered/tree/c88672bb44df548ac21d7f6651047ffc43fd3750).

- `constants/map_constants.asm`, `data/maps/map_header_banks.asm` and
  `data/tilesets/tileset_headers.asm`: map index, bank and block layout.
- `data/maps/objects/*.asm`, `data/maps/toggleable_objects.asm`: warps and NPCs.
- `scripts/PalletTown.asm`, `scripts/OaksLab.asm`,
  `scripts/RedsHouse1F.asm`, `scripts/BluesHouse.asm`: event adapter references.
- `data/pokemon/base_stats/*.asm`, `data/moves/moves.asm`:
  the cartridge battle tables.
- `text/*.asm`, `home/text.asm`: GB text formats and named speech pointers.

Original GB assembly routines are **not** automatically executable in the
HackerOoT engine. This version implements the opening sequence with
hand-written state adapters but takes the data itself from the user ROM.
It is an incremental compiler, not a full executable converter.

## Validation and next checks

```sh
make test
make sanitize
python3 tools/check_native.py --require-mips --oot-conversion --engine build/engine-oot
```

Synthetic ROM tests cover version rejection, source-offset decoding, changed
dialogue/map/stat bytes, native source generation, and C runtime compatibility.
Other tests verify the original five-room opening and independent native MIPS
compilation without distributing a ROM.

Still necessary before treating the imported result as working:
1. Run `--check` and the real import using an authentic supported Red/Blue ROM
   in the user's environment. Resolve unsupported real text/control sequences
   and map assumptions based on **actual** ROM evidence.
2. Link `poke-n64-pallet.z64` with the user's Zelda and private Stadium data.
3. Run the scripted bedroom-to-rival E2E in ParaLLEl N64, including both battle
   results, dialogue pages, collision and all map transitions.
4. Address remaining source parity: exact Oak movement, dynamic ASM text,
   original battle rules, level-up moves, saves and original event progression.
