#ifndef POKE_PALLET_NATIVE_H
#define POKE_PALLET_NATIVE_H

#include "play_state.h"

s32 PokePalletNative_Enabled(void);
s32 PokePalletNative_InputLocked(void);
void PokePalletNative_OnSceneEnter(PlayState* play);
void PokePalletNative_Update(PlayState* play);
void PokePalletNative_Draw(PlayState* play);

#endif
