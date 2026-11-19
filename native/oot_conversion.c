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
#include "stadium_asset.h"
#include "sys_matrix.h"
#include "z_lib.h"
#include "view.h"

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
    u32 modelFrame;
    u8 attackFramesRemaining;
    s16 battleCameraId;
    Vec3f battleAnchor;
    u16 previousTurns;
} PokeOotRuntime;

static PokeOotRuntime sPokeOot;

s32 PokeOot_BattleActive(void) {
    return sPokeOot.initialized && poke_in_battle(&sPokeOot.game);
}

static u16 PokeOot_BattleInput(const Input* input) {
    u16 b = input->cur.button;
    u16 keys = 0;
    if (b & BTN_A) keys |= KEY_A;
    if (b & BTN_B) keys |= KEY_B;
    if (b & BTN_DUP || input->cur.stick_y > 24) keys |= KEY_UP;
    if (b & BTN_DDOWN || input->cur.stick_y < -24) keys |= KEY_DOWN;
    return keys;
}

/* Only Pokémon turn rules run while OoT's world update is suspended.
 * Battle camera is a real OoT sub-camera, not a simulated tracking camera.
 */
static void PokeOot_EnterBattle(PlayState* play, Player* player) {
    Vec3f at, eye;
    s16 id;
    if (poke_start_encounter(&sPokeOot.game, POKE_RATTATA, 4) != POKE_OK)
        return;
    sPokeOot.battleAnchor = player->actor.world.pos;
    sPokeOot.previousTurns = sPokeOot.game.turns;
    sPokeOot.attackFramesRemaining = 0;
    sPokeOot.modelFrame = 0;
    id = Play_CreateSubCamera(play);
    sPokeOot.battleCameraId = id;
    if (id != CAM_ID_NONE) {
        at.x = sPokeOot.battleAnchor.x;
        at.y = sPokeOot.battleAnchor.y + 65.0f;
        at.z = sPokeOot.battleAnchor.z + 70.0f;
        eye.x = sPokeOot.battleAnchor.x + 235.0f;
        eye.y = sPokeOot.battleAnchor.y + 165.0f;
        eye.z = sPokeOot.battleAnchor.z + 385.0f;
        Play_ChangeCameraStatus(play, CAM_ID_MAIN, CAM_STAT_WAIT);
        Play_ChangeCameraStatus(play, id, CAM_STAT_ACTIVE);
        Play_SetCameraAtEye(play, id, &at, &eye);
    }
    sPokeOot.game.previous_keys = KEY_B;
}

static void PokeOot_ExitBattle(PlayState* play) {
    if (sPokeOot.battleCameraId != CAM_ID_NONE) {
        Play_ReturnToMainCam(play, sPokeOot.battleCameraId, 0);
        sPokeOot.battleCameraId = CAM_ID_NONE;
    }
    sPokeOot.attackFramesRemaining = 0;
}


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
    sPokeOot.battleCameraId = CAM_ID_NONE;
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
    if (sPokeOot.modelFrame < 0x7FFFFFFFU) sPokeOot.modelFrame++;
    else sPokeOot.modelFrame = 0;
    if (sPokeOot.attackFramesRemaining) sPokeOot.attackFramesRemaining--;

    if (PokeOot_BattleActive()) {
        u16 battleKeys = PokeOot_BattleInput(input);
        poke_update(&sPokeOot.game, battleKeys);
        if (sPokeOot.game.turns != sPokeOot.previousTurns) {
            sPokeOot.previousTurns = sPokeOot.game.turns;
            sPokeOot.attackFramesRemaining = 24;
            sPokeOot.modelFrame = 0;
        }
        if (!PokeOot_BattleActive()) PokeOot_ExitBattle(play);
        return;
    }
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
    /* Optional field preview, separate from the turn-based encounter. */
    if ((held & (BTN_L | BTN_R)) == (BTN_L | BTN_R) &&
        (pressed & BTN_B) && PokeStadium_AssetAvailable() &&
        sPokeOot.game.party_count &&
        sPokeOot.game.party[sPokeOot.game.active].species == POKE_BULBASAUR) {
        PokeOot_EnterBattle(play, player);
        return;
    }
    if ((held & (BTN_L | BTN_R)) == (BTN_L | BTN_R) &&
        (pressed & BTN_A) && PokeStadium_AssetAvailable()) {
        sPokeOot.attackFramesRemaining = 24;
        sPokeOot.modelFrame = 0;
    }
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

/* Preview the *real* user-exported Stadium Bulbasaur in a native OoT room.
 * This retains the scene camera, room geometry and collision. A proper battle
 * actor/sub-camera will reuse the same asset draw routine in a later slice.
 */
static void PokeOot_DrawStadiumModel(PlayState* play) {
    Player* player = GET_PLAYER(play);
    GraphicsContext* gfx = play->state.gfxCtx;
    f32 x, z;
    if (!PokeStadium_AssetAvailable() || player == NULL) return;

    x = player->actor.world.pos.x + Math_SinS(player->actor.shape.rot.y) * 165.0f;
    z = player->actor.world.pos.z + Math_CosS(player->actor.shape.rot.y) * 165.0f;

    View_Apply(&play->view, VIEW_ALL);
    Matrix_Push();
    Matrix_Translate(x, player->actor.world.pos.y, z, MTXMODE_NEW);
    Matrix_RotateY((f32)player->actor.shape.rot.y * (3.14159265f / 32768.0f),
                   MTXMODE_APPLY);

    OPEN_DISPS(gfx);
    MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++, gfx);
    CLOSE_DISPS(gfx);
    PokeStadium_DrawBulbasaur(gfx, sPokeOot.attackFramesRemaining != 0,
                              sPokeOot.modelFrame);
    Matrix_Pop();
}

void PokeOot_Draw(PlayState* play) {
    GraphicsContext* gfx;
    GfxPrint printer;

    if (!sPokeOot.initialized) return;
    gfx = play->state.gfxCtx;
    PokeOot_DrawStadiumModel(play);

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
        GfxPrint_Printf(&printer, "L+C< BULB  L+C^ CHAR  L+C> SQUIRT");
    } else {
        const PokeMon* starter = &sPokeOot.game.party[0];
        GfxPrint_Printf(&printer, "%s L%u  PARTY %u/6  STEPS %u",
                         poke_species(starter->species)->name, starter->level,
                         sPokeOot.game.party_count, sPokeOot.game.steps);
    }

    GfxPrint_SetColor(&printer, 225, 229, 230, 255);
    GfxPrint_SetPosPx(&printer, 16, 216);
    if (PokeStadium_AssetAvailable()) {
        GfxPrint_Printf(&printer, "STADIUM BULBASAUR: L+R+A ATTACK");
    } else {
        GfxPrint_Printf(&printer, "STADIUM MODEL MISSING: make stadium-n64");
    }
    OVERLAY_DISP = GfxPrint_Close(&printer);
    GfxPrint_Destroy(&printer);
    CLOSE_DISPS(gfx);
}
