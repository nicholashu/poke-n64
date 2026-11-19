/* Original prototype renderer and platform adapter for HackerOoT.
 * No Stadium/Snap geometry, textures or animations are embedded here.
 */
#include "poke_state.h"
#include "controller.h"
#include "gfx.h"
#include "gfx_setupdl.h"
#include "letterbox.h"
#include "libu64/gfxprint.h"
#include "regs.h"
#include "save.h"
#include "ss_sram.h"
#include "sys_matrix.h"
#include "sys_ucode.h"

#define WORLD_TILE 100
#define MAX_DRAW_BOXES 260
#define JOURNAL_SIZE 512
#define JOURNAL_DATA 16
#define JOURNAL_CRC (JOURNAL_DATA + POKE_SAVE_SIZE)
#define SRAM_BASE 0x08000000

/* DMA uses 16-byte aligned buffers; slots are disjoint and do not depend on
 * SaveContext layout. The custom state never invokes the stock file selector.
 * The entire SRAM format belongs to this ROM; do not reuse a Zelda .sra file.
 */
static u8 sJournal[2][JOURNAL_SIZE] __attribute__((aligned(16)));
static u8 sReadback[JOURNAL_SIZE] __attribute__((aligned(16)));

static u32 Read32(const u8* p) {
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

static void Write32(u8* p, u32 n) {
    p[0] = (u8)n; p[1] = (u8)(n >> 8); p[2] = (u8)(n >> 16); p[3] = (u8)(n >> 24);
}

static int JournalValid(const u8* p, PokeGame* decoded) {
    if (p[0] != 'P' || p[1] != 'K' || p[2] != '6' || p[3] != '4' ||
        Read32(p + 4) != 1 || Read32(p + 12) != POKE_SAVE_SIZE ||
        Read32(p + JOURNAL_CRC) != poke_crc32(p, JOURNAL_CRC)) return 0;
    return poke_save_decode(decoded, p + JOURNAL_DATA, POKE_SAVE_SIZE);
}

static int JournalLoad(PokeState* self) {
    PokeGame decoded[2];
    int valid[2];
    int chosen;
    SsSram_ReadWrite(SRAM_BASE, sJournal[0], JOURNAL_SIZE, OS_READ);
    SsSram_ReadWrite(SRAM_BASE + JOURNAL_SIZE, sJournal[1], JOURNAL_SIZE, OS_READ);
    valid[0] = JournalValid(sJournal[0], &decoded[0]);
    valid[1] = JournalValid(sJournal[1], &decoded[1]);
    if (!valid[0] && !valid[1]) return 0;
    chosen = valid[1] && (!valid[0] || (s32)(Read32(sJournal[1] + 8) - Read32(sJournal[0] + 8)) > 0);
    self->game = decoded[chosen];
    self->saveSlot = chosen;
    self->saveGeneration = Read32(sJournal[chosen] + 8);
    poke_note(&self->game, "Saved adventure loaded.");
    return 1;
}

static int JournalSave(PokeState* self) {
    PokeGame verify;
    int next = self->saveSlot == 0 ? 1 : 0;
    u8* target = sJournal[next];
    int i;
    for (i = 0; i < JOURNAL_SIZE; ++i) target[i] = 0;
    if (poke_save_encode(&self->game, target + JOURNAL_DATA, POKE_SAVE_SIZE) != POKE_SAVE_SIZE) return 0;
    target[0] = 'P'; target[1] = 'K'; target[2] = '6'; target[3] = '4';
    Write32(target + 4, 1);
    Write32(target + 8, self->saveGeneration + 1);
    Write32(target + 12, POKE_SAVE_SIZE);
    Write32(target + JOURNAL_CRC, poke_crc32(target, JOURNAL_CRC));
    SsSram_ReadWrite(SRAM_BASE + next * JOURNAL_SIZE, target, JOURNAL_SIZE, OS_WRITE);
    SsSram_ReadWrite(SRAM_BASE + next * JOURNAL_SIZE, sReadback, JOURNAL_SIZE, OS_READ);
    /* Both CRCs plus byte-for-byte readback are needed before reporting success. */
    if (!JournalValid(sReadback, &verify)) return 0;
    for (i = 0; i < JOURNAL_SIZE; ++i) if (target[i] != sReadback[i]) return 0;
    self->saveSlot = next;
    self->saveGeneration += 1;
    return 1;
}

static u16 ReadKeys(const Input* input) {
    u16 keys = 0;
    u16 b = input->cur.button;
    if ((b & BTN_DUP) || input->cur.stick_y > 24) keys |= KEY_UP;
    if ((b & BTN_DDOWN) || input->cur.stick_y < -24) keys |= KEY_DOWN;
    if ((b & BTN_DLEFT) || input->cur.stick_x < -24) keys |= KEY_LEFT;
    if ((b & BTN_DRIGHT) || input->cur.stick_x > 24) keys |= KEY_RIGHT;
    if (b & BTN_A) keys |= KEY_A;
    if (b & BTN_B) keys |= KEY_B;
    if (b & BTN_START) keys |= KEY_START;
    return keys;
}

/* Vertices are generated in world coordinates. One identity model matrix is
 * shared by all boxes: no per-object matrix allocation or pointer serialization.
 */
static void Box(PokeState* self, int x, int y, int z, int sx, int sy, int sz, u8 r, u8 g, u8 b) {
    GraphicsContext* gfx = self->state.gfxCtx;
    Vtx* v;
    int i;
    if (self->drawBoxes >= MAX_DRAW_BOXES) return;
    self->drawBoxes++;
    v = GRAPH_ALLOC(gfx, sizeof(Vtx) * 8);
    if (v == NULL) return; /* Never emit a vertex load from a failed allocation. */
    for (i = 0; i < 8; ++i) {
        int top = (i & 2) != 0;
        v[i].v.ob[0] = x + ((i & 1) ? sx : -sx);
        v[i].v.ob[1] = y + (top ? sy : 0);
        v[i].v.ob[2] = z + ((i & 4) ? sz : -sz);
        v[i].v.flag = 0;
        v[i].v.tc[0] = v[i].v.tc[1] = 0;
        v[i].v.cn[0] = top ? r : r * 3 / 4;
        v[i].v.cn[1] = top ? g : g * 3 / 4;
        v[i].v.cn[2] = top ? b : b * 3 / 4;
        v[i].v.cn[3] = 255;
    }
    OPEN_DISPS(gfx);
    gSPVertex(POLY_OPA_DISP++, v, 8, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 1, 3, 0, 0, 3, 2, 0);
    gSP2Triangles(POLY_OPA_DISP++, 4, 6, 7, 0, 4, 7, 5, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 2, 6, 0, 0, 6, 4, 0);
    gSP2Triangles(POLY_OPA_DISP++, 1, 5, 7, 0, 1, 7, 3, 0);
    gSP2Triangles(POLY_OPA_DISP++, 2, 3, 7, 0, 2, 7, 6, 0);
    gSP2Triangles(POLY_OPA_DISP++, 0, 4, 5, 0, 0, 5, 1, 0);
    CLOSE_DISPS(gfx);
}

static void Creature(PokeState* self, int x, int z, u8 species) {
    u8 r = 153, g = 111, b = 187;
    if (species == POKE_BULBASAUR) { r = 72; g = 177; b = 128; }
    if (species == POKE_CHARMANDER) { r = 240; g = 136; b = 66; }
    if (species == POKE_SQUIRTLE) { r = 101; g = 181; b = 222; }
    if (species == POKE_PIDGEY) { r = 184; g = 150; b = 104; }
    Box(self, x, 12, z, 32, 39, 28, r, g, b);
    Box(self, x, 45, z - 14, 27, 32, 25, r, g, b);
    Box(self, x - 15, 0, z, 10, 17, 15, r, g, b);
    Box(self, x + 15, 0, z, 10, 17, 15, r, g, b);
    Box(self, x - 13, 63, z - 40, 5, 7, 3, 24, 29, 35);
    Box(self, x + 13, 63, z - 40, 5, 7, 3, 24, 29, 35);
    if (species == POKE_BULBASAUR) Box(self, x, 44, z + 19, 24, 32, 25, 54, 128, 70);
    if (species == POKE_SQUIRTLE) Box(self, x, 24, z + 24, 28, 35, 12, 135, 98, 65);
    if (species == POKE_CHARMANDER) Box(self, x, 18, z + 40, 7, 34, 9, 249, 205, 56);
    if (species == POKE_RATTATA) {
        Box(self, x - 20, 74, z - 8, 9, 18, 9, r, g, b);
        Box(self, x + 20, 74, z - 8, 9, 18, 9, r, g, b);
    }
    if (species == POKE_PIDGEY) {
        Box(self, x - 38, 27, z, 14, 12, 23, r, g, b);
        Box(self, x + 38, 27, z, 14, 12, 23, r, g, b);
        Box(self, x, 53, z - 44, 9, 8, 10, 242, 199, 72);
    }
}

static void DrawWorld(PokeState* self) {
    int tx = self->game.x / POKE_TILE;
    int tz = self->game.z / POKE_TILE;
    int x, z;
    int px = self->game.x * WORLD_TILE / POKE_TILE;
    int pz = self->game.z * WORLD_TILE / POKE_TILE;
    Box(self, 1000, -7, 1200, 1000, 7, 1200, 157, 186, 115);
    for (z = tz - 6; z <= tz + 6; ++z) for (x = tx - 6; x <= tx + 6; ++x) {
        PokeTile tile;
        int wx = x * WORLD_TILE + 50;
        int wz = z * WORLD_TILE + 50;
        if (x < 0 || z < 0 || x >= POKE_MAP_W || z >= POKE_MAP_H) continue;
        tile = poke_tile(x, z);
        if (tile == TILE_GRASS) {
            Box(self, wx, 0, wz, 47, 6, 47, 84, 145, 79);
        } else if (tile == TILE_TREE) {
            Box(self, wx, 0, wz, 12, 55, 12, 115, 91, 63);
            Box(self, wx, 40, wz, 43, 65, 43, 56, 119, 83);
        } else if (tile == TILE_WALL) {
            Box(self, wx, 0, wz, 50, 95, 50, 224, 211, 168);
            Box(self, wx, 95, wz, 54, 25, 54, 164, 90, 74);
        } else if (tile == TILE_HEAL || tile == TILE_OAK) {
            Box(self, wx, 0, wz, 16, 43, 13, 235, 234, 215);
            Box(self, wx, 43, wz, 13, 23, 13, 234, 190, 151);
            Box(self, wx, 66, wz, 15, 9, 15, tile == TILE_HEAL ? 214 : 174, tile == TILE_HEAL ? 84 : 174, tile == TILE_HEAL ? 91 : 164);
        } else {
            Box(self, wx, 0, wz, 49, 1, 49, tile == TILE_DOOR ? 172 : 204, tile == TILE_DOOR ? 151 : 190, tile == TILE_DOOR ? 115 : 142);
        }
    }
    /* Keep the frame-wide box budget. Never reset it midway through drawing. */
    Box(self, px - 8, 0, pz, 6, 16, 8, 51, 66, 93);
    Box(self, px + 8, 0, pz, 6, 16, 8, 51, 66, 93);
    Box(self, px, 16, pz, 17, 29, 11, 207, 70, 66);
    Box(self, px, 45, pz, 12, 19, 11, 241, 194, 150);
    Box(self, px, 64, pz, 16, 6, 14, 217, 69, 66);
}

static void Panel(GraphicsContext* gfx, int x, int y, int w, int h, u8 r, u8 g, u8 b) {
    u32 color = GPACK_RGBA5551(r, g, b, 1);
    OPEN_DISPS(gfx);
    gDPPipeSync(OVERLAY_DISP++);
    gDPSetCycleType(OVERLAY_DISP++, G_CYC_FILL);
    gDPSetRenderMode(OVERLAY_DISP++, G_RM_NOOP, G_RM_NOOP2);
    gDPSetFillColor(OVERLAY_DISP++, (color << 16) | color);
    gDPFillRectangle(OVERLAY_DISP++, x, y, x + w - 1, y + h - 1);
    gDPPipeSync(OVERLAY_DISP++);
    CLOSE_DISPS(gfx);
}

static void PrintLine(GfxPrint* print, int x, int y, const char* text) {
    /* 36-character cap is a 288 px safe viewport at 320 x 240. */
    char line[37];
    int i = 0;
    while (i < 36 && text[i]) { line[i] = text[i]; ++i; }
    if (i == 36 && text[i]) { line[33] = '.'; line[34] = '.'; line[35] = '.'; }
    line[i] = '\0';
    GfxPrint_SetPosPx(print, x, y);
    GfxPrint_Printf(print, "%s", line);
}

static void DrawHud(PokeState* self) {
    GraphicsContext* gfx = self->state.gfxCtx;
    PokeGame* game = &self->game;
    GfxPrint print;
    unsigned i, count = poke_menu_count(game);
    int menuTop = 112;
    Panel(gfx, 8, 7, 304, 31, 27, 43, 45);
    Panel(gfx, 8, 185, 304, 47, 27, 43, 45);
    if (game->mode != MODE_FIELD) Panel(gfx, 169, menuTop - 4, 143, 69, 35, 52, 53);
    if (poke_in_battle(game)) {
        const PokeMon* player = &game->party[game->active];
        Panel(gfx, 15, 60, 104, 5, 67, 76, 69);
        if (game->enemy.hp) Panel(gfx, 15, 60, 103 * game->enemy.hp / game->enemy.max_hp + 1, 5, 128, 211, 118);
        Panel(gfx, 15, 180, 104, 3, 67, 76, 69);
        if (player->hp) Panel(gfx, 15, 180, 103 * player->hp / player->max_hp + 1, 3, 128, 211, 118);
    }
    OPEN_DISPS(gfx);
    gSPSegment(OVERLAY_DISP++, 0, 0);
    GfxPrint_Init(&print);
    GfxPrint_Open(&print, OVERLAY_DISP);
    GfxPrint_SetColor(&print, 242, 235, 210, 255);
    PrintLine(&print, 15, 12, poke_in_battle(game) ? "POKE N64 / WILD ENCOUNTER" : "POKE N64 / PALLET + ROUTE 1");
    PrintLine(&print, 15, 23, poke_objective(game));
    if (poke_in_battle(game)) {
        GfxPrint_SetPosPx(&print, 15, 48);
        GfxPrint_Printf(&print, "%s L%u  HP %u/%u", poke_species(game->enemy.species)->name,
                       game->enemy.level, game->enemy.hp, game->enemy.max_hp);
        if (game->party_count) {
            const PokeMon* mon = &game->party[game->active];
            GfxPrint_SetPosPx(&print, 15, 159);
            GfxPrint_Printf(&print, "%s L%u", poke_species(mon->species)->name, mon->level);
            GfxPrint_SetPosPx(&print, 15, 170);
            GfxPrint_Printf(&print, "HP %u/%u", mon->hp, mon->max_hp);
        }
    } else {
        GfxPrint_SetPosPx(&print, 15, 44);
        GfxPrint_Printf(&print, "PARTY %u/6  BALL %u  POTION %u", game->party_count, game->balls, game->potions);
        int tx = game->x / POKE_TILE;
        int tz = game->z / POKE_TILE;
        int dx, dz;
        PrintLine(&print, 15, 56, "Stick: walk  A: talk  Start: menu");
        for (dz = -1; dz <= 1; ++dz) for (dx = -1; dx <= 1; ++dx) {
            PokeTile tile = poke_tile(tx + dx, tz + dz);
            if (tile == TILE_OAK) PrintLine(&print, 15, 69, "OAK  /  Press A to talk");
            if (tile == TILE_HEAL) PrintLine(&print, 15, 69, "HEALER  /  Press A to restore party");
        }
    }
    for (i = 0; i < count && i < 6; ++i) {
        GfxPrint_SetColor(&print, game->cursor == i ? 255 : 217, game->cursor == i ? 212 : 225, game->cursor == i ? 92 : 209, 255);
        GfxPrint_SetPosPx(&print, 176, menuTop + i * 10);
        /* labels are names; 15 chars fits the right-side panel */
        GfxPrint_Printf(&print, "%c %.15s", game->cursor == i ? '>' : ' ', poke_menu_label(game, i));
    }
    GfxPrint_SetColor(&print, 242, 235, 210, 255);
    if (game->mode == MODE_MOVES && game->cursor < POKE_MOVE_SLOTS) {
        const PokeMon* mon = &game->party[game->active];
        const PokeMove* move = poke_move_info(mon->moves[game->cursor]);
        GfxPrint_SetPosPx(&print, 15, 143);
        GfxPrint_Printf(&print, "PP %u/%u", mon->pp[game->cursor], move->pp);
    }
    if (game->mode == MODE_PARTY && game->cursor < game->party_count) {
        const PokeMon* mon = &game->party[game->cursor];
        GfxPrint_SetPosPx(&print, 15, 93);
        GfxPrint_Printf(&print, "L%u  HP %u/%u", mon->level, mon->hp, mon->max_hp);
    }
    for (i = 0; i < POKE_LOG_LINES; ++i) PrintLine(&print, 15, 190 + i * 9, game->log[i]);
    OVERLAY_DISP = GfxPrint_Close(&print);
    GfxPrint_Destroy(&print);
    CLOSE_DISPS(gfx);
}

static void Draw(PokeState* self) {
    GraphicsContext* gfx = self->state.gfxCtx;
    Vec3f at, eye, up = { 0, 1, 0 };
    int battle = poke_in_battle(&self->game);
    self->drawBoxes = 0;
    Gfx_SetupFrame(gfx, true, 162, 196, 180);
    Gfx_ClearZBuffer(gfx);
    at.x = battle ? 0 : self->game.x * WORLD_TILE / (f32)POKE_TILE;
    at.y = battle ? 25 : 0;
    at.z = battle ? 0 : self->game.z * WORLD_TILE / (f32)POKE_TILE - 100;
    eye.x = at.x + (battle ? 320 : 0);
    eye.y = battle ? 260 : 720;
    eye.z = at.z + (battle ? 620 : 650);
    View_LookAt(&self->view, &eye, &at, &up);
    View_Apply(&self->view, VIEW_ALL);
    OPEN_DISPS(gfx);
    gSPSegment(POLY_OPA_DISP++, 0, 0);
    gSPMatrix(POLY_OPA_DISP++, &gIdentityMtx, G_MTX_NOPUSH | G_MTX_LOAD | G_MTX_MODELVIEW);
    gDPPipeSync(POLY_OPA_DISP++);
    gDPSetCycleType(POLY_OPA_DISP++, G_CYC_1CYCLE);
    gSPClearGeometryMode(POLY_OPA_DISP++, G_LIGHTING | G_TEXTURE_GEN | G_TEXTURE_GEN_LINEAR | G_CULL_BOTH | G_FOG);
    gSPSetGeometryMode(POLY_OPA_DISP++, G_SHADE | G_SHADING_SMOOTH | G_ZBUFFER);
    gSPTexture(POLY_OPA_DISP++, 0, 0, 0, G_TX_RENDERTILE, G_OFF);
    gDPSetCombineMode(POLY_OPA_DISP++, G_CC_SHADE, G_CC_SHADE);
    gDPSetRenderMode(POLY_OPA_DISP++, G_RM_AA_ZB_OPA_SURF, G_RM_AA_ZB_OPA_SURF2);
    CLOSE_DISPS(gfx);
    if (battle) {
        Box(self, 0, -8, 0, 440, 8, 310, 132, 165, 108);
        Box(self, -140, 0, 100, 84, 3, 64, 199, 192, 143);
        Box(self, 120, 0, -100, 84, 3, 64, 199, 192, 143);
        if (self->game.party_count) Creature(self, -140, 100, self->game.party[self->game.active].species);
        Creature(self, 120, -100, self->game.enemy.species);
    } else DrawWorld(self);
    DrawHud(self);
}

/* Deliberately minimal boot probe: only the engine's framebuffer-clear path.
 * If this blue frame is absent, failure predates the map, vertex and HUD code.
 * A enters the game, Z+A bypasses the SRAM read to isolate save problems.
 */
static void DrawBoot(PokeState* self) {
    Gfx_SetupFrame(self->state.gfxCtx, true, 30, 98, 180);
}

static void Poke_Main(GameState* state) {
    PokeState* self = (PokeState*)state;
    u16 keys = ReadKeys(&state->input[0]);
    u8 request;
    if (self->bootSplash) {
        if (state->input[0].press.button & BTN_A) {
            /* First prove the framebuffer path works without invoking any
             * world, SRAM, view or matrix initialization at boot. */
            Matrix_Init(state);
            Letterbox_Init();
#if ENABLE_NEW_LETTERBOX
            ShrinkWindow_Init();
#endif
            Letterbox_SetSize(0);
            View_Init(&self->view, state->gfxCtx);
            View_SetPerspective(&self->view, 55.0f, 10.0f, 3500.0f);
            SET_FULLSCREEN_VIEWPORT(&self->view);
            poke_init(&self->game, (u32)osGetTime() ^ 0x504F4B45U);
            self->saveGeneration = 0;
            self->saveSlot = -1;
            self->drawBoxes = 0;
            self->bootReady = 1;
            if (!(state->input[0].cur.button & BTN_Z)) JournalLoad(self);
            self->bootSplash = 0;
            self->game.previous_keys = KEY_A;
        }
        DrawBoot(self);
        return;
    }
    poke_update(&self->game, keys);
    request = poke_take_request(&self->game);
    if (request == REQUEST_SAVE) poke_note(&self->game, JournalSave(self) ? "Adventure saved to cartridge SRAM." : "Save failed. Previous save preserved.");
    if (request == REQUEST_LOAD && !JournalLoad(self)) poke_note(&self->game, "No valid save. Adventure unchanged.");
    /* Do not treat held confirm/start as a new edge after a successful load. */
    self->game.previous_keys = keys;
    Draw(self);
}

void Poke_Init(GameState* state) {
    PokeState* self = (PokeState*)state;
    /* Keep the first visible frame independent of all gameplay subsystems.
     * Even matrix/view setup is deferred until the user presses A. */
    self->bootSplash = 1;
    self->bootReady = 0;
    state->main = Poke_Main;
    state->destroy = Poke_Destroy;
    state->running = true;
    R_UPDATE_RATE = 2; /* 30 game updates per second on NTSC */
}

void Poke_Destroy(GameState* state) {
    PokeState* self = (PokeState*)state;
    if (!self->bootReady) return;
#if ENABLE_NEW_LETTERBOX
    ShrinkWindow_Destroy();
#endif
    Letterbox_Destroy();
}
