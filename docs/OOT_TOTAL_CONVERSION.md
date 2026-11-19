# Pokémon Red 64: Ocarina of Time total conversion

**Architecture decision:** We are modding Ocarina of Time into Pokémon Red, **not** building a new RPG inside Zelda's render loop.

The original independently running `PokeState` prototype remains available while the native `PlayState` conversion is proven. It will be retired from the eventual game, not developed into a competing overworld engine.

## Game vision

- **Overworld:** Ocarina of Time third-person exploration, camera, movement, walls, rooms, doors, NPC interactions and character animations, rebuilt geographically as Kanto.
- **Battles:** Pokémon Stadium-inspired 3D presentation, using Pokémon Red/Blue turn rules and Pokémon Stadium models/animations converted locally.
- **Story/content:** Red/Blue's Kanto, Oak, starters, 151 Pokémon, gyms, rival, Team Rocket, badges and Pokédex.
- **Hardware:** native Nintendo 64 ROM built from a supported, user-supplied OoT cartridge dump. Expansion Pak required by current HackerOoT target.

## Which engine owns what

| Feature | Source of truth |
| --- | --- |
| Player position, velocity, collision, animations | OoT `Player` actor inside `PlayState` |
| Third-person camera and recentering | OoT `Camera` and scene collision |
| Rooms, scene loading, terrain and exits | OoT scene and room systems |
| NPCs, dialogue triggers and shops | OoT actors with Pokémon-specific scripts |
| Pokémon party, stats, types, turns, items | `src/core.c`, progressively adapted for the new world |
| Stadium battle presentation | OoT sub-cameras and new Pokémon battle actors |
| Saves | Planned Pokémon-specific format; do not conflate with OoT SRAM |
| Models and materials | Local asset extraction + conversion; never publish copyrighted dumps |

## Current foundation (experimental PR)

`make rom-oot-docker` is a separate opt-in ROM build. It:

1. Fetches the pinned HackerOoT code into its own `build/docker-engine-<arch>-oot` checkout.
2. Uses the original `PlayState` (including native player, camera, actors, rooms and collision).
3. Starts a fresh OoT-style child save and boots into **Kokiri Forest as a temporary engineering scene**. It does not enter the old standalone `PokeState`.
4. Calls `PokeOot_OnSceneEnter()`, `PokeOot_Update()` and `PokeOot_Draw()` from OoT's own lifecycle.
5. Shows an overlay identifying the conversion and allows starter selection with **L + C-left (Bulbasaur), L + C-up (Charmander), L + C-right (Squirtle)**. This is only a temporary debug input.
6. Tracks footsteps from the real OoT player actor, without calling `poke_walk()` or modifying the camera.
7. Emits `build/poke-n64-oot.z64` and `build/poke-n64-oot.bps`, leaving the original `make rom-docker` game untouched.

**Not implemented in this slice:** Red player model; custom Pallet scene; replacing Kokiri NPCs; encounters from world surfaces; battle scene transition; Stadium assets; persistent Pokémon saves. Those are separate milestones.

The boot and runtime path above has been compiled against real HackerOoT headers, but the final ROM still requires emulator verification with your own legal OoT NTSC 1.2 dump. Do not infer that a linked image has run on hardware.

## Cutover milestones

### M1. Native OoT play lifecycle

- Boot a native `PlayState` game without the custom `PokeState`.
- Player movement and native Z camera work on actual scene collision.
- Pokémon overlay and starter selection do not corrupt OoT input or camera controls.
- Run MIPS compilation plus emulator smoke test of scene transitions and restart.

### M2. Red actor and Pallet Town

- Convert an original Red model/animations to an OoT actor skeleton.
- Preserve OoT player animation and physics, remapping tunic/equipment behaviours to Pokémon actions.
- Export Pallet Town, Oak's lab, houses and collision through Fast64.
- Remove Kokiri placeholder and stock actors from the launch path.

### M3. Pokémon overworld systems

- Drive encounter steps using OoT player displacement and flagged grass/cave terrain.
- Pokémon actor-driven dialogue, trainer challenges, starter lab events, doors and scripted rival encounters.
- Change scene layouts and entrance table to match Kanto.
- Keep the portable combat engine independent of movement and camera.

### M4. Stadium-style encounters

- Enter a dedicated battle scene/room from an OoT overworld encounter.
- Use OoT **sub-cameras** for Stadium-style introduction, action, hit, faint and capture shots.
- Convert Stadium Pokémon geometry, materials, skeletons and animations one species at a time.
- Restore player location/camera consistently on battle exit.

### M5. Save and gameplay fidelity

- Separate Pokémon save layout (party, Pokédex, badges, story flags, money, items, Kanto location).
- Atomic/validated SRAM handling; game ID and emulator saves separate from OoT.
- Confirm type damage, encounter distributions, evolution, move learning, status and catching.
- Complete story loop; test on accurate emulation and original N64 hardware.

## Build and test

From this feature branch:

```sh
make test
make check-native-oot-docker
make rom-oot-docker
```

Open `build/poke-n64-oot.z64` using ParaLLEl N64/ares with an F3DEX3-compatible RSP setup. Choose separate emulator save storage for this image. The older prototype remains `make rom-docker` → `build/poke-n64.z64`.

### Failure diagnostics

- **Black screen at boot:** verify original OoT ROM checksum, `ROM verified` output and N64 emulator fault messages; startup `SaveContext_Init` and `Sram_InitNewSave` are a new boot path requiring emulator smoke testing.
- **Camera works but Pokémon overlay missing:** investigate `PokeOot_Draw` and the `Play_Main` hook.
- **Scene starts then crashes:** inspect player/actor initialization and the native game-state order. The conversion must never construct a fake `Player` or pass a pretend `PlayState` into `Camera_Update`.
- **Saves appear wrong:** do not load old Zelda or standalone Pokémon saves into the conversion; save compatibility and persistence are not delivered here.

## Distribution

Do not commit OoT or Pokémon Stadium ROMs, extracted copyrighted models, sound, textures or game data. Share source and BPS patches against appropriately sourced user dumps.
