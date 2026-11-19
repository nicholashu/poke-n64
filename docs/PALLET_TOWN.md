# The first playable area

The native total conversion now starts in **Red's bedroom** and implements the Pallet Town introduction through the first Blue battle and return outside. `src/intro.c` holds portable story logic; `native/oot_conversion.c` connects it to actual OoT player physics, collision, room loading, cameras and drawing.

## Map fidelity

Reference: [pret/pokered ba9c0568f64ae602fadda577a08c66639f93082a](https://github.com/pret/pokered/tree/ba9c0568f64ae602fadda577a08c66639f93082a). Coordinates below are zero-based **16-pixel movement cells**, with x east and z south. Each cell becomes 80 native world units. These are semantic data and original 3D meshes, not copied Game Boy textures.

| Area | Cells | Static passable cells | Native segment slot |
| --- | --- | ---: | --- |
| Pallet Town | 20 × 18 | 221 | `spot04` |
| Red's bedroom | 8 × 8 | 47 | `kokiri_home` |
| Red's downstairs | 8 × 8 | 49 | `kokiri_home3` |
| Blue's house | 8 × 8 | 45 | `kokiri_home4` |
| Oak's lab | 10 × 12 | 83 | `kokiri_home5` |

All five static cell grids match the pinned original reference. Pallet's ordinary connected walking area has 207 cells; 14 other passable cells are isolated along the original northern border. Dynamic NPC occupancy is separate.

### Outdoor landmarks

| Feature | Original cells |
| --- | --- |
| Red's house | x4–7, z3–5; door (5,5) |
| Blue's house | x12–15, z3–5; door (13,5) |
| Oak's lab | x10–15, z8–11; door (12,11) |
| Four signs | (3,5), (11,5), (7,9), (13,13) |
| Fences | z9 x4–6; z13 x10–12 and x14–15 |
| Flower beds | x4–7/z10–11; x10–13/z14–15; walkable |
| Water | x4–7/z14–17; blocked on foot |
| North grass opening | x10–11/z0–1; Oak intercepts at z1 |

The earlier invented crossroads and tall perimeter trees have been replaced. Original ground-pattern positions drive sparse grass and flower detail; the border uses low rounded obstacles. There are no random wild encounters in Pallet's northern grass.

### Interiors

Bedroom furniture includes the PC, desk, TV, console, bed and plant in the reference locations. Both home floors connect through stairs at (7,1). Downstairs exits at (2,7)/(3,7) return to Red's house; Mother stands at (5,4). Blue's room contains Daisy at (2,3) and the original table arrangement.

The lab's shelves preserve the two-cell aisle x4–5 through rows z6–7. Starter balls are at (6,3), (7,3), (8,3); Oak stands at (5,2) and Blue initially at (4,3). Exits at (4,11)/(5,11) return to the lab door outside. Chairs and the cells below table artwork remain passable, as in the original.

## Opening state flow

1. **Wake.** Red appears lying on the bed. A starts the short get-up animation and restores control beside it. This adapts the original standing start at (3,6); the wake spawn is (1,6).
2. **Explore.** Stairs, both houses and the lab are enterable. The PC has one optional Potion. Mother and Daisy have introductory dialogue. Entering the lab early cannot grant a starter or skip Oak.
3. **Oak warning.** Reaching the north grass at x10/11,z1 stops the player. A begins the escort.
4. **Escort.** The player follows the original passable route `(10,2) -> (10,7) -> (9,7) -> (9,12) -> (12,12) -> (12,11)`. The native scene transition then enters the lab at the welcome position.
5. **Choose.** Face any ball and press A. The name and confirmation are shown; B cancels. Trying to leave before choosing produces Oak's reminder and returns the player one cell north.
6. **Blue chooses.** He receives the type-advantage counterpart; those two balls disappear and the third stays.
7. **Challenge.** Walking down the lab's central aisle to z6 triggers the rival battle.
8. **Finish.** Win or lose, the first battle advances, restores the party's HP and PP without granting supplies, removes Blue and lets Red leave the lab.

| Player's ball | Player starter | Blue's starter | Initial moves |
| --- | --- | --- | --- |
| Left, (6,3) | Charmander | Squirtle | Scratch / Growl |
| Middle, (7,3) | Squirtle | Bulbasaur | Tackle / Tail Whip |
| Right, (8,3) | Bulbasaur | Charmander | Tackle / Growl |

Trainer battles reject running and capture without consuming a turn or item. Losing this fight does not invoke the prototype's wild-battle blackout/teleport. The normal shared combat simplifications still apply; see the README's XP/stat limits.

## Native implementation

Each map replaces its actual scene and room payloads. The internal Zelda scene IDs are retained to preserve upstream tables and DMA ordering; their original world geometry is not loaded in these five areas. The two other Kokiri room slots contain empty self-contained headers.

`tools/pallet_town.py` emits:

- A separate scene-header object and scene-body object.
- A separate room-header object and room-body object.
- Native floor triangles for every passable cell and inward-facing walls only at blocked edges.
- Static vertex-colored display lists in batches of at most 30 vertices.
- Idle player spawns and the correct spawn-list command ordering.

The linker spec places command headers first. The full build validates all **ten** scene/room header addresses against their segment starts. This guards the segment-zero bug that an object-only compile cannot catch.

The player uses native physics. D-pad directions are converted into camera-relative stick input to produce world north/south/east/west; the analog stick keeps native camera-relative behavior. Scene spawns are resolved before player/camera initialization. Story state is resident across scene unloads. Interiors use a north-facing cutaway camera, and battles temporarily use a separate subcamera.

Red's original procedural rig replaces Link's visible display lists while retaining the native limb callback structure. Navi's allocated actor remains valid for upstream pointers, with behavior/drawing disabled and its normal destructor retained. Normal custom HUD drawing is omitted during native room fades.

## Art

All geometry is authored in Python source. Red is 490 rendered triangles, including both arms and both legs. The renderers use vertex colors and no imported Red textures. His cap, vest, jeans, backpack and sneakers follow the requested Gen 1 visual direction.

Original low-poly Oak, Blue, Mother, Daisy, neighbors and aides are included. Bulbasaur uses a privately extracted Stadium model when present; all three starters also have original fallback meshes, and the post-opening Rattata debug encounter has its own mesh.

`python3 tools/preview_opening.py` writes labelled source-mesh previews for inspection. These are not emulator evidence.

## Verification and limits

`make test` runs 96 complete portable story journeys across the three starters and 32 seeds each. Both win and loss paths are exercised. Additional cases cover cancel/reselect, facing-based ball interactions, PC inventory capacity, early lab entry/exit, both Oak columns and warp rearming. Geometry tests verify pinned collision fingerprints, floors/wall normals, landmarks, spawn data and RSP limits. `make sanitize` checks the C suites with ASan/UBSan. The native check compiles real MIPS objects against the pinned engine.

The controller-driven test is `make test-opening`; `OPENING_ARGS=--all-starters` performs three fresh runs. It verifies the running ROM's state from screenshots. **The new opening has not yet been linked and run in the available cloud workspace.** Previous successful native smoke tests belong to the earlier outdoor scene.

The map grids match the original, but the current introduction is not an exact reproduction of every animation or mechanic: Oak's approach and indoor arrival are abbreviated, Blue's selection/departure is abbreviated, wandering residents are stationary, original dialogue is paraphrased, and the new bed animation is an addition. The shared battle core still uses cubic growth, so the original first-battle level-up is not yet reproduced. Story progress is not persisted to SRAM. Routes 1/21 and later gifts/events are outside this area.
