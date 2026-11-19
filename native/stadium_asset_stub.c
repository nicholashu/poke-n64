/* Copyright-free fallback for CI and builds without a local Stadium export.
 * Real model data is generated into ignored assets/private/stadium/001/.
 */
#include "stadium_asset.h"

s32 PokeStadium_AssetAvailable(void) { return false; }

void PokeStadium_DrawBulbasaur(GraphicsContext* gfx, s32 attack, u32 ticks) {
    (void)gfx;
    (void)attack;
    (void)ticks;
}
