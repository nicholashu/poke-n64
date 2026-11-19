#ifndef POKE_OOT_H
#define POKE_OOT_H

#include "play_state.h"

/* Pokémon Red total-conversion bridge to OoT's real PlayState.
 * Never allocates a second player, view, camera, or collision context. */
void PokeOot_OnSceneEnter(PlayState* play);
void PokeOot_Update(PlayState* play);
/* Stops OoT player movement only during the temporary turn-based battle test. */
s32 PokeOot_BattleActive(void);
void PokeOot_Draw(PlayState* play);

#endif
