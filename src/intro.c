#include "poke_intro.h"
#include <string.h>

/* A dialogue page is two 36-column rows. The original GB text controls were
 * decoded during import. Do not replace missing ROM passages with authored
 * substitute dialogue in the imported build. */
static const char* opening_rom_dialogue(const PokeIntro* s) {
    if (!gPokeOpeningTextEnabled || s->talk == TALK_NONE || s->talk > TALK_LAB_GIRL)
        return NULL;
    if (s->talk == TALK_BALL) {
        if (s->selection == POKE_BULBASAUR) return gPokeOpeningStarters[0];
        if (s->selection == POKE_CHARMANDER) return gPokeOpeningStarters[1];
        if (s->selection == POKE_SQUIRTLE) return gPokeOpeningStarters[2];
        return NULL;
    }
    if (s->talk == TALK_RESULT) {
        if (s->outcome == BATTLE_WON) return gPokeOpeningResults[0];
        if (s->outcome == BATTLE_LOST) return gPokeOpeningResults[1];
        return NULL;
    }
    return gPokeOpeningTalks[s->talk];
}

/* Render or count the same paginated text. A new paragraph and every two
 * display lines advance a page; source passages are separated by form-feed. */
static int opening_rom_page(const char* text, unsigned target, char out[2][37]) {
    unsigned page = 0, row = 0, column = 0, i;
    out[0][0] = out[1][0] = 0;
    if (text == NULL) return 0;
    for (i = 0; i < 4096 && text[i] != 0; ++i) {
        char ch = text[i];
        if (ch == '\r') continue;
        if (ch == '\f') { ++page; row = column = 0; continue; }
        if (ch == '\n') {
            ++row; column = 0;
            if (row >= 2) { ++page; row = 0; }
            continue;
        }
        if (column >= 36) {
            ++row; column = 0;
            if (row >= 2) { ++page; row = 0; }
        }
        if (page == target) {
            out[row][column] = ch;
            out[row][column + 1] = 0;
        }
        ++column;
    }
    return page > target;
}

static int opening_rom_more(const PokeIntro* s) {
    char discarded[2][37];
    return opening_rom_page(opening_rom_dialogue(s), s->text_page, discarded);
}

static const uint8_t sEscort[][2] = {
    {10,2}, {10,7}, {9,7}, {9,12}, {12,12}, {12,11}
};
static int near(const PokeIntro* s,int x,int z,int a,int b) {
    if (s->look_x || s->look_z) return x+s->look_x==a && z+s->look_z==b;
    int dx=x-a,dz=z-b;
    if (dx<0) dx=-dx;
    if (dz<0) dz=-dz;
    return dx+dz<=1;
}
static void warp(PokeIntro* s,uint8_t room,uint8_t spawn) {
    s->warp_pending=1; s->warp_room=room; s->warp_spawn=spawn;
}
static void heal_without_items(PokeGame* g) {
    unsigned i,j;
    for (i=0;i<g->party_count;++i) {
        g->party[i].hp=g->party[i].max_hp;
        for (j=0;j<POKE_MOVE_SLOTS;++j)
            g->party[i].pp[j]=poke_move_info(g->party[i].moves[j])->pp;
    }
    g->active=0;
}

void poke_intro_init(PokeIntro* s) {
    memset(s,0,sizeof(*s));
    s->stage=INTRO_WAKE; s->room=INTRO_BEDROOM; s->talk=TALK_WAKE;
}
void poke_intro_enter(PokeIntro* s,uint8_t room) {
    if (room>=INTRO_ROOM_COUNT) return;
    s->room=room; s->warp_pending=0; s->warp_armed=0;
    if (room==INTRO_LAB && s->stage==INTRO_LAB_WELCOME)
        s->talk=TALK_LAB_WELCOME;
}
void poke_intro_face(PokeIntro* s,int dx,int dz) {
    s->look_x=(int8_t)(dx<0 ? -1 : dx>0 ? 1 : 0);
    s->look_z=(int8_t)(dz<0 ? -1 : dz>0 ? 1 : 0);
    if (s->look_x) s->look_z=0;
}
int poke_intro_walkable(unsigned room,int x,int z) {
    const PokeIntroMap* map;
    if (room>=INTRO_ROOM_COUNT) return 0;
    map=&gPokeIntroMaps[room];
    return x>=0 && z>=0 && x<map->width && z<map->height && map->rows[z][x]=='.';
}
int poke_intro_locked(const PokeIntro* s) {
    return s->talk!=TALK_NONE || s->stage==INTRO_ESCORT ||
           s->stage==INTRO_RIVAL_BATTLE || s->warp_pending;
}
uint8_t poke_intro_rival(uint8_t starter) {
    if (starter==POKE_BULBASAUR) return POKE_CHARMANDER;
    if (starter==POKE_CHARMANDER) return POKE_SQUIRTLE;
    if (starter==POKE_SQUIRTLE) return POKE_BULBASAUR;
    return POKE_NONE;
}

static void confirm(PokeIntro* s,PokeGame* g,uint16_t pressed) {
    uint8_t talk=s->talk;
    if (talk==TALK_BALL && (pressed&KEY_B)) { s->talk=TALK_NONE; return; }
    if (!(pressed&KEY_A)) return;
    if (gPokeOpeningTextEnabled && opening_rom_more(s)) {
        ++s->text_page;
        return;
    }
    s->text_page = 0;
    s->talk=TALK_NONE;
    switch (talk) {
        case TALK_WAKE: s->stage=INTRO_EXPLORE; break;
        case TALK_OAK_WARNING: s->stage=INTRO_ESCORT; s->escort_step=0; break;
        case TALK_LAB_WELCOME: s->stage=INTRO_CHOOSE; break;
        case TALK_BALL:
            if (s->stage!=INTRO_CHOOSE || g->party_count) break;
            g->mode=MODE_STARTER;
            if (poke_choose_starter(g,s->selection)!=POKE_OK) { g->mode=MODE_FIELD; break; }
            /* Original opening: no free Poke Balls; optional PC Potion only. */
            g->balls=0; g->potions=s->pc_taken ? 1 : 0;
            s->starter=s->selection; s->rival=poke_intro_rival(s->starter);
            s->stage=INTRO_CHOSEN; s->talk=TALK_CHOSEN;
            break;
        case TALK_RIVAL_CHALLENGE:
            if (poke_start_trainer_battle(g,s->rival,5)==POKE_OK) {
                s->stage=INTRO_RIVAL_BATTLE;
                g->previous_keys=KEY_A; /* confirmation cannot also choose Fight */
            }
            break;
        case TALK_RESULT: s->stage=INTRO_COMPLETE; break;
        default: break;
    }
}

/* GB object and sign records, not the handwritten fixture, determine where
 * every opening-area interaction occurs. Script effects below are adapters
 * for pret/pokered's known map-specific assembly routines. */
static void interact_rom(PokeIntro* s, PokeGame* g, int x, int z) {
    unsigned i;
    for (i = 0; i < gPokeIntroSignCount; ++i) {
        const PokeIntroSign* sign = &gPokeIntroSigns[i];
        if (sign->room != s->room || !near(s,x,z,sign->x,sign->z)) continue;
        if (s->room == INTRO_PALLET) {
            if (sign->text_id == 4) s->talk = TALK_LAB_SIGN;
            else if (sign->text_id == 5) s->talk = TALK_TOWN_SIGN;
            else if (sign->text_id == 6) s->talk = TALK_RED_SIGN;
            else if (sign->text_id == 7) s->talk = TALK_BLUE_SIGN;
        } else if (s->room == INTRO_HOME && sign->text_id == 2)
            s->talk = TALK_TV;
        return;
    }
    for (i = 0; i < gPokeIntroObjectCount; ++i) {
        const PokeIntroObject* obj = &gPokeIntroObjects[i];
        if (obj->room != s->room || !near(s,x,z,obj->x,obj->z)) continue;
        switch (s->room) {
            case INTRO_PALLET:
                if (obj->id == 2) s->talk = TALK_GIRL;
                else if (obj->id == 3) s->talk = TALK_FISHER;
                break;
            case INTRO_HOME:
                if (obj->id == 1) {
                    if (g->party_count) {
                        heal_without_items(g);
                        s->talk = TALK_HEALED;
                    } else s->talk = TALK_MOM;
                }
                break;
            case INTRO_BLUE_HOUSE:
                if (obj->id == 1) s->talk = TALK_DAISY;
                else if (obj->id == 2) s->talk = TALK_DAISY_WALK;
                else if (obj->id == 3) s->talk = TALK_TOWN_MAP;
                break;
            case INTRO_LAB:
                if (obj->id >= 2 && obj->id <= 4) {
                    static const uint8_t starters[] = {
                        POKE_CHARMANDER, POKE_SQUIRTLE, POKE_BULBASAUR
                    };
                    if (s->stage == INTRO_CHOOSE) {
                        s->selection = starters[obj->id-2];
                        s->talk = TALK_BALL;
                    } else s->talk = s->stage < INTRO_CHOOSE ?
                                      TALK_OAK_AWAY : TALK_OAK_DONE;
                } else if (obj->id == 1) s->talk = TALK_BLUE;
                else if (obj->id == 5) s->talk =
                    s->stage == INTRO_CHOOSE ? TALK_PICK_FIRST : TALK_OAK_DONE;
                else if (obj->id == 9) s->talk = TALK_LAB_GIRL;
                else if (obj->id == 10 || obj->id == 11) s->talk = TALK_LAB_AIDE;
                break;
            default: break;
        }
        return;
    }
}
static void interact(PokeIntro* s,PokeGame* g,int x,int z) {
    if (gPokeOpeningTextEnabled) {
        interact_rom(s,g,x,z);
        return;
    }
    if (s->room==INTRO_BEDROOM) {
        if (near(s,x,z,0,1)) {
            s->talk=s->pc_taken ? TALK_PC_EMPTY : g->potions>=99 ? TALK_PC_FULL : TALK_PC;
            if (!s->pc_taken && g->potions<99) { s->pc_taken=1; ++g->potions; }
        } else if (near(s,x,z,3,5)) s->talk=TALK_CONSOLE;
        else if (near(s,x,z,3,4)) s->talk=TALK_TV;
        else if (z<=2) s->talk=TALK_BOOKS;
    } else if (s->room==INTRO_HOME) {
        if (near(s,x,z,5,4)) {
            if (g->party_count) { heal_without_items(g); s->talk=TALK_HEALED; }
            else s->talk=TALK_MOM;
        } else if (near(s,x,z,3,1)) s->talk=TALK_TV;
        else if (x<=2 && z<=2) s->talk=TALK_BOOKS;
    } else if (s->room==INTRO_BLUE_HOUSE) {
        if (near(s,x,z,2,3)) s->talk=TALK_DAISY;
        else if (z<=2) s->talk=TALK_BOOKS;
    } else if (s->room==INTRO_PALLET) {
        if (near(s,x,z,3,5)) s->talk=TALK_RED_SIGN;
        else if (near(s,x,z,11,5)) s->talk=TALK_BLUE_SIGN;
        else if (near(s,x,z,7,9)) s->talk=TALK_TOWN_SIGN;
        else if (near(s,x,z,13,13)) s->talk=TALK_LAB_SIGN;
        else if (near(s,x,z,3,8)) s->talk=TALK_GIRL;
        else if (near(s,x,z,11,14)) s->talk=TALK_FISHER;
    } else if (s->room==INTRO_LAB) {
        /* Physical left-to-right table order in Red/Blue. */
        int i,ball=-1;
        static const uint8_t choices[]={POKE_CHARMANDER,POKE_SQUIRTLE,POKE_BULBASAUR};
        for (i=0;i<3;++i) if (near(s,x,z,6+i,3)) { ball=i; break; }
        if (ball>=0) {
            if (s->stage==INTRO_CHOOSE) { s->selection=choices[ball]; s->talk=TALK_BALL; }
            else s->talk=s->stage<INTRO_CHOOSE ? TALK_OAK_AWAY : TALK_OAK_DONE;
        } else if (near(s,x,z,5,2) && s->stage>=INTRO_CHOOSE)
            s->talk=s->stage==INTRO_CHOOSE ? TALK_LAB_WELCOME : TALK_OAK_DONE;
        else if (near(s,x,z,4,3) && s->stage<INTRO_COMPLETE) s->talk=TALK_BLUE;
        else if (near(s,x,z,1,9) || near(s,x,z,2,10) || near(s,x,z,8,10)) s->talk=TALK_LAB_AIDE;
        else if (z<=2) s->talk=TALK_BOOKS;
    }
}

void poke_intro_update(PokeIntro* s,PokeGame* g,int x,int z,uint16_t pressed) {
    unsigned i;
    int on_warp=0;
    if (s->warp_pending || s->room>=INTRO_ROOM_COUNT) return;
    if (s->stage==INTRO_RIVAL_BATTLE) {
        if (poke_in_battle(g)) return;
        if (g->battle_result!=BATTLE_WON && g->battle_result!=BATTLE_LOST) return;
        s->outcome=g->battle_result;
        heal_without_items(g);
        s->stage=INTRO_AFTER_BATTLE; s->talk=TALK_RESULT;
        return;
    }
    if (s->talk) { confirm(s,g,pressed); return; }
    if (s->stage==INTRO_ESCORT) return;
    if (s->room==INTRO_PALLET && s->stage==INTRO_EXPLORE && z<=1 && (x==10 || x==11)) {
        s->stage=INTRO_OAK_WARNING; s->talk=TALK_OAK_WARNING; return;
    }
    if (s->room==INTRO_LAB && z==6 && s->stage==INTRO_CHOOSE) {
        s->talk=TALK_PICK_FIRST; s->reposition=1; s->reposition_x=(uint8_t)x; s->reposition_z=5; return;
    }
    if (s->room==INTRO_LAB && z==6 && s->stage==INTRO_CHOSEN) {
        s->stage=INTRO_RIVAL_CHALLENGE; s->talk=TALK_RIVAL_CHALLENGE; return;
    }
    for (i=0;i<gPokeIntroWarpCount;++i) {
        const PokeIntroWarp* w=&gPokeIntroWarps[i];
        if (w->room==s->room && x==w->x && z==w->z) {
            on_warp=1;
            if (s->warp_armed) { warp(s,w->destination,w->spawn); return; }
        }
    }
    if (!on_warp) s->warp_armed=1;
    if ((pressed&KEY_A)!=0) interact(s,g,x,z);
    /* The slice ends at Pallet. These connections keep their correct map
     * coordinates, with an explicit message instead of a false destination. */
    if (s->room==INTRO_PALLET && ((z==0 && s->stage==INTRO_COMPLETE) || z==17)) {
        s->talk=TALK_ROUTE_END; s->reposition=1;
        s->reposition_x=(uint8_t)x; s->reposition_z=z==0 ? 2 : 16;
    }
}

int poke_intro_escort_target(const PokeIntro* s,int* x,int* z) {
    if (s->stage!=INTRO_ESCORT || s->escort_step>=sizeof(sEscort)/sizeof(sEscort[0])) return 0;
    *x=sEscort[s->escort_step][0]; *z=sEscort[s->escort_step][1]; return 1;
}
void poke_intro_escort_arrived(PokeIntro* s) {
    if (s->stage!=INTRO_ESCORT) return;
    if (++s->escort_step>=sizeof(sEscort)/sizeof(sEscort[0])) {
        s->stage=INTRO_LAB_WELCOME; warp(s,INTRO_LAB,1);
    }
}

const char* poke_intro_speaker(const PokeIntro* s,const PokeGame* g) {
    (void)g;
    switch(s->talk) {
        case TALK_OAK_WARNING: case TALK_LAB_WELCOME: case TALK_PICK_FIRST: case TALK_OAK_DONE: return "PROFESSOR OAK";
        case TALK_CHOSEN: case TALK_RIVAL_CHALLENGE: case TALK_RESULT: case TALK_BLUE: return "BLUE";
        case TALK_MOM: case TALK_HEALED: return "MOM";
        case TALK_DAISY: case TALK_DAISY_WALK: return "DAISY";
        case TALK_BALL: return poke_species(s->selection)->name;
        case TALK_GIRL: return "NEIGHBOR";
        case TALK_FISHER: return "TOWNSPERSON";
        case TALK_LAB_AIDE: return "OAK'S AIDE";
        case TALK_LAB_GIRL: return "ASSISTANT";
        case TALK_TOWN_MAP: return "TOWN MAP";
        default: return "PALLET TOWN";
    }
}
const char* poke_intro_line(const PokeIntro* s,const PokeGame* g,unsigned line) {
    static char page[2][37];
    (void)g;
    if (line>1) return "";
    if (gPokeOpeningTextEnabled) {
        opening_rom_page(opening_rom_dialogue(s), s->text_page, page);
        return page[line];
    }
    switch(s->talk) {
        case TALK_WAKE: return line ? "A: get up and begin your journey." : "A new morning in Pallet Town.";
        case TALK_OAK_WARNING: return line ? "Come to my lab. I can help." : "Wait! The grass is dangerous alone.";
        case TALK_LAB_WELCOME: return line ? "Walk to a Poke Ball and press A." : "Choose one of these three Pokemon.";
        case TALK_BALL: return line ? "A: choose this partner   B: cancel" : "Make this level 5 Pokemon yours?";
        case TALK_CHOSEN: return line ? poke_species(s->rival)->name : "Then this Pokemon will be mine!";
        case TALK_RIVAL_CHALLENGE: return line ? "Let's see what our Pokemon can do!" : "Wait, RED! Battle me before you go!";
        case TALK_RESULT: return line ? "Oak restored your Pokemon. A: next" : s->outcome==BATTLE_WON ? "You won this time. I'll train harder!" : "I won! We'll battle again someday.";
        case TALK_MOM: return line ? "Go outside and find him." : "Professor Oak was looking for you.";
        case TALK_HEALED: return line ? "Your Pokemon's HP and PP are full." : "Take a rest before your next trip.";
        case TALK_PC: return line ? "You took one Potion from storage." : "RED's PC";
        case TALK_PC_FULL: return line ? "Make room in your Bag first." : "One Potion is still in storage.";
        case TALK_PC_EMPTY: return line ? "There are no more items in storage." : "RED's PC";
        case TALK_CONSOLE: return line ? "Time for an adventure of your own." : "The SNES is switched off.";
        case TALK_TV: return line ? "A film is playing on television." : "The TV is on.";
        case TALK_BOOKS: return line ? "Books and notes about Pokemon." : "A well-used collection.";
        case TALK_DAISY: return line ? "He is waiting in Oak's laboratory." : "My brother BLUE is out.";
        case TALK_GIRL: return line ? "Everyone knows everyone here." : "Welcome to Pallet Town!";
        case TALK_FISHER: return line ? "It's amazing what technology can do." : "Computers can store Pokemon!";
        case TALK_RED_SIGN: return line ? "RED's house" : "Home, sweet home.";
        case TALK_BLUE_SIGN: return line ? "BLUE's house" : "Daisy and BLUE live here.";
        case TALK_TOWN_SIGN: return line ? "Your adventure begins here." : "PALLET TOWN";
        case TALK_LAB_SIGN: return line ? "Pokemon research laboratory" : "PROFESSOR OAK";
        case TALK_OAK_AWAY: return line ? "Look for him near the north path." : "Wait for Professor Oak first.";
        case TALK_PICK_FIRST: return line ? "The three Poke Balls are on the table." : "Choose your Pokemon before leaving.";
        case TALK_ROUTE_END: return line ? "Route 1 and Route 21 come next." : "You've reached this playable area's edge.";
        case TALK_LAB_AIDE: return line ? "Oak studies Pokemon with our help." : "Welcome to the research lab.";
        case TALK_BLUE: return line ? "I'm going to become a great Trainer." : "What are you waiting for, RED?";
        case TALK_OAK_DONE: return line ? "Take good care of your partner." : "You and your Pokemon are a team now.";
        default: return "";
    }
}
const char* poke_intro_objective(const PokeIntro* s) {
    if (s->stage==INTRO_WAKE) return "A: WAKE UP";
    if (s->stage==INTRO_EXPLORE) return "FIND OAK AT THE NORTH PATH";
    if (s->stage<=INTRO_LAB_WELCOME) return "FOLLOW PROFESSOR OAK";
    if (s->stage==INTRO_CHOOSE) return "A: INSPECT A POKE BALL";
    if (s->stage<=INTRO_RIVAL_CHALLENGE) return "HEAD TOWARD THE LAB EXIT";
    if (s->stage==INTRO_RIVAL_BATTLE) return "BATTLE YOUR RIVAL";
    if (s->stage==INTRO_AFTER_BATTLE) return "A: FINISH THE CONVERSATION";
    return "FIRST BATTLE COMPLETE / EXPLORE PALLET";
}
