#ifndef POKE_INTRO_H
#define POKE_INTRO_H
#include "poke.h"

/* Stable room/stage IDs also form the read-only emulator test protocol. */
typedef enum { INTRO_PALLET, INTRO_BEDROOM, INTRO_HOME, INTRO_BLUE_HOUSE,
               INTRO_LAB, INTRO_ROOM_COUNT } PokeIntroRoom;
typedef enum { INTRO_WAKE, INTRO_EXPLORE, INTRO_OAK_WARNING, INTRO_ESCORT,
               INTRO_LAB_WELCOME, INTRO_CHOOSE, INTRO_CHOSEN,
               INTRO_RIVAL_CHALLENGE, INTRO_RIVAL_BATTLE,
               INTRO_AFTER_BATTLE, INTRO_COMPLETE } PokeIntroStage;
typedef enum { TALK_NONE, TALK_WAKE, TALK_OAK_WARNING, TALK_LAB_WELCOME,
               TALK_BALL, TALK_CHOSEN, TALK_RIVAL_CHALLENGE, TALK_RESULT,
               TALK_MOM, TALK_HEALED, TALK_PC, TALK_PC_EMPTY, TALK_CONSOLE,
               TALK_TV, TALK_BOOKS, TALK_DAISY, TALK_GIRL, TALK_FISHER,
               TALK_RED_SIGN, TALK_BLUE_SIGN, TALK_TOWN_SIGN, TALK_LAB_SIGN,
               TALK_OAK_AWAY, TALK_PICK_FIRST, TALK_ROUTE_END, TALK_LAB_AIDE,
               TALK_BLUE, TALK_OAK_DONE, TALK_PC_FULL } PokeIntroTalk;
typedef struct { uint8_t room, x, z, destination, spawn; } PokeIntroWarp;
typedef struct { uint8_t width, height; const char* name; const char* const* rows; } PokeIntroMap;
extern const PokeIntroMap gPokeIntroMaps[INTRO_ROOM_COUNT];
extern const PokeIntroWarp gPokeIntroWarps[];
extern const unsigned gPokeIntroWarpCount;

/* Present only in the ROM-import build. Generated tables contain text
 * extracted locally from the supported Red/Blue cartridge. */
extern const unsigned gPokeOpeningTextEnabled;
extern const char* const gPokeOpeningTalks[TALK_PC_FULL + 1];
extern const char* const gPokeOpeningStarters[3]; /* Bulbasaur, Charmander, Squirtle */
extern const char* const gPokeOpeningResults[2]; /* win, loss */

typedef struct {
    uint8_t stage, room, talk, selection, starter, rival;
    uint8_t warp_pending, warp_room, warp_spawn;
    uint8_t escort_step, pc_taken, outcome, warp_armed;
    uint8_t text_page;
    uint8_t reposition, reposition_x, reposition_z;
    int8_t look_x, look_z;
} PokeIntro;

void poke_intro_init(PokeIntro* intro);
void poke_intro_enter(PokeIntro* intro, uint8_t room);
void poke_intro_face(PokeIntro* intro, int dx, int dz);
int poke_intro_walkable(unsigned room, int x, int z);
int poke_intro_locked(const PokeIntro* intro);
uint8_t poke_intro_rival(uint8_t starter);
/* Receives actual native player tile and freshly pressed logical buttons. */
void poke_intro_update(PokeIntro* intro, PokeGame* game, int x, int z,
                       uint16_t pressed);
int poke_intro_escort_target(const PokeIntro* intro, int* x, int* z);
void poke_intro_escort_arrived(PokeIntro* intro);
const char* poke_intro_speaker(const PokeIntro* intro, const PokeGame* game);
const char* poke_intro_line(const PokeIntro* intro, const PokeGame* game, unsigned line);
const char* poke_intro_objective(const PokeIntro* intro);
#endif
