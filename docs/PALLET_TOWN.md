# Pallet Town native OoT scene, v0.1

This is the first **actual map replacement** in the OoT total conversion. Link
remains the temporary character, and OoT's Player actor, follow camera,
collision engine, skybox, room loader and controller handling remain native.

The scene uses the original **SCENE_KOKIRI_FOREST entrance ID** only as a
temporary mapping to avoid rewriting scene/entrance registries prematurely.
The ROM segments originally holding Kokiri Forest's scene and room 0 now point
to **new, original Pallet Town data**. No Kokiri geometry or cutscene is loaded
by this scene slot.

## Map contents

- Red's house, left side of the town, with a red roof
- Rival's house, right side, with a blue roof
- Professor Oak's laboratory at the northern end, with a purple roof
- A north-south road, crosswalk to the two houses and northern Route 1 approach
- A southern water edge, clustered trees, white fences, signs and grass strips
- Flat world floor plus **native OoT collision** for houses, tree trunks and
  world boundaries
- Child Link starts on the south side looking north into Pallet Town
- Bulbasaur's test model stays at a fixed point near spawn instead of
  floating directly in front of Link as he moves

**Limitations:** Geometry is original, simple vertex-colored N64 geometry,
not a fully textured Red/Blue map remake. Doors are decorative and do not
transition indoors yet. No Oak NPC or scripted events. Route 1 is visually
indicated but its north boundary does not change scenes yet.

## Build

On the \`feat/pallet-town-native-scene\` branch:

\`\`\`sh
git fetch origin
git switch feat/pallet-town-native-scene

# Reuse your previously extracted compatible Pokémon Stadium Bulbasaur.
# This command is only necessary if the native C asset is not generated yet.
make stadium-n64

make rom-oot-docker
\`\`\`

Open \`build/poke-n64-oot.z64\` in ParaLLEl N64 with F3DEX3-compatible
graphics. A working original OoT US NTSC 1.2 dump is required.

This branch includes incremental build improvements. The first build in a
fresh engine directory extracts OoT; subsequent builds preserve those files,
compile only changed sources and relink/recompress as required.

## Technical details

The renderer and collision use two source generators in
\`tools/pallet_town.py\`:

- \`scene_source()\` writes a native \`SceneCmd\` array, actual
  \`CollisionHeader\`, collision polygons, room list, spawn and lights.
- \`room_source()\` writes an OoT \`RoomShapeNormal\`, static F3DEX3 display
  lists and shaded geometry, batched to the N64's 32-vertex RSP limit.

\`tools/bootstrap.py\` replaces only the **spot04 scene and room 0 object
references** in \`spec/scenes_n64.inc\`. It preserves the existing scene ID
and generates new \`src/code/poke_pallet_scene.c\` and
\`src/code/poke_pallet_room.c\` inside the isolated HackerOoT checkout.

The new scene uses custom linker segment payloads, not a fake overworld
drawing on top of Kokiri. The native camera obtains the scene collision
from the usual OoT scene loader.

The generated assets and tests are copyright-free. Existing OoT assets not
reachable from this scene remain in the overall ROM for now, because safely
trimming the scene registry is separate work.

## Verification

\`tests/test_pallet_town.py\` verifies the geometry, original landmarks,
world bounds, floor normals, collision indices, native scene commands and
RSP vertex budget without any user ROM. Native MIPS checks compile both
generated scene and room against HackerOoT headers.

**Actual runtime:** The new scene still needs testing in ParaLLEl and then
on N64 hardware. Source compilation alone does not establish ROM linkage,
segmented pointer relocation, camera behavior or collision at runtime.

## Follow-up milestones

- Detailed Pallet Town geometry/textures from the Red/Blue layout
- Real home/lab doors and indoor rooms, dialogue and Professor Oak
- Link → animated Red model replacement, while retaining OoT's player physics
- Route 1 as a connected OoT scene, with world-material wild encounters
- Finished Stadium battle staging and species actor framework
