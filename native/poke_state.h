#ifndef POKE_STATE_H
#define POKE_STATE_H

#include "game.h"
#include "view.h"
#include "poke.h"

/* Resident game state. The Pokémon data survives frames, never an actor overlay. */
typedef struct PokeState {
    GameState state;
    View view;
    PokeGame game;
    u32 saveGeneration;
    s32 saveSlot;
    s32 drawBoxes;
    s32 bootSplash;
} PokeState;

void Poke_Init(GameState* state);
void Poke_Destroy(GameState* state);

#endif
