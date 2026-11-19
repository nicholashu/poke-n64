# Battle Presentation: Pokémon Stadium on Nintendo 64

**Status:** battle presentation scaffolding implemented; official Stadium assets and move animation library not yet imported.

## Design intent

The **overworld** uses an Ocarina of Time-style third-person camera. A wild Pokémon or trainer battle switches to a **separate, Pokémon Stadium-inspired scene**. This is a 3D turn-based Pokémon RPG, not real-time Zelda combat and not a flat Pokémon Red battle viewport.

Red/Blue's battle rules remain authoritative. Stadium is the reference for characters, perspective, staging, animation timing and sound design.

## Target battle loop

1. **Encounter transition:** field fades/swipes into a lightweight arena. Wild Pokémon gets an introduction shot; trainer throws a Poké Ball with a short camera cut.
2. **Idle:** both active Pokémon face each other on opposite sides of a 3D arena. Camera follows a subtle arc and idle animation, with small readable species/HP panels.
3. **Command selection:** Fight / Bag / Party / Run, then a four-move grid with PP and type. Inputs remain turn-based. No 3D combat physics.
4. **Move action:** camera moves to the attacker, play a species-appropriate attack action, display a move-specific effect, then cut to the defender's reaction and HP loss.
5. **Resolution:** status/XP/faint/switch transitions as appropriate; winning returns the player to the field at the same position and camera heading.
6. **Capture:** Poké Ball launch, impact, enclosure, shakes and catch/fail result with matching timing.
7. **Save continuity:** battle state is not serialized; overworld save format is unchanged.

## Camera behaviour

- **Field:** lower chase view behind Red; camera-relative analog/D-pad movement; Z recentres; temporary C-left/C-right orbit.
- **Battle:** independent arena camera with both Pokémon in frame, player in near foreground and opponent on the far platform.
- **Idle:** a small, slowly changing angle to add depth, without motion that makes menus hard to read.
- **Moves:** close shot of attacker and defender, returning smoothly to the baseline angle.
- **Future:** distinct opening, move, impact, faint and capture shot presets, with transitions that do not interrupt the turn-based rules.

## N64 implementation boundaries

- `src/core.c`: gameplay rules, turn resolution, encounters, item actions, statuses and damage. **No rendering code.**
- `native/poke_state.c`: current game-state adapter, scene drawing, battle camera and UI. Presentation is driven by rule-state transitions.
- `native/poke_state.h`: camera and animation timers, all native-only, not part of the portable cartridge save.
- Future asset pipeline: extract selected models and animations locally from the user's Stadium dump, convert geometry, materials and skeletons into OoT-compatible assets, then batch-import species progressively.

**Limitations of the current stage:** both Pokémon still use original proxy box geometry; the battle floor is a primitive mesh; attacks currently have no model-specific motion, contact effects, sound, or trainer throw animation. The camera and HP panels are Stadium-inspired, not an asset-accurate recreation.

## Next milestones and acceptance criteria

### B1. Playable stadium-style camera (current development slice)

- Normal field movement is behind the character, not overhead.
- Entering a battle changes to a stable two-Pokémon arena view.
- Idle characters have subtle independent motion.
- The menu, species labels and HP bars remain legible.
- Returning to the field restores the chase camera without moving the saved character position.

### B2. Import one real Pokémon

- Build a legal, local-only extractor for one Stadium species (prefer Rattata or a starter).
- Record texture, skeleton and animation conversion results.
- Replace its primitive box proxy in battle, not in the field.
- Maintain 30fps target and verify on accurate emulation.
- Never check in the user's Stadium ROM or extracted copyrighted data.

### B3. Animated move and capture slice

- Tackle: attacker wind-up, move toward opponent, hit reaction and return.
- Growl: sound/gesture and subtle debuff effect.
- Poké Ball throw, shake and capture/fail.
- Stadium-style camera cuts for all three actions.

### B4. Progression towards 151 species

- Reusable asset conversion tools, metadata tables and loading strategy.
- Per-species scale, pivot, front/back orientation and animation mapping.
- Battle arenas for routes, caves and trainer fights.
- Real hardware validation, frame timings and memory budgets.

## Non-goals for this milestone

Recreating Stadium's tournament modes, Pokémon from later generations, exact Stadium damage rules, multiplayer and fully modeled Kanto in a single release. The project stays focused on **Pokémon Red/Blue played in OoT-style Kanto, with Stadium-style battles**.
