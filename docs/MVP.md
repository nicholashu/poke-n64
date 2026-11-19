# MVP specification and delivery record

## Goal

Prove one repeatable Pokémon RPG loop on a Nintendo 64 engine: choose a starter, explore a small 3D area, enter a wild encounter, fight or catch, heal, save, restart and continue. This milestone is the systems foundation for a later Red/Blue recreation, not a claim that Kanto is complete.

## Native integration decision

The slice adds a dedicated resident `PokeState` to HackerOoT. The engine supplies boot, scheduling, controller polling, display-list submission, camera/view math, font drawing and cartridge I/O. The project owns its test-map collision, character proxies, battle menus and persistent state.

This avoids coupling the first battle system to Zelda's combat, player actor, pause menu and file-select save layout. It also means the initial test area is generated directly from the shared tile map; a Fast64 scene and imported Stadium models remain later work. No stock Zelda save initializer or file selector is entered after the common in-memory setup.

## Scope and acceptance

| Feature | Acceptance | Evidence in initial delivery |
| --- | --- | --- |
| Starter | One starter only, three choices, party and supplies initialized once | Host rules and input tests |
| Movement | Collision respects character radius, grass rolls only after actual movement | Host tests; native adapter compiled |
| Encounters | Wild Pidgey/Rattata, correct field/battle transitions | Deterministic journey and CLI tests |
| Turns | No repeated action from held A; invalid actions spend nothing; fainted actors never attack | C tests |
| Capture | Successful capture adds once, failed throw spends once, party cannot exceed six | C tests and CLI journey |
| Party | Lead selection, voluntary switch costs a turn, forced replacement does not | C tests |
| Recovery | Healing restores HP/PP; total defeat returns to a safe location | C tests and CLI journey |
| Progression | XP awarded once, level growth and elemental move learning | C tests |
| Persistence | Explicit byte format, corruption/bounds rejection, load failure leaves state unchanged | C tests and CLI restart |
| Native build wiring | Core and adapter in resident linker segment; Poke state registered and booted | Actual MIPS object compilation of project and modified hooks |
| Native runtime | 3D presentation, controller interaction and cartridge save reload | **Pending ROM link and emulator playthrough** |
| Hardware target | Works with 8 MiB on a real N64 | **Pending hardware test** |

## Rules contract

- Five species: Bulbasaur, Charmander, Squirtle, Pidgey and Rattata.
- Three level-5 starters; wild levels 2–4.
- Four move slots, six party slots. No PC box in this slice.
- Deterministic xorshift32 RNG, saved with progress. Native new games seed from `osGetTime`; console seed defaults to 1.
- Movement uses fixed integer coordinates, 256 units per map tile, 32 per cardinal update. Diagonal steps use approximately the same speed. Only actual displacement advances encounter distance.
- Grass encounter check: 22% per traversed tile, with three tiles of grace after a battle.
- Wild encounters choose Pidgey/Rattata equally; levels 2–4 equally. These are prototype tables, not extracted Red/Blue route tables.
- Battle actions resolve immediately in the rules core; the display reads the resulting HP and messages. Presentation animation does not drive game rules.
- All species use `level^3` XP thresholds, up to level 100. No EV/stat experience, natures or abilities.
- Stats use the original style of level scaling with fixed DV 8. The limited move data includes Gen 1 Tackle power 35/accuracy 95/PP 35.
- Damage uses integer arithmetic, physical/special stat selection by type, STAB, limited dual-type effectiveness, 85–100% variance and flat 1/16 critical hits.
- Capture threshold: `(3*maxHP - 2*HP) * catchRate / (3*maxHP)`, clamped to 16–245 out of 256. No capture XP. This is deliberately simpler than Red/Blue's algorithm.
- Escape succeeds if the player is at least as fast, the battle has reached its third turn, or a 3-in-4 roll succeeds. An unsuccessful attempt permits the enemy action.
- Healing raises balls to at least five and Potions to at least three. This is a testing convenience, not final economy design.

## Persistence contract

The shared v1 save is exactly 256 bytes. `src/save.c` documents field offsets and byte order. It includes RNG, position, movement accumulator, inventory, progress, species masks, active index and six explicitly encoded Pokémon records. A trailing CRC32 covers the preceding 252 bytes. Reserved bytes must be zero.

The loader verifies version, exact size, CRC, party capacity, species and moves, level/XP relationship, derived stats, PP/HP bounds, masks, flags and safe collision placement. It decodes into a temporary structure and only replaces the live game after validation. Transient enemy, menu, log, input and battle state are reset. Saving during battle is disallowed.

The console saves through a temporary file and atomic rename. The native adapter owns two 512-byte SRAM records containing the shared save, a generation counter and an outer checksum. It writes the alternate record, reads it back and checks every byte before reporting success. On load it selects the newest valid record. Cartridge power-loss behavior remains a hardware/emulator validation item.

## Validation gates

1. `make test`: shared core, save contract and a command-driven full journey.
2. `make sanitize`: address and undefined behavior checks for the C tests.
3. `python3 tools/check_native.py --require-mips`: six real target object files against the pinned upstream headers, including modified boot/dispatcher/table code.
4. Full ROM build with the exact supported base image. **Input not supplied for initial delivery.**
5. Emulator journey, video/HUD inspection, repeat battles and save across emulator restart.
6. Real console journey and SRAM recovery test with an Expansion Pak.

The first three gates do not imply the last three passed. CI intentionally does not use copyrighted ROM inputs.

## Next work, in order

### 1. Run the native slice

Supply the supported base ROM locally, build the image, then verify boot, controls, geometry, text legibility, battle outcomes and save reload in an F3DEX3-capable emulator. Record emulator/version/configuration and test results. Fix native issues before expanding content.

### 2. Prove one animated Stadium import

Extract one model from a user-provided Stadium image; document source version and conversion. Convert geometry/materials, skeleton hierarchy and one idle animation into a verified OoT-compatible representation. Confirm bounds, texture formats, winding, coordinate conventions, skinning and memory usage on the target. Add attack/hit/faint clips only after idle works. Do not treat a model inspector as a ready-made exporter.

### 3. Replace the test area with authored Pallet Town

Create Red, Oak, houses and a route section using Fast64 and original/authenticated local inputs. Add scene collision, transitions, a readable camera and NPC interactions while retaining the tested rules core. Profile native frame time and memory with actual models.

### 4. Finish the first story slice

Add a rival/trainer battle, route trainers, encounter-table data, money/items, progression flags and a small story script system. Then PC storage, evolution and learnset choices. Give each new mechanic a targeted regression test.

### 5. Expand only after the pipeline is repeatable

Build the first gym journey, broaden species/moves and import more assets in batches. Explicitly decide whether to reproduce Gen 1 bugs or use corrected rules before calling the game faithful. Full Kanto, 151 species, trading and link compatibility are separate milestones.

## Explicitly unfinished

No complete ROM or emulator recording is included. No Stadium/Snap mesh converter, skeletal animation, battle effects, sound, full Red/Blue maps/scripts, trainers, evolutions, storage boxes, trading or multiplayer exists in this milestone. These are tracked above rather than hidden behind stub APIs.
