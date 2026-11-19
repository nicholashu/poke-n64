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
    /* Native-only OoT-style chase camera. Never serialized into Gen 1 saves. */
    f32 cameraYaw;
    f32 playerYaw;
    f32 cameraFocusX;
    f32 cameraFocusZ;
    f32 cameraDistance;
    f32 movementBasisYaw;
    s32 movementActive;
    s32 orbitHoldFrames;
    s32 cameraIdleFrames;
    s32 cameraReady;
    s32 battleFrames;
    s32 battleActionFrames;
    u16 seenTurns;
    u8 wasInBattle;
} PokeState;

void Poke_Init(GameState* state);
void Poke_Destroy(GameState* state);

#endif
