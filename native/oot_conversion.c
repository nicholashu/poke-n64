/* Pokémon Red 64: first native OoT PlayState integration.
 *
 * This code runs INSIDE Zelda's own Play_Update / Play_Draw lifecycle. Its
 * player movement, camera, room transitions and collision remain untouched.
 * Kokiri Forest is a temporary engineering map, NOT a replacement for Kanto.
 *
 * The battle logic remains platform-independent in poke_core.c. This slice
 * deliberately does not start encounters until a Stadium-style scene bridge
 * exists. No proprietary Pokémon Stadium content is embedded in this file.
 */
#include "poke_oot.h"
#include "poke.h"
#include "player.h"
#include "controller.h"
#include "gfx.h"
#include "libu64/gfxprint.h"
#include "save.h"

/* Native bridge state persists across OoT room/scene loads. Not yet SRAM-
 * persisted: this first slice only validates the real OoT runtime integration.
 */
typedef struct {
    PokeGame game;
    Vec3f previous;
    f32 distanceSinceStep;
    s16 lastScene;
    u8 initialized;
    u8 havePrevious;
} PokeOotRuntime;

static PokeOotRuntime sPokeOot;

static f32 PokeOot_Abs(f32 value) {
    return value < 0.0f ? -value : value;
}

void PokeOot_OnSceneEnter(PlayState* play) {
    if (!sPokeOot.initialized) {
        /* Pokémon battle rules and party data, owned by our ROM conversion. */
        poke_init(&sPokeOot.game, (u32)osGetTime() ^ 0x504F4B45U);
        sPokeOot.initialized = 1;
    }
    /* OoT's actor position may have teleported between scene loads. */
    sPokeOot.havePrevious = 0;
    sPokeOot.lastScene = play->sceneId;
}

/* The OoT player actor, not poke_walk(), owns overworld movement and walls.
 * Keep Pokémon's step counter in sync with observed Zelda actor movement.
 */
void PokeOot_Update(PlayState* play) {
    Player* player = GET_PLAYER(play);
    Input* input = &play->state.input[0];
    Vec3f position;
    u16 held;
    u16 pressed;
    f32 dx;
    f32 dz;
    f32 travelled;

    if (player == NULL || !sPokeOot.initialized) return;
    position = player->actor.world.pos;
    if (!sPokeOot.havePrevious || sPokeOot.lastScene != play->sceneId) {
        sPokeOot.previous = position;
        sPokeOot.lastScene = play->sceneId;
        sPokeOot.havePrevious = 1;
    }

    dx = PokeOot_Abs(position.x - sPokeOot.previous.x);
    dz = PokeOot_Abs(position.z - sPokeOot.previous.z);
    sPokeOot.previous = position;

    /* Ignore teleports and cutscene moves. World tile collision/encounter
     * mapping will be supplied by our custom Kanto scene configuration. */
    travelled = dx + dz;
    if (travelled < 60.0f) {
        sPokeOot.distanceSinceStep += travelled;
        while (sPokeOot.distanceSinceStep >= 80.0f) {
            sPokeOot.distanceSinceStep -= 80.0f;
            if (sPokeOot.game.steps != 0xFFFFFFFFU)
                sPokeOot.game.steps++;
        }
    }

    /* Starter-picker proof of integration. L+C-left/up/right currently choose
     * a Pokémon. These are temporary debugging inputs, not the final UI.
     * Do not steal OoT's movement, Z-target or camera updates. */
    held = input->cur.button;
    pressed = input->press.button;
    if (!(sPokeOot.game.flags & FLAG_STARTER) && (held & BTN_L)) {
        u8 species = POKE_NONE;
        if (pressed & BTN_CLEFT) species = POKE_BULBASAUR;
        else if (pressed & BTN_CUP) species = POKE_CHARMANDER;
        else if (pressed & BTN_CRIGHT) species = POKE_SQUIRTLE;
        if (species != POKE_NONE) {
            sPokeOot.game.mode = MODE_STARTER;
            (void)poke_choose_starter(&sPokeOot.game, species);
        }
    }
}

void PokeOot_Draw(PlayState* play) {
    GraphicsContext* gfx;
    GfxPrint printer;

    if (!sPokeOot.initialized) return;
    gfx = play->state.gfxCtx;

    OPEN_DISPS(gfx);
    gSPSegment(OVERLAY_DISP++, 0, 0);
    GfxPrint_Init(&printer);
    GfxPrint_Open(&printer, OVERLAY_DISP);
    GfxPrint_SetColor(&printer, 255, 229, 155, 255);
    GfxPrint_SetPosPx(&printer, 16, 10);
    GfxPrint_Printf(&printer, "POKEMON RED 64 / OOT PLAYSTATE");

    GfxPrint_SetColor(&printer, 244, 239, 219, 255);
    GfxPrint_SetPosPx(&printer, 16, 22);
    if (!(sPokeOot.game.flags & FLAG_STARTER)) {
        GfxPrint_Printf(&printer, "L+C-LEFT BULB  L+C-UP CHAR  L+C-RIGHT SQUIRT");
    } else {
        const PokeMon* starter = &sPokeOot.game.party[0];
        GfxPrint_Printf(&printer, "%s L%u  PARTY %u/6  STEPS %u",
                         poke_species(starter->species)->name, starter->level,
                         sPokeOot.game.party_count, sPokeOot.game.steps);
    }

    GfxPrint_SetColor(&printer, 225, 229, 230, 255);
    GfxPrint_SetPosPx(&printer, 16, 216);
    GfxPrint_Printf(&printer, "NATIVE ZELDA PLAYER + CAMERA  |  TEST SCENE %d", play->sceneId);
    OVERLAY_DISP = GfxPrint_Close(&printer);
    GfxPrint_Destroy(&printer);
    CLOSE_DISPS(gfx);
}
