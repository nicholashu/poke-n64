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
#include "sys_math.h"
#include "sys_ucode.h"

#define WORLD_TILE 100
#define POKE_PI 3.14159265f
#define POKE_TWO_PI 6.2831853f
#define FIELD_CAMERA_DISTANCE 285.0f
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

/* OoT-style exploration uses a shoulder-height tracking camera instead of
 * an elevated/isometric view. Battle cameras are independent of exploration.
 * Camera state lives in PokeState, so the portable Pokémon save format remains
 * stable and the host harness retains its existing cardinal controls.
 */
static f32 CameraApproach(f32 current, f32 target, f32 weight) {
    return current + (target - current) * weight;
}

static f32 CameraAbs(f32 value) {
    return value < 0.0f ? -value : value;
}

static f32 CameraWrapYaw(f32 angle) {
    while (angle > POKE_PI) angle -= POKE_TWO_PI;
    while (angle < -POKE_PI) angle += POKE_TWO_PI;
    return angle;
}

static f32 CameraApproachYaw(f32 current, f32 target, f32 weight) {
    f32 difference = CameraWrapYaw(target - current);
    return CameraWrapYaw(current + difference * weight);
}

static f32 FacingYaw(s32 dx, s32 dz) {
    if (dx > 0) {
        if (dz < 0) return POKE_PI * 0.25f;
        if (dz > 0) return POKE_PI * 0.75f;
        return POKE_PI * 0.5f;
    }
    if (dx < 0) {
        if (dz < 0) return -POKE_PI * 0.25f;
        if (dz > 0) return -POKE_PI * 0.75f;
        return -POKE_PI * 0.5f;
    }
    return dz > 0 ? POKE_PI : 0.0f;
}

/* Use the camera heading at the START of a stick gesture to map walking.
 * Otherwise, the chase camera turning to follow Red feeds back into analog
 * movement and makes holding forward continuously steer him round corners.
 * Releasing the stick establishes a fresh camera-relative movement basis.
 */
static u16 ReadFieldKeys(PokeState* self, const Input* input) {
    s32 sx = input->cur.stick_x;
    s32 sy = input->cur.stick_y;
    u16 held = input->cur.button;
    u16 keys = ReadKeys(input) & ~(KEY_UP | KEY_DOWN | KEY_LEFT | KEY_RIGHT);
    f32 worldX, worldZ, absX, absZ;
    s32 dx = 0, dz = 0;

    if (held & BTN_DLEFT) sx = -70;
    if (held & BTN_DRIGHT) sx = 70;
    if (held & BTN_DUP) sy = 70;
    if (held & BTN_DDOWN) sy = -70;

    /* C-buttons orbit manually. Leave that angle alone briefly after release.
     * Z-lock brings the camera behind Red without an instantaneous yaw jump. */
    if (held & BTN_CLEFT) {
        self->cameraYaw = CameraWrapYaw(self->cameraYaw - 0.040f);
        self->orbitHoldFrames = 75;
    }
    if (held & BTN_CRIGHT) {
        self->cameraYaw = CameraWrapYaw(self->cameraYaw + 0.040f);
        self->orbitHoldFrames = 75;
    }
    if (held & BTN_Z) {
        self->cameraYaw = CameraApproachYaw(self->cameraYaw, self->playerYaw, 0.28f);
        self->orbitHoldFrames = 12;
    }

    if (sx > -22 && sx < 22) sx = 0;
    if (sy > -22 && sy < 22) sy = 0;
    if (sx == 0 && sy == 0) {
        self->movementActive = 0;
        if (self->cameraIdleFrames < 120) self->cameraIdleFrames++;
        return keys;
    }
    self->cameraIdleFrames = 0;
    if (!self->movementActive) {
        self->movementBasisYaw = self->cameraYaw;
        self->movementActive = 1;
    }
    worldX = (f32)sx * Math_CosF(self->movementBasisYaw) +
             (f32)sy * Math_SinF(self->movementBasisYaw);
    worldZ = (f32)sx * Math_SinF(self->movementBasisYaw) -
             (f32)sy * Math_CosF(self->movementBasisYaw);
    absX = CameraAbs(worldX);
    absZ = CameraAbs(worldZ);
    /* Eight sectors, with the diagonal sector starting at about 22.5 deg.
     * Unlike a fixed 20-unit threshold, this does not vary with stick strength.
     */
    if (absX > absZ * 0.4142f) {
        if (worldX > 0.0f) { keys |= KEY_RIGHT; dx = 1; }
        else { keys |= KEY_LEFT; dx = -1; }
    }
    if (absZ > absX * 0.4142f) {
        if (worldZ > 0.0f) { keys |= KEY_DOWN; dz = 1; }
        else { keys |= KEY_UP; dz = -1; }
    }
    if (dx || dz) self->playerYaw = FacingYaw(dx, dz);
    return keys;
}

/* Sample the actual line from Red to the camera, rather than blocking the
 * camera behind roofs that it is already high enough to see over. This is a
 * provisional tile-based visibility check until real OoT collision is used.
 */
static f32 CameraFreeDistance(f32 px, f32 pz, f32 yaw) {
    f32 sine = Math_SinF(yaw);
    f32 cosine = Math_CosF(yaw);
    f32 distance;
    for (distance = 100.0f; distance <= FIELD_CAMERA_DISTANCE; distance += 15.0f) {
        f32 cx = px - sine * distance;
        f32 cz = pz + cosine * distance;
        f32 rayHeight = 65.0f + (180.0f - 65.0f) *
                        (distance / FIELD_CAMERA_DISTANCE);
        int tx = (int)(cx / WORLD_TILE);
        int tz = (int)(cz / WORLD_TILE);
        PokeTile tile = poke_tile(tx, tz);
        if (tx <= 0 || tz <= 0 || tx >= POKE_MAP_W - 1 ||
            tz >= POKE_MAP_H - 1 ||
            (tile == TILE_WALL && rayHeight < 126.0f) ||
            (tile == TILE_TREE && rayHeight < 113.0f)) {
            /* Leave a small gap in front of the obstruction. */
            return distance > 115.0f ? distance - 24.0f : 90.0f;
        }
    }
    return FIELD_CAMERA_DISTANCE;
}

/* Keep camera position and aim on ONE smoothed pivot. Previously the eye
 * lagged independently while the look-at point moved immediately with Red,
 * causing visible sway and occasional camera crossings near house corners.
 */
static void FieldCamera(PokeState* self, Vec3f* eye, Vec3f* at) {
    f32 px = (f32)self->game.x * WORLD_TILE / POKE_TILE;
    f32 pz = (f32)self->game.z * WORLD_TILE / POKE_TILE;
    f32 sine, cosine, freeDistance;
    f32 yaw;

    if (self->orbitHoldFrames > 0) self->orbitHoldFrames--;
    /* Follow Red's facing while moving without changing the heading used
     * for a held stick gesture. Manual camera or Z-lock suspends auto-follow. */
    if (self->orbitHoldFrames == 0 && self->movementActive) {
        self->cameraYaw = CameraApproachYaw(self->cameraYaw, self->playerYaw, 0.025f);
    } else if (self->orbitHoldFrames == 0 && self->cameraIdleFrames > 30) {
        self->cameraYaw = CameraApproachYaw(self->cameraYaw, self->playerYaw, 0.018f);
    }

    yaw = self->cameraYaw;
    sine = Math_SinF(yaw);
    cosine = Math_CosF(yaw);
    if (!self->cameraReady) {
        self->cameraFocusX = px;
        self->cameraFocusZ = pz;
        self->cameraDistance = FIELD_CAMERA_DISTANCE;
        self->cameraReady = 1;
    } else {
        self->cameraFocusX = CameraApproach(self->cameraFocusX, px, 0.36f);
        self->cameraFocusZ = CameraApproach(self->cameraFocusZ, pz, 0.36f);
    }

    freeDistance = CameraFreeDistance(self->cameraFocusX, self->cameraFocusZ, yaw);
    /* Pull in promptly to prevent clipping; slide back out gently, without
     * the abrupt 35-unit zoom pops of the old wall-avoidance algorithm. */
    if (freeDistance < self->cameraDistance)
        self->cameraDistance = freeDistance;
    else
        self->cameraDistance = CameraApproach(self->cameraDistance, freeDistance, 0.08f);

    eye->x = self->cameraFocusX - sine * self->cameraDistance;
    eye->y = 180.0f;
    eye->z = self->cameraFocusZ + cosine * self->cameraDistance;
    at->x = self->cameraFocusX + sine * 50.0f;
    at->y = 60.0f;
    at->z = self->cameraFocusZ - cosine * 50.0f;
}

/* Stadium-like battle broadcast camera. Characters and attack animations are
 * still original proxy geometry; Stadium ROM models have NOT been imported. */
static void StadiumCamera(PokeState* self, Vec3f* eye, Vec3f* at) {
    f32 t = (f32)self->battleFrames;
    f32 orbit = Math_SinF(t * 0.011f) * 0.16f;
    f32 zoom = (f32)self->battleActionFrames * 5.0f;
    eye->x = 210.0f + orbit * 140.0f;
    eye->y = 193.0f + Math_SinF(t * 0.022f) * 7.0f;
    eye->z = 550.0f - zoom;
    at->x = 0.0f;
    at->y = 75.0f;
    at->z = 0.0f;
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

static void Creature(PokeState* self, int x, int z, u8 species, int bob) {
    u8 r = 153, g = 111, b = 187;
    if (species == POKE_BULBASAUR) { r = 72; g = 177; b = 128; }
    if (species == POKE_CHARMANDER) { r = 240; g = 136; b = 66; }
    if (species == POKE_SQUIRTLE) { r = 101; g = 181; b = 222; }
    if (species == POKE_PIDGEY) { r = 184; g = 150; b = 104; }
    Box(self, x, 12 + bob, z, 32, 39, 28, r, g, b);
    Box(self, x, 45 + bob, z - 14, 27, 32, 25, r, g, b);
    Box(self, x - 15, bob, z, 10, 17, 15, r, g, b);
    Box(self, x + 15, bob, z, 10, 17, 15, r, g, b);
    Box(self, x - 13, 63 + bob, z - 40, 5, 7, 3, 24, 29, 35);
    Box(self, x + 13, 63 + bob, z - 40, 5, 7, 3, 24, 29, 35);
    if (species == POKE_BULBASAUR) Box(self, x, 44 + bob, z + 19, 24, 32, 25, 54, 128, 70);
    if (species == POKE_SQUIRTLE) Box(self, x, 24 + bob, z + 24, 28, 35, 12, 135, 98, 65);
    if (species == POKE_CHARMANDER) Box(self, x, 18 + bob, z + 40, 7, 34, 9, 249, 205, 56);
    if (species == POKE_RATTATA) {
        Box(self, x - 20, 74 + bob, z - 8, 9, 18, 9, r, g, b);
        Box(self, x + 20, 74 + bob, z - 8, 9, 18, 9, r, g, b);
    }
    if (species == POKE_PIDGEY) {
        Box(self, x - 38, 27 + bob, z, 14, 12, 23, r, g, b);
        Box(self, x + 38, 27 + bob, z, 14, 12, 23, r, g, b);
        Box(self, x, 53 + bob, z - 44, 9, 8, 10, 242, 199, 72);
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

static void PrintShort(GfxPrint* print, int x, int y, const char* text, int cap) {
    char line[37];
    int i = 0;
    if (cap < 1) return;
    if (cap > 36) cap = 36;
    while (i < cap && text[i]) {
        line[i] = text[i];
        i++;
    }
    line[i] = '\0';
    GfxPrint_SetPosPx(print, x, y);
    GfxPrint_Printf(print, "%s", line);
}

static void DrawHud(PokeState* self) {
    GraphicsContext* gfx = self->state.gfxCtx;
    PokeGame* game = &self->game;
    GfxPrint print;
    unsigned i, count = poke_menu_count(game);
    int battle = poke_in_battle(game);
    unsigned firstOption = 0;

    /* World exploration is no longer a full-screen Game Boy HUD. */
    if (battle) {
        /* Stadium-style opponent status, player status, command box, log. */
        Panel(gfx, 8, 8, 149, 36, 26, 42, 49);
        Panel(gfx, 163, 130, 149, 49, 26, 42, 49);
        Panel(gfx, 8, 187, 154, 45, 26, 42, 49);
        Panel(gfx, 166, 185, 146, 47, 34, 54, 57);
        if (game->enemy.max_hp) {
            Panel(gfx, 17, 33, 124, 5, 62, 64, 64);
            if (game->enemy.hp) Panel(gfx, 17, 33, 124 * game->enemy.hp / game->enemy.max_hp,
                                      5, 112, 203, 108);
        }
        if (game->party_count) {
            const PokeMon* mon = &game->party[game->active];
            Panel(gfx, 172, 163, 125, 5, 62, 64, 64);
            if (mon->hp) Panel(gfx, 172, 163, 125 * mon->hp / mon->max_hp, 5, 112, 203, 108);
        }
    } else {
        Panel(gfx, 8, 8, 190, 19, 26, 42, 49);
        Panel(gfx, 8, 198, 304, 34, 26, 42, 49);
        if (game->mode != MODE_FIELD) {
            Panel(gfx, 167, 91, 145, 78, 34, 54, 57);
        }
    }

    OPEN_DISPS(gfx);
    gSPSegment(OVERLAY_DISP++, 0, 0);
    GfxPrint_Init(&print);
    GfxPrint_Open(&print, OVERLAY_DISP);
    GfxPrint_SetColor(&print, 244, 239, 222, 255);
    if (battle) {
        const PokeMon* enemy = &game->enemy;
        PrintShort(&print, 16, 13, poke_species(enemy->species)->name, 12);
        GfxPrint_SetPosPx(&print, 110, 13);
        GfxPrint_Printf(&print, "L%u", enemy->level);
        if (game->party_count) {
            const PokeMon* mon = &game->party[game->active];
            PrintShort(&print, 173, 138, poke_species(mon->species)->name, 12);
            GfxPrint_SetPosPx(&print, 270, 138);
            GfxPrint_Printf(&print, "L%u", mon->level);
            GfxPrint_SetPosPx(&print, 173, 151);
            GfxPrint_Printf(&print, "HP %u/%u", mon->hp, mon->max_hp);
        }
        PrintShort(&print, 15, 193, game->log[POKE_LOG_LINES - 2], 17);
        PrintShort(&print, 15, 205, game->log[POKE_LOG_LINES - 1], 17);
        if (count > 4 && game->cursor >= 4) firstOption = game->cursor - 3;
        for (i = firstOption; i < count && i < firstOption + 4; ++i) {
            GfxPrint_SetColor(&print, game->cursor == i ? 255 : 218,
                              game->cursor == i ? 212 : 224,
                              game->cursor == i ? 91 : 214, 255);
            GfxPrint_SetPosPx(&print, 174, 189 + (i - firstOption) * 10);
            GfxPrint_Printf(&print, "%c %.14s",
                            game->cursor == i ? '>' : ' ', poke_menu_label(game, i));
        }
        if (game->mode == MODE_MOVES && game->party_count && game->cursor < POKE_MOVE_SLOTS) {
            const PokeMon* mon = &game->party[game->active];
            const PokeMove* move = poke_move_info(mon->moves[game->cursor]);
            GfxPrint_SetColor(&print, 244, 239, 222, 255);
            GfxPrint_SetPosPx(&print, 174, 176);
            GfxPrint_Printf(&print, "PP %u/%u", mon->pp[game->cursor], move->pp);
        }
    } else {
        PrintShort(&print, 15, 12, "PALLET TOWN / ROUTE 1", 26);
        GfxPrint_SetColor(&print, 244, 239, 222, 255);
        GfxPrint_SetPosPx(&print, 15, 204);
        GfxPrint_Printf(&print, "PARTY %u/6   BALL %u   POTION %u",
                        game->party_count, game->balls, game->potions);
        PrintLine(&print, 15, 216, game->log[POKE_LOG_LINES - 1]);
        if (game->mode != MODE_FIELD) {
            for (i = 0; i < count && i < 6; ++i) {
                GfxPrint_SetColor(&print, game->cursor == i ? 255 : 218,
                                  game->cursor == i ? 212 : 224,
                                  game->cursor == i ? 91 : 214, 255);
                GfxPrint_SetPosPx(&print, 174, 97 + i * 11);
                GfxPrint_Printf(&print, "%c %.15s",
                                game->cursor == i ? '>' : ' ', poke_menu_label(game, i));
            }
        }
    }
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
    if (battle) {
        if (!self->wasInBattle) {
            self->battleFrames = 0;
            self->battleActionFrames = 0;
            self->seenTurns = self->game.turns;
        } else if (self->seenTurns != self->game.turns) {
            self->battleActionFrames = 18;
            self->seenTurns = self->game.turns;
        }
        if (self->battleActionFrames > 0) self->battleActionFrames--;
        if (self->battleFrames < 30000) self->battleFrames++;
        StadiumCamera(self, &eye, &at);
    } else {
        if (self->wasInBattle) {
            self->cameraReady = 0;
            self->movementActive = 0;
            self->cameraIdleFrames = 0;
        }
        FieldCamera(self, &eye, &at);
    }
    self->wasInBattle = battle;
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
        int playerBob = (int)(2.0f * Math_SinF((f32)self->battleFrames * 0.12f));
        int enemyBob = (int)(3.0f * Math_SinF((f32)self->battleFrames * 0.09f + 1.8f));
        Box(self, 0, -8, 0, 440, 8, 310, 114, 145, 103);
        Box(self, -140, 0, 100, 91, 3, 74, 192, 182, 143);
        Box(self, 120, 0, -100, 91, 3, 74, 192, 182, 143);
        if (self->game.party_count)
            Creature(self, -140, 100, self->game.party[self->game.active].species, playerBob);
        Creature(self, 120, -100, self->game.enemy.species, enemyBob);
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
            View_Init(&self->view, state->gfxCtx);
            View_SetPerspective(&self->view, 55.0f, 10.0f, 3500.0f);
            SET_FULLSCREEN_VIEWPORT(&self->view);
            poke_init(&self->game, (u32)osGetTime() ^ 0x504F4B45U);
            self->saveGeneration = 0;
            self->saveSlot = -1;
            self->drawBoxes = 0;
            self->cameraYaw = 0.0f;
            self->playerYaw = 0.0f;
            self->cameraReady = 0;
            self->cameraIdleFrames = 0;
            self->movementActive = 0;
            self->orbitHoldFrames = 0;
            self->movementBasisYaw = 0.0f;
            self->wasInBattle = 0;
            self->battleFrames = 0;
            self->battleActionFrames = 0;
            if (!(state->input[0].cur.button & BTN_Z)) JournalLoad(self);
            self->bootSplash = 0;
            self->game.previous_keys = KEY_A;
        }
        DrawBoot(self);
        return;
    }
    if (self->game.mode == MODE_FIELD)
        keys = ReadFieldKeys(self, &state->input[0]);
    else
        self->movementActive = 0; /* Menus and battles end a stick gesture. */
    poke_update(&self->game, keys);
    request = poke_take_request(&self->game);
    if (request == REQUEST_SAVE) poke_note(&self->game, JournalSave(self) ? "Adventure saved to cartridge SRAM." : "Save failed. Previous save preserved.");
    if (request == REQUEST_LOAD) {
        if (JournalLoad(self)) {
            self->cameraReady = 0; /* The saved position may be elsewhere. */
            self->movementActive = 0;
        } else {
            poke_note(&self->game, "No valid save. Adventure unchanged.");
        }
    }
    /* Do not treat held confirm/start as a new edge after a successful load. */
    self->game.previous_keys = keys;
    Draw(self);
}

void Poke_Init(GameState* state) {
    PokeState* self = (PokeState*)state;
    /* Gfx_SetupFrame reads letterbox state even for the first blue frame. */
    Letterbox_Init();
#if ENABLE_NEW_LETTERBOX
    ShrinkWindow_Init();
#endif
    Letterbox_SetSize(0);
    self->bootSplash = 1;
    state->main = Poke_Main;
    state->destroy = Poke_Destroy;
    state->running = true;
    R_UPDATE_RATE = 2; /* 30 game updates per second on NTSC */
}

void Poke_Destroy(GameState* state) {
    (void)state;
#if ENABLE_NEW_LETTERBOX
    ShrinkWindow_Destroy();
#endif
    Letterbox_Destroy();
}
