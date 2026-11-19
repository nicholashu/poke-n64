/* Native adapter for the user-ROM Pallet import. Only data tables are
 * generated; all scene interaction and original proxy geometry lives here. */
#include "poke_pallet_native.h"
#include "poke_pallet_import.h"
#include "controller.h"
#include "gfx.h"
#include "libu64/gfxprint.h"
#include "player.h"
#include "scene.h"
#include "sys_matrix.h"
#include "view.h"

static PokePalletState sPallet;
static u8 sEntered;

s32 PokePalletNative_Enabled(void) { return gPokePalletMap.enabled; }
s32 PokePalletNative_InputLocked(void) {
    return PokePalletNative_Enabled() && (!sPallet.active || poke_pallet_locked(&sPallet));
}

static f32 world_x(s16 x) {
    return (f32)x + (0.5f - gPokePalletMap.width * 0.5f) * POKE_PALLET_CELL;
}
static f32 world_z(s16 y) {
    return (f32)y + (0.5f - gPokePalletMap.height * 0.5f) * POKE_PALLET_CELL;
}

void PokePalletNative_OnSceneEnter(PlayState* play) {
    if (!PokePalletNative_Enabled() || play->sceneId != SCENE_KOKIRI_FOREST) return;
    if (!sEntered) {
        (void)poke_pallet_init(&sPallet, &gPokePalletMap);
        sEntered = 1;
    }
}

void PokePalletNative_Update(PlayState* play) {
    Player* player = GET_PLAYER(play);
    Input* input = &play->state.input[0];
    int x, y, face_x = 0, face_y = 0;
    s32 was_scripted;
    s16 yaw;
    if (!PokePalletNative_Enabled() || !sPallet.active || !player ||
        play->sceneId != SCENE_KOKIRI_FOREST) return;
    was_scripted = sPallet.stage == POKE_PALLET_ESCORT;
    x = (int)(player->actor.world.pos.x - world_x(0));
    y = (int)(player->actor.world.pos.z - world_z(0));
    yaw = player->actor.shape.rot.y;
    if (yaw >= -0x2000 && yaw < 0x2000) face_y = 1;
    else if (yaw >= 0x2000 && yaw < 0x6000) face_x = 1;
    else if (yaw >= 0x6000 || yaw < -0x6000) face_y = -1;
    else face_x = -1;
    if (!poke_pallet_locked(&sPallet)) {
        /* PrepareInput converts cardinal D-pad directions to native analog.
         * Both controller paths have already gone through OoT player physics. */
        poke_pallet_face(&sPallet, face_x, face_y);
    }
    poke_pallet_update(&sPallet, &gPokePalletMap, x, y,
                       (input->press.button & BTN_A) ? 16 : 0);
    player->actor.world.pos.x = world_x(sPallet.player_x);
    player->actor.world.pos.z = world_z(sPallet.player_y);
    player->actor.prevPos = player->actor.world.pos;
    if (PokePalletNative_InputLocked()) {
        player->actor.speed = 0.0f;
        player->actor.velocity.x = player->actor.velocity.z = 0.0f;
    }
    if (was_scripted) {
        int dx = sPallet.player_x - x, dy = sPallet.player_y - y;
        if (dx || dy) {
            sPallet.face_x = dx < 0 ? -1 : dx > 0 ? 1 : 0;
            sPallet.face_y = dx ? 0 : dy < 0 ? -1 : 1;
        }
    }
    /* Native analog movement keeps its smooth actor rotation. Only movement
     * commanded by this adapter should force a cardinal render heading. */
    if (was_scripted && (sPallet.face_x || sPallet.face_y)) {
        yaw = sPallet.face_x > 0 ? 0x4000 : sPallet.face_x < 0 ? -0x4000 :
              sPallet.face_y < 0 ? (s16)0x8000 : 0;
        player->actor.shape.rot.y = player->actor.world.rot.y = yaw;
    }
}

static void box(GraphicsContext* gfx, s16 radius, s16 bottom, s16 height,
                u8 red, u8 green, u8 blue) {
    Vtx* vertices = GRAPH_ALLOC(gfx, sizeof(Vtx) * 8);
    s32 i;
    if (!vertices) return;
    for (i = 0; i < 8; ++i) {
        vertices[i].v.ob[0] = (i & 1) ? radius : -radius;
        vertices[i].v.ob[1] = bottom + ((i & 2) ? height : 0);
        vertices[i].v.ob[2] = (i & 4) ? radius : -radius;
        vertices[i].v.flag = 0;
        vertices[i].v.tc[0] = vertices[i].v.tc[1] = 0;
        vertices[i].v.cn[0] = red;
        vertices[i].v.cn[1] = green;
        vertices[i].v.cn[2] = blue;
        vertices[i].v.cn[3] = 255;
    }
    OPEN_DISPS(gfx);
    gSPVertex(POLY_OPA_DISP++, vertices, 8, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 1, 3, 0, 0, 3, 2, 0);
    gSP2Triangles(POLY_OPA_DISP++, 4, 6, 7, 0, 4, 7, 5, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 2, 6, 0, 0, 6, 4, 0);
    gSP2Triangles(POLY_OPA_DISP++, 1, 5, 7, 0, 1, 7, 3, 0);
    gSP2Triangles(POLY_OPA_DISP++, 2, 3, 7, 0, 2, 7, 6, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 4, 5, 0, 0, 5, 1, 0);
    CLOSE_DISPS(gfx);
}

static void people(PlayState* play) {
    GraphicsContext* gfx = play->state.gfxCtx;
    unsigned i;
    View_Apply(&play->view, VIEW_ALL);
    for (i = 0; i < gPokePalletMap.object_count; ++i) {
        const PokePalletObject* object = &gPokePalletMap.objects[i];
        s16 x, y;
        s32 oak = object->id == gPokePalletMap.oak_object_id;
        if (!poke_pallet_object_visible(&sPallet, &gPokePalletMap, i)) continue;
        x = oak ? sPallet.oak_x : (s16)(object->x * POKE_PALLET_CELL);
        y = oak ? sPallet.oak_y : (s16)(object->y * POKE_PALLET_CELL);
        Matrix_Push();
        Matrix_Translate(world_x(x), 0.0f, world_z(y), MTXMODE_NEW);
        OPEN_DISPS(gfx);
        MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++, gfx);
        gDPPipeSync(POLY_OPA_DISP++);
        gSPClearGeometryMode(POLY_OPA_DISP++, G_LIGHTING | G_TEXTURE_GEN | G_CULL_BACK | G_CULL_FRONT);
        gSPSetGeometryMode(POLY_OPA_DISP++, G_SHADE | G_ZBUFFER);
        gDPSetCycleType(POLY_OPA_DISP++, G_CYC_1CYCLE);
        gDPSetRenderMode(POLY_OPA_DISP++, G_RM_AA_ZB_OPA_SURF, G_RM_AA_ZB_OPA_SURF2);
        gSPTexture(POLY_OPA_DISP++, 0, 0, 0, G_TX_RENDERTILE, G_OFF);
        gDPSetCombineMode(POLY_OPA_DISP++, G_CC_SHADE, G_CC_SHADE);
        CLOSE_DISPS(gfx);
        box(gfx, 11, 0, 22, 73, 68, 72);
        box(gfx, 16, 22, 31, oak ? 231 : 170, oak ? 228 : 102, oak ? 213 : 152);
        box(gfx, 12, 53, 23, 231, 185, 144);
        box(gfx, 12, 73, 6, oak ? 205 : 83, oak ? 205 : 65, oak ? 205 : 59);
        Matrix_Pop();
    }
}

static void panel(GraphicsContext* gfx, s32 x, s32 y, s32 w, s32 h) {
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

void PokePalletNative_Draw(PlayState* play) {
    GraphicsContext* gfx = play->state.gfxCtx;
    GfxPrint printer;
    unsigned i;
    const char* prompt;
    if (!PokePalletNative_Enabled() || play->sceneId != SCENE_KOKIRI_FOREST) return;
    if (sPallet.active) people(play);
    if (play->transitionTrigger!=TRANS_TRIGGER_OFF || play->transitionMode!=TRANS_MODE_OFF) return;
    panel(gfx, 8, 8, 304, 34);
    panel(gfx, 8, sPallet.talking ? 166 : 214, 304, sPallet.talking ? 67 : 19);
    OPEN_DISPS(gfx);
    gSPSegment(OVERLAY_DISP++, 0, 0);
    GfxPrint_Init(&printer);
    GfxPrint_Open(&printer, OVERLAY_DISP);
    GfxPrint_SetColor(&printer, 255, 229, 155, 255);
    GfxPrint_SetPosPx(&printer, 16, 13);
    GfxPrint_Printf(&printer, "PALLET TOWN / GB ROM IMPORT");
    GfxPrint_SetColor(&printer, 244, 239, 219, 255);
    GfxPrint_SetPosPx(&printer, 16, 25);
    GfxPrint_Printf(&printer, "A TALK  /  OUTDOOR PROOF OF CONCEPT");
    if (sPallet.talking) {
        const char* speaker = sPallet.text_id == POKE_PALLET_TEXT_NONE ? "IMPORT BOUNDARY" :
            sPallet.text_id <= POKE_PALLET_TEXT_OAK_UNSAFE ? "PROF. OAK" :
            sPallet.text_id <= POKE_PALLET_TEXT_FISHER ? "TOWN RESIDENT" : "SIGN";
        GfxPrint_SetPosPx(&printer, 16, 170);
        GfxPrint_Printf(&printer, "%s", speaker);
        for (i = 0; i < POKE_PALLET_TEXT_LINES; ++i) {
            GfxPrint_SetPosPx(&printer, 16, 183 + i * 11);
            GfxPrint_Printf(&printer, "%s", sPallet.lines[i]);
        }
        GfxPrint_SetPosPx(&printer, 16, 220);
        GfxPrint_Printf(&printer, "%s", sPallet.page_more ? "A NEXT" : "A CONTINUE");
    } else {
        prompt = !sPallet.active ? "INVALID IMPORT DATA: REBUILD REQUIRED" :
            sPallet.stage == POKE_PALLET_OAK_APPROACH ? "Professor Oak is approaching." :
            sPallet.stage == POKE_PALLET_ESCORT ? "Follow Oak to the laboratory." :
            sPallet.stage == POKE_PALLET_LAB_BOUNDARY ? "Lab interior is not imported yet." :
            "Explore town and approach Route 1.";
        GfxPrint_SetPosPx(&printer, 16, 218);
        GfxPrint_Printf(&printer, "%s", prompt);
    }
    OVERLAY_DISP = GfxPrint_Close(&printer);
    GfxPrint_Destroy(&printer);
    CLOSE_DISPS(gfx);
}
