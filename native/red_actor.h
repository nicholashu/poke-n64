#ifndef POKE_RED_H
#define POKE_RED_H
#include "play_state.h"
#include "gfx.h"
enum { MODEL_RED, MODEL_BLUE, MODEL_OAK, MODEL_MOM, MODEL_DAISY,
       MODEL_GIRL, MODEL_SCIENTIST, MODEL_FISHER };
void PokeRed_HideLinkLimb(PlayState* play,Gfx** dList);
void PokeModels_DrawHuman(GraphicsContext* gfx,s32 kind,f32 phase,f32 amount);
void PokeModels_DrawPokemon(GraphicsContext* gfx,s32 species);
void PokeRed_Setup(GraphicsContext* gfx);
#endif
