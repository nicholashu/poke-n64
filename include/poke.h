#ifndef POKE_H
#define POKE_H

/* Platform-independent rules. World coordinates use 256 units per map tile. */
#include <stddef.h>
#include <stdint.h>

#define POKE_PARTY_MAX 6
#define POKE_MOVE_SLOTS 4
#define POKE_MAP_W 20
#define POKE_MAP_H 24
#define POKE_TILE 256
#define POKE_LOG_LINES 4
#define POKE_LOG_WIDTH 64
#define POKE_SAVE_SIZE 256
#define POKE_SAVE_VERSION 1

typedef enum {
    POKE_NONE = 0, POKE_BULBASAUR = 1, POKE_CHARMANDER = 4,
    POKE_SQUIRTLE = 7, POKE_PIDGEY = 16, POKE_RATTATA = 19
} PokeSpecies;

typedef enum {
    MOVE_NONE, MOVE_TACKLE, MOVE_GROWL, MOVE_VINE_WHIP, MOVE_SCRATCH,
    MOVE_EMBER, MOVE_TAIL_WHIP, MOVE_WATER_GUN, MOVE_GUST, MOVE_STRUGGLE,
    MOVE_COUNT
} PokeMoveId;

typedef enum { TYPE_NORMAL, TYPE_GRASS, TYPE_FIRE, TYPE_WATER, TYPE_FLYING, TYPE_POISON } PokeType;
typedef enum { MODE_FIELD, MODE_STARTER, MODE_BATTLE, MODE_MOVES, MODE_BAG, MODE_PARTY, MODE_MENU } PokeMode;
typedef enum { REQUEST_NONE, REQUEST_SAVE, REQUEST_LOAD } PokeRequest;
typedef enum { TILE_PATH, TILE_GRASS, TILE_TREE, TILE_WALL, TILE_HEAL, TILE_OAK, TILE_DOOR } PokeTile;
typedef enum { POKE_OK, POKE_INVALID, POKE_NO_PP, POKE_NO_ITEM, POKE_PARTY_FULL, POKE_WRONG_MODE } PokeResult;

enum {
    KEY_UP = 1, KEY_DOWN = 2, KEY_LEFT = 4, KEY_RIGHT = 8,
    KEY_A = 16, KEY_B = 32, KEY_START = 64
};
enum { FLAG_STARTER = 1 };

typedef struct {
    uint8_t species, level;
    uint16_t hp, max_hp, attack, defense, speed, special;
    uint32_t xp;
    uint8_t moves[POKE_MOVE_SLOTS], pp[POKE_MOVE_SLOTS];
} PokeMon;

typedef struct {
    uint8_t id;
    const char *name;
    uint8_t type, power, accuracy, pp;
} PokeMove;

typedef struct {
    uint8_t id;
    const char *name;
    uint8_t type1, type2;
    uint8_t hp, attack, defense, speed, special, catch_rate, base_xp;
} PokeSpeciesInfo;

typedef struct {
    uint32_t rng;
    PokeMon party[POKE_PARTY_MAX];
    PokeMon enemy;
    int32_t x, z;
    uint32_t steps, wins, captures;
    uint16_t balls, potions, flags, previous_keys;
    uint16_t walk_distance, encounter_cooldown, turns;
    uint8_t party_count, active, mode, cursor, request, forced_switch;
    int8_t attack_stage[2], defense_stage[2];
    uint8_t seen_mask, caught_mask;
    char log[POKE_LOG_LINES][POKE_LOG_WIDTH];
} PokeGame;

const PokeSpeciesInfo *poke_species(uint8_t id);
const PokeMove *poke_move_info(uint8_t id);
uint32_t poke_random(PokeGame *game);
uint32_t poke_level_xp(uint8_t level);
void poke_make_mon(PokeMon *mon, uint8_t species, uint8_t level);
void poke_recalculate(PokeMon *mon);
void poke_init(PokeGame *game, uint32_t seed);
void poke_note(PokeGame *game, const char *text);
PokeTile poke_tile(int x, int z);
int poke_walkable(int32_t x, int32_t z);
int poke_in_battle(const PokeGame *game);
int poke_valid_mon(const PokeMon *mon);
int poke_valid_game(const PokeGame *game);
PokeResult poke_choose_starter(PokeGame *game, uint8_t species);
PokeResult poke_start_encounter(PokeGame *game, uint8_t species, uint8_t level);
PokeResult poke_battle_move(PokeGame *game, uint8_t slot);
PokeResult poke_capture(PokeGame *game);
PokeResult poke_run(PokeGame *game);
PokeResult poke_switch(PokeGame *game, uint8_t slot);
PokeResult poke_potion(PokeGame *game);
void poke_heal(PokeGame *game);
void poke_walk(PokeGame *game, int dx, int dz);
void poke_update(PokeGame *game, uint16_t held_keys);
uint8_t poke_take_request(PokeGame *game);
unsigned poke_menu_count(const PokeGame *game);
const char *poke_menu_label(const PokeGame *game, unsigned index);
const char *poke_objective(const PokeGame *game);

/* Saves are field-only, explicitly little-endian; failure leaves output intact. */
size_t poke_save_encode(const PokeGame *game, uint8_t *out, size_t capacity);
int poke_save_decode(PokeGame *game, const uint8_t *bytes, size_t length);
uint32_t poke_crc32(const uint8_t *bytes, size_t length);

#endif
