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
#include "poke_pallet_native.h"

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
    Vec3f fieldBulbasaurPos;
    u16 previousTurns;
} PokeOotRuntime;

static PokeOotRuntime sPokeOot;

s32 PokeOot_BattleActive(void) {
    return sPokeOot.initialized && poke_in_battle(&sPokeOot.game);
}

s32 PokeOot_InputLocked(void) {
    return PokeOot_BattleActive() || PokePalletNative_InputLocked();
}

s32 PokeOot_ImportedPallet(void) { return PokePalletNative_Enabled(); }

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
        /* Stage opponent and player on either side of this axis. Framing
         * uses a forward-facing broadcast camera instead of Link's camera. */
        at.x = sPokeOot.battleAnchor.x;
        at.y = sPokeOot.battleAnchor.y + 75.0f;
        at.z = sPokeOot.battleAnchor.z + 95.0f;
        eye.x = sPokeOot.battleAnchor.x + 10.0f;
        eye.y = sPokeOot.battleAnchor.y + 176.0f;
        eye.z = sPokeOot.battleAnchor.z + 540.0f;
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
    PokePalletNative_OnSceneEnter(play);
    /* OoT's actor position may have teleported between scene loads. */
    sPokeOot.havePrevious = 0;
    sPokeOot.lastScene = play->sceneId;
    sPokeOot.battleCameraId = CAM_ID_NONE;
    /* Stable original Pallet landmark, no longer parented to Link's
     * continuously changing position or his facing direction. */
    sPokeOot.fieldBulbasaurPos.x = 160.0f;
    sPokeOot.fieldBulbasaurPos.y = 0.0f;
    sPokeOot.fieldBulbasaurPos.z = 535.0f;
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
    if (PokePalletNative_Enabled()) {
        PokePalletNative_Update(play);
        return;
    }
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

    if (PokeOot_BattleActive()) {
        x = sPokeOot.battleAnchor.x - 145.0f;
        z = sPokeOot.battleAnchor.z + 175.0f;
    } else {
        x = sPokeOot.fieldBulbasaurPos.x;
        z = sPokeOot.fieldBulbasaurPos.z;
    }

    View_Apply(&play->view, VIEW_ALL);
    Matrix_Push();
    Matrix_Translate(x, PokeOot_BattleActive() ? sPokeOot.battleAnchor.y :
                     sPokeOot.fieldBulbasaurPos.y, z, MTXMODE_NEW);
    /* Face the enemy in battle. In the field, face toward the town path. */
    Matrix_RotateY(PokeOot_BattleActive() ? 1.5707963f : 3.14159265f,
                   MTXMODE_APPLY);

    OPEN_DISPS(gfx);
    MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++, gfx);
    CLOSE_DISPS(gfx);
    PokeStadium_DrawBulbasaur(gfx, sPokeOot.attackFramesRemaining != 0,
                              sPokeOot.modelFrame);
    Matrix_Pop();
}

/* Temporary wild Rattata stand-in until its own Stadium model is exported.
 * This is intentionally original geometry and does not ship copyrighted data.
 */
static void PokeOot_DrawWildProxy(PlayState* play) {
    GraphicsContext* gfx = play->state.gfxCtx;
    Vtx* vertices;
    s32 i;
    if (!PokeOot_BattleActive()) return;
    vertices = GRAPH_ALLOC(gfx, sizeof(Vtx) * 8);
    if (vertices == NULL) return;
    for (i = 0; i < 8; i++) {
        s32 top = (i & 2) != 0;
        vertices[i].v.ob[0] = (i & 1) ? 27 : -27;
        vertices[i].v.ob[1] = top ? 57 : 0;
        vertices[i].v.ob[2] = (i & 4) ? 36 : -36;
        vertices[i].v.flag = 0;
        vertices[i].v.tc[0] = vertices[i].v.tc[1] = 0;
        vertices[i].v.cn[0] = top ? 159 : 123;
        vertices[i].v.cn[1] = top ? 114 : 84;
        vertices[i].v.cn[2] = top ? 189 : 151;
        vertices[i].v.cn[3] = 255;
    }
    Matrix_Push();
    Matrix_Translate(sPokeOot.battleAnchor.x + 145.0f,
                     sPokeOot.battleAnchor.y,
                     sPokeOot.battleAnchor.z + 5.0f, MTXMODE_NEW);
    OPEN_DISPS(gfx);
    MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++, gfx);
    gDPPipeSync(POLY_OPA_DISP++);
    gSPTexture(POLY_OPA_DISP++, 0, 0, 0, G_TX_RENDERTILE, G_OFF);
    gDPSetCombineMode(POLY_OPA_DISP++, G_CC_SHADE, G_CC_SHADE);
    gSPVertex(POLY_OPA_DISP++, vertices, 8, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 1, 3, 0, 0, 3, 2, 0);
    gSP2Triangles(POLY_OPA_DISP++, 4, 6, 7, 0, 4, 7, 5, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 2, 6, 0, 0, 6, 4, 0);
    gSP2Triangles(POLY_OPA_DISP++, 1, 5, 7, 0, 1, 7, 3, 0);
    gSP2Triangles(POLY_OPA_DISP++, 2, 3, 7, 0, 2, 7, 6, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 4, 5, 0, 0, 5, 1, 0);
    CLOSE_DISPS(gfx);
    Matrix_Pop();
}

static void PokeOot_DrawPanel(GraphicsContext* gfx, s32 x, s32 y, s32 w, s32 h) {
    u32 color = GPACK_RGBA5551(21, 37, 47, 1);
    OPEN_DISPS(gfx);
    gDPPipeSync(OVERLAY_DISP++);
    gDPSetCycleType(OVERLAY_DISP++, G_CYC_FILL);
    gDPSetRenderMode(OVERLAY_DISP++, G_RM_NOOP, G_RM_NOOP2);
    gDPSetFillColor(OVERLAY_DISP++, (color << 16) | color);
    gDPFillRectangle(OVERLAY_DISP++, x, y, x + w - 1, y + h - 1);
    gDPPipeSync(OVERLAY_DISP++);
    CLOSE_DISPS(gfx);
}

void PokeOot_Draw(PlayState* play) {
    GraphicsContext* gfx;
    GfxPrint printer;
    PokeGame* game = &sPokeOot.game;
    s32 battling = PokeOot_BattleActive();
    s32 index;
    unsigned choices;

    if (!sPokeOot.initialized) return;
    if (PokePalletNative_Enabled()) {
        PokePalletNative_Draw(play);
        return;
    }
    gfx = play->state.gfxCtx;

    PokeOot_DrawStadiumModel(play);
    if (battling) {
        PokeOot_DrawWildProxy(play);
        PokeOot_DrawPanel(gfx, 8, 8, 170, 45);
        PokeOot_DrawPanel(gfx, 155, 130, 157, 45);
        PokeOot_DrawPanel(gfx, 8, 181, 304, 52);
    } else {
        PokeOot_DrawPanel(gfx, 8, 8, 304, 34);
        PokeOot_DrawPanel(gfx, 8, 214, 304, 19);
    }

    OPEN_DISPS(gfx);
    gSPSegment(OVERLAY_DISP++, 0, 0);
    GfxPrint_Init(&printer);
    GfxPrint_Open(&printer, OVERLAY_DISP);
    GfxPrint_SetColor(&printer, 255, 229, 155, 255);
    if (battling) {
        const PokeMon* enemy = &game->enemy;
        const PokeMon* own = &game->party[game->active];
        GfxPrint_SetPosPx(&printer, 16, 13);
        GfxPrint_Printf(&printer, "WILD %s L%u", poke_species(enemy->species)->name, enemy->level);
        GfxPrint_SetPosPx(&printer, 16, 28);
        GfxPrint_Printf(&printer, "HP %u/%u", enemy->hp, enemy->max_hp);

        GfxPrint_SetPosPx(&printer, 163, 136);
        GfxPrint_Printf(&printer, "%s L%u", poke_species(own->species)->name, own->level);
        GfxPrint_SetPosPx(&printer, 163, 150);
        GfxPrint_Printf(&printer, "HP %u/%u", own->hp, own->max_hp);

        choices = poke_menu_count(game);
        GfxPrint_SetColor(&printer, 244, 239, 219, 255);
        if (game->mode == MODE_MOVES || game->mode == MODE_BAG ||
            game->mode == MODE_BATTLE || game->mode == MODE_PARTY) {
            for (index = 0; index < 4 && index < choices; index++) {
                GfxPrint_SetPosPx(&printer, 16 + (index / 2) * 146,
                                 187 + (index % 2) * 12);
                GfxPrint_Printf(&printer, "%c %.15s",
                                 game->cursor == index ? '>' : ' ',
                                 poke_menu_label(game, index));
            }
        }
        GfxPrint_SetPosPx(&printer, 16, 216);
        GfxPrint_Printf(&printer, "%.35s", game->log[POKE_LOG_LINES - 1]);
    } else {
        GfxPrint_SetPosPx(&printer, 16, 13);
        GfxPrint_Printf(&printer, "PALLET TOWN / KANTO");
        GfxPrint_SetColor(&printer, 244, 239, 219, 255);
        GfxPrint_SetPosPx(&printer, 16, 25);
        if (!(game->flags & FLAG_STARTER)) {
            GfxPrint_Printf(&printer, "L+C< BULB  L+C^ CHAR  L+C> SQUIRT");
        } else {
            const PokeMon* starter = &game->party[0];
            GfxPrint_Printf(&printer, "%s L%u  PARTY %u/6  STEPS %u",
                             poke_species(starter->species)->name, starter->level,
                             game->party_count, game->steps);
        }
        GfxPrint_SetColor(&printer, 225, 229, 230, 255);
        GfxPrint_SetPosPx(&printer, 16, 218);
        if (PokeStadium_AssetAvailable()) {
            GfxPrint_Printf(&printer, "L+R+A ATTACK  L+R+B WILD BATTLE");
        } else {
            GfxPrint_Printf(&printer, "STADIUM MODEL MISSING: make stadium-n64");
        }
    }
    OVERLAY_DISP = GfxPrint_Close(&printer);
    GfxPrint_Destroy(&printer);
    CLOSE_DISPS(gfx);
}
