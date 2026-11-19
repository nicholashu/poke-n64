#ifndef POKE_PALLET_IMPORT_H
#define POKE_PALLET_IMPORT_H

#include <stdint.h>

/* Portable, immutable content emitted from a supported user-supplied GB ROM.
 * Coordinates are original 16-pixel walking cells. No engine types or ROM
 * addresses escape into the gameplay runner. */
#define POKE_PALLET_CELL 80
#define POKE_PALLET_MAX_CELLS 512
#define POKE_PALLET_TEXT_WIDTH 36
#define POKE_PALLET_TEXT_LINES 3
#define POKE_PALLET_TEXT_LIMIT 4096

typedef enum {
    POKE_PALLET_TEXT_NONE, POKE_PALLET_TEXT_OAK_HEY_WAIT,
    POKE_PALLET_TEXT_OAK_UNSAFE, POKE_PALLET_TEXT_GIRL,
    POKE_PALLET_TEXT_FISHER, POKE_PALLET_TEXT_LAB_SIGN,
    POKE_PALLET_TEXT_TOWN_SIGN, POKE_PALLET_TEXT_PLAYER_HOUSE_SIGN,
    POKE_PALLET_TEXT_RIVAL_HOUSE_SIGN, POKE_PALLET_TEXT_COUNT
} PokePalletTextId;

typedef enum {
    POKE_PALLET_NORTH, POKE_PALLET_SOUTH,
    POKE_PALLET_WEST, POKE_PALLET_EAST
} PokePalletDirection;

typedef struct {
    uint8_t id, x, y, sprite_id, visible, text_id;
} PokePalletObject;
typedef struct {
    uint8_t x, y, destination_map, destination_warp;
    const char* destination_name;
} PokePalletWarp;
typedef struct { uint8_t x, y, text_id; } PokePalletSign;
typedef struct {
    uint8_t direction, destination_map;
    const char* destination_name;
} PokePalletConnection;
typedef struct {
    uint8_t enabled, width, height, spawn_x, spawn_y;
    uint8_t oak_object_id, lab_warp_index;
    const uint8_t* walkable;
    uint8_t object_count, warp_count, sign_count, connection_count;
    const PokePalletObject* objects;
    const PokePalletWarp* warps;
    const PokePalletSign* signs;
    const PokePalletConnection* connections;
    /* Indexed by PokePalletTextId; NONE may be NULL. ASCII with newlines. */
    const char* const* texts;
} PokePalletMap;

extern const PokePalletMap gPokePalletMap;

typedef enum {
    POKE_PALLET_EXPLORE, POKE_PALLET_OAK_CALL,
    POKE_PALLET_OAK_APPROACH, POKE_PALLET_OAK_WARNING,
    POKE_PALLET_ESCORT, POKE_PALLET_LAB_BOUNDARY,
    POKE_PALLET_SCRIPT_BLOCKED
} PokePalletStage;

typedef struct {
    uint8_t active, stage, oak_visible, followed_oak_into_lab;
    uint8_t talking, text_id, page_more, boundary_armed;
    int8_t face_x, face_y;
    /* Sub-cell units, with cell (0,0)'s center at (0,0). */
    int16_t player_x, player_y, oak_x, oak_y;
    uint16_t text_offset, path_length, path_index;
    uint16_t path[POKE_PALLET_MAX_CELLS];
    const char* message;
    char notice[160];
    char lines[POKE_PALLET_TEXT_LINES][POKE_PALLET_TEXT_WIDTH + 1];
} PokePalletState;

int poke_pallet_validate(const PokePalletMap* map);
int poke_pallet_init(PokePalletState* state, const PokePalletMap* map);
int poke_pallet_locked(const PokePalletState* state);
int poke_pallet_static_walkable(const PokePalletMap* map, int x, int y);
int poke_pallet_object_visible(const PokePalletState* state,
                               const PokePalletMap* map, unsigned index);
void poke_pallet_face(PokePalletState* state, int x, int y);
/* One call is one native gameplay frame; A is bit 16 (KEY_A in poke.h).
 * Player input is the observed position, in sub-cell units. The accepted or
 * scripted position is returned in state->player_x/y for the native adapter. */
void poke_pallet_update(PokePalletState* state, const PokePalletMap* map,
                        int player_x, int player_y, uint16_t pressed);

#endif
