#ifndef POKE_STADIUM_ASSET_H
#define POKE_STADIUM_ASSET_H

#include "gfx.h"
#include "ultra64.h"

/* Implemented by the local, private Stadium model generator when available.
 * Otherwise the compiled test ROM links a no-op public fallback. */
s32 PokeStadium_AssetAvailable(void);
void PokeStadium_DrawBulbasaur(GraphicsContext* gfx, s32 attack, u32 ticks);

#endif
