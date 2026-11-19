#include "poke.h"
#include <string.h>

/* Small, explicitly scoped ruleset. No host I/O, heap, floats or engine globals. */
static const PokeSpeciesInfo species_table[] = {
    {POKE_BULBASAUR, "Bulbasaur", TYPE_GRASS, TYPE_POISON, 45,49,49,45,65,45,64},
    {POKE_CHARMANDER, "Charmander", TYPE_FIRE, TYPE_FIRE, 39,52,43,65,50,45,65},
    {POKE_SQUIRTLE, "Squirtle", TYPE_WATER, TYPE_WATER, 44,48,65,43,50,45,66},
    {POKE_PIDGEY, "Pidgey", TYPE_NORMAL, TYPE_FLYING, 40,45,40,56,35,255,55},
    {POKE_RATTATA, "Rattata", TYPE_NORMAL, TYPE_NORMAL, 30,56,35,72,25,255,57}
};

static const PokeMove move_table[MOVE_COUNT] = {
    {MOVE_NONE,"--",TYPE_NORMAL,0,0,0},
    {MOVE_TACKLE,"Tackle",TYPE_NORMAL,35,95,35},
    {MOVE_GROWL,"Growl",TYPE_NORMAL,0,100,40},
    {MOVE_VINE_WHIP,"Vine Whip",TYPE_GRASS,35,100,10},
    {MOVE_SCRATCH,"Scratch",TYPE_NORMAL,40,100,35},
    {MOVE_EMBER,"Ember",TYPE_FIRE,40,100,25},
    {MOVE_TAIL_WHIP,"Tail Whip",TYPE_NORMAL,0,100,30},
    {MOVE_WATER_GUN,"Water Gun",TYPE_WATER,40,100,25},
    {MOVE_GUST,"Gust",TYPE_NORMAL,40,100,35},
    {MOVE_STRUGGLE,"Struggle",TYPE_NORMAL,50,100,0}
};

const PokeSpeciesInfo *poke_species(uint8_t id) {
    unsigned i;
    for (i=0;i<sizeof(species_table)/sizeof(species_table[0]);++i)
        if (species_table[i].id==id) return &species_table[i];
    return NULL;
}

const PokeMove *poke_move_info(uint8_t id) {
    return id<MOVE_COUNT ? &move_table[id] : &move_table[0];
}

static uint8_t species_mask(uint8_t id) {
    unsigned i;
    for (i=0;i<sizeof(species_table)/sizeof(species_table[0]);++i)
        if (species_table[i].id==id) return (uint8_t)(1u<<i);
    return 0;
}

uint32_t poke_random(PokeGame *g) {
    uint32_t x=g->rng;
    if (!x) x=0x504b3634u;
    x^=x<<13; x^=x>>17; x^=x<<5;
    g->rng=x;
    return x;
}

uint32_t poke_level_xp(uint8_t level) {
    return (uint32_t)level*level*level;
}

static uint16_t stat(uint8_t base,uint8_t level) {
    return (uint16_t)((2u*((uint32_t)base+8u)*level)/100u+5u);
}

void poke_recalculate(PokeMon *m) {
    const PokeSpeciesInfo *s=poke_species(m->species);
    if (!s) return;
    m->max_hp=(uint16_t)((2u*((uint32_t)s->hp+8u)*m->level)/100u+m->level+10u);
    m->attack=stat(s->attack,m->level);
    m->defense=stat(s->defense,m->level);
    m->speed=stat(s->speed,m->level);
    m->special=stat(s->special,m->level);
    if (m->hp>m->max_hp) m->hp=m->max_hp;
}

static void give_move(PokeMon *m,unsigned slot,uint8_t move) {
    if (slot<POKE_MOVE_SLOTS && m->moves[slot]!=move) {
        m->moves[slot]=move;
        m->pp[slot]=move_table[move].pp;
    }
}

static void learn_moves(PokeMon *m) {
    if (m->level<7) return;
    if (m->species==POKE_BULBASAUR) give_move(m,2,MOVE_VINE_WHIP);
    else if (m->species==POKE_CHARMANDER) give_move(m,2,MOVE_EMBER);
    else if (m->species==POKE_SQUIRTLE) give_move(m,2,MOVE_WATER_GUN);
}

void poke_make_mon(PokeMon *m,uint8_t species,uint8_t level) {
    memset(m,0,sizeof(*m));
    if (!poke_species(species) || level<2 || level>100) return;
    m->species=species; m->level=level; m->xp=poke_level_xp(level);
    give_move(m,0,species==POKE_CHARMANDER ? MOVE_SCRATCH :
                    species==POKE_PIDGEY ? MOVE_GUST : MOVE_TACKLE);
    give_move(m,1,(species==POKE_SQUIRTLE || species==POKE_RATTATA) ? MOVE_TAIL_WHIP : MOVE_GROWL);
    learn_moves(m);
    poke_recalculate(m); m->hp=m->max_hp;
}

static void copy_text(char *dst,const char *src,size_t cap) {
    size_t n=0;
    if (!cap) return;
    while (n+1<cap && src[n]) { dst[n]=src[n]; ++n; }
    dst[n]='\0';
}

void poke_note(PokeGame *g,const char *text) {
    unsigned i;
    for (i=0;i+1<POKE_LOG_LINES;++i)
        memcpy(g->log[i],g->log[i+1],POKE_LOG_WIDTH);
    memset(g->log[POKE_LOG_LINES-1],0,POKE_LOG_WIDTH);
    copy_text(g->log[POKE_LOG_LINES-1],text,POKE_LOG_WIDTH);
}

static void note_join(PokeGame *g,const char *a,const char *b,const char *c) {
    char text[POKE_LOG_WIDTH];
    size_t n;
    copy_text(text,a,sizeof(text)); n=strlen(text);
    copy_text(text+n,b,sizeof(text)-n); n=strlen(text);
    copy_text(text+n,c,sizeof(text)-n);
    poke_note(g,text);
}

PokeTile poke_tile(int x,int z) {
    if (x<=0 || z<=0 || x>=POKE_MAP_W-1 || z>=POKE_MAP_H-1) return TILE_TREE;
    if ((x>=3 && x<=6 && z>=16 && z<=18) ||
        (x>=12 && x<=15 && z>=15 && z<=17)) return TILE_WALL;
    if (x==8 && z==18) return TILE_OAK;
    if (x==13 && z==19) return TILE_HEAL;
    if (z==19 && x==5) return TILE_DOOR;
    if ((x==2 || x==17) && z>=2 && z<=13) return TILE_TREE;
    if (x>=4 && x<=15 && z>=3 && z<=12 && x!=9 && x!=10) return TILE_GRASS;
    return TILE_PATH;
}

int poke_walkable(int32_t x,int32_t z) {
    PokeTile tile;
    if (x<POKE_TILE || z<POKE_TILE || x>=(POKE_MAP_W-1)*POKE_TILE || z>=(POKE_MAP_H-1)*POKE_TILE) return 0;
    tile=poke_tile((int)(x/POKE_TILE),(int)(z/POKE_TILE));
    return tile!=TILE_TREE && tile!=TILE_WALL && tile!=TILE_OAK && tile!=TILE_HEAL;
}

void poke_init(PokeGame *g,uint32_t seed) {
    memset(g,0,sizeof(*g));
    g->rng=seed ? seed : 0x504b3634u;
    g->x=9*POKE_TILE+POKE_TILE/2; g->z=19*POKE_TILE+POKE_TILE/2;
    g->mode=MODE_FIELD;
    poke_note(g,"PALLET / ROUTE 1 - prototype");
    poke_note(g,"Talk to Oak beside the west house.");
}

int poke_in_battle(const PokeGame *g) {
    return g->mode==MODE_BATTLE || g->mode==MODE_MOVES || g->mode==MODE_BAG ||
        (g->mode==MODE_PARTY && g->enemy.species!=POKE_NONE);
}

int poke_valid_mon(const PokeMon *m) {
    PokeMon expected;
    unsigned i;
    if (!poke_species(m->species) || m->level<2 || m->level>100) return 0;
    if (m->xp<poke_level_xp(m->level) || m->xp>1000000u ||
        (m->level<100 && m->xp>=poke_level_xp((uint8_t)(m->level+1)))) return 0;
    poke_make_mon(&expected,m->species,m->level);
    if (m->max_hp!=expected.max_hp || m->attack!=expected.attack || m->defense!=expected.defense ||
        m->speed!=expected.speed || m->special!=expected.special || m->hp>m->max_hp) return 0;
    for (i=0;i<POKE_MOVE_SLOTS;++i)
        if (m->moves[i]!=expected.moves[i] || m->pp[i]>move_table[expected.moves[i]].pp) return 0;
    return 1;
}

int poke_valid_game(const PokeGame *g) {
    unsigned i;
    int alive=0;
    if (!g->rng || g->mode>MODE_MENU || g->party_count>POKE_PARTY_MAX || g->balls>99 || g->potions>99 ||
        g->trainer_battle>1 || g->battle_result>BATTLE_RAN ||
        g->flags>FLAG_STARTER || g->seen_mask>31 || g->caught_mask>31 ||
        (g->caught_mask & ~g->seen_mask) || g->walk_distance>=POKE_TILE ||
        g->encounter_cooldown>8*POKE_TILE || !poke_walkable(g->x,g->z)) return 0;
    if (!poke_walkable(g->x-48,g->z-48) || !poke_walkable(g->x+48,g->z-48) ||
        !poke_walkable(g->x-48,g->z+48) || !poke_walkable(g->x+48,g->z+48)) return 0;
    if (!!(g->flags & FLAG_STARTER)!=!!g->party_count) return 0;
    if ((!g->party_count && g->active) || (g->party_count && g->active>=g->party_count)) return 0;
    for (i=0;i<g->party_count;++i) {
        if (!poke_valid_mon(&g->party[i])) return 0;
        if (!(g->caught_mask & species_mask(g->party[i].species))) return 0;
        if (g->party[i].hp) alive=1;
    }
    if (g->party_count && !alive) return 0;
    if ((g->mode==MODE_FIELD || g->mode==MODE_MENU) && g->party_count && !g->party[g->active].hp) return 0;
    return 1;
}

PokeResult poke_choose_starter(PokeGame *g,uint8_t species) {
    if (g->mode!=MODE_STARTER || (g->flags&FLAG_STARTER)) return POKE_WRONG_MODE;
    if (species!=POKE_BULBASAUR && species!=POKE_CHARMANDER && species!=POKE_SQUIRTLE) return POKE_INVALID;
    poke_make_mon(&g->party[0],species,5);
    g->party_count=1; g->active=0; g->flags|=FLAG_STARTER;
    g->balls=10; g->potions=3;
    g->seen_mask|=species_mask(species); g->caught_mask|=species_mask(species);
    g->mode=MODE_FIELD; g->cursor=0;
    note_join(g,"Oak: Take good care of ",poke_species(species)->name,"!");
    poke_note(g,"Received 10 Poke Balls and 3 Potions.");
    poke_note(g,"Walk north, then into the tall grass.");
    return POKE_OK;
}

static void reset_stages(PokeGame *g) {
    memset(g->attack_stage,0,sizeof(g->attack_stage));
    memset(g->defense_stage,0,sizeof(g->defense_stage));
}

PokeResult poke_start_encounter(PokeGame *g,uint8_t species,uint8_t level) {
    if (g->mode!=MODE_FIELD || !g->party_count || !g->party[g->active].hp) return POKE_WRONG_MODE;
    if (!poke_species(species) || level<2 || level>100) return POKE_INVALID;
    poke_make_mon(&g->enemy,species,level);
    g->mode=MODE_BATTLE; g->cursor=0; g->turns=0; g->forced_switch=0;
    g->trainer_battle=0; g->battle_result=BATTLE_NONE;
    g->walk_distance=0; reset_stages(g);
    g->seen_mask|=species_mask(species);
    note_join(g,"A wild ",poke_species(species)->name," appeared!");
    return POKE_OK;
}

PokeResult poke_start_trainer_battle(PokeGame *g,uint8_t species,uint8_t level) {
    PokeResult result=poke_start_encounter(g,species,level);
    if (result!=POKE_OK) return result;
    g->trainer_battle=1;
    note_join(g,"BLUE sent out ",poke_species(species)->name,"!");
    return POKE_OK;
}

void poke_heal(PokeGame *g) {
    unsigned i,j;
    if (poke_in_battle(g)) return;
    for (i=0;i<g->party_count;++i) {
        g->party[i].hp=g->party[i].max_hp;
        for (j=0;j<POKE_MOVE_SLOTS;++j) g->party[i].pp[j]=poke_move_info(g->party[i].moves[j])->pp;
    }
    if (g->party_count) {
        /* Free basic supplies make repeated prototype runs possible. */
        if (g->balls<5) g->balls=5;
        if (g->potions<3) g->potions=3;
    }
    poke_note(g,"HP and PP restored. Basic supplies refilled.");
}

static void finish_battle(PokeGame *g) {
    g->mode=MODE_FIELD; g->cursor=0; g->forced_switch=0;
    g->trainer_battle=0;
    g->walk_distance=0; g->encounter_cooldown=3*POKE_TILE;
    memset(&g->enemy,0,sizeof(g->enemy)); reset_stages(g);
}

static void blackout(PokeGame *g) {
    uint8_t trainer=g->trainer_battle;
    unsigned i,j;
    g->battle_result=BATTLE_LOST;
    finish_battle(g);
    if (trainer) {
        /* The opening rival fight continues after a loss. Do not teleport
         * into the legacy host map or invent a reward/item refill. */
        for (i=0;i<g->party_count;++i) {
            g->party[i].hp=g->party[i].max_hp;
            for (j=0;j<POKE_MOVE_SLOTS;++j)
                g->party[i].pp[j]=poke_move_info(g->party[i].moves[j])->pp;
        }
        g->active=0;
        poke_note(g,"BLUE won the battle.");
        return;
    }
    g->x=12*POKE_TILE+POKE_TILE/2; g->z=19*POKE_TILE+POKE_TILE/2;
    g->active=0; poke_heal(g);
    poke_note(g,"Your party fainted. Back at the healing station.");
}

static unsigned first_alive(const PokeGame *g) {
    unsigned i;
    for (i=0;i<g->party_count;++i) if (g->party[i].hp) return i;
    return POKE_PARTY_MAX;
}

static void award_xp(PokeGame *g) {
    PokeMon *m=&g->party[g->active];
    uint32_t gain=(uint32_t)poke_species(g->enemy.species)->base_xp*g->enemy.level/7u;
    uint16_t old_hp;
    uint8_t old_level=m->level;
    if (!m->hp || m->level==100) return;
    if (g->trainer_battle) gain=gain*3u/2u;
    m->xp=(m->xp+gain>1000000u) ? 1000000u : m->xp+gain;
    while (m->level<100 && m->xp>=poke_level_xp((uint8_t)(m->level+1))) {
        old_hp=m->max_hp; ++m->level;
        poke_recalculate(m); m->hp=(uint16_t)(m->hp+m->max_hp-old_hp); learn_moves(m);
    }
    poke_note(g,"Your Pokemon gained experience.");
    if (m->level!=old_level) {
        note_join(g,poke_species(m->species)->name," grew a level!","");
        if (old_level<7 && m->level>=7 && m->moves[2])
            note_join(g,"Learned ",poke_move_info(m->moves[2])->name,"!");
    }
}

/* Return true if the turn must stop (battle over or forced replacement). */
static int resolve_faints(PokeGame *g) {
    unsigned next;
    if (!g->enemy.hp) {
        g->battle_result=BATTLE_WON;
        note_join(g,poke_species(g->enemy.species)->name," fainted!","");
        award_xp(g); if (g->wins!=UINT32_MAX) ++g->wins;
        next=first_alive(g);
        if (next==POKE_PARTY_MAX) blackout(g);
        else { g->active=(uint8_t)(g->party[g->active].hp ? g->active : next); finish_battle(g); }
        return 1;
    }
    if (!g->party[g->active].hp) {
        note_join(g,poke_species(g->party[g->active].species)->name," fainted!","");
        next=first_alive(g);
        if (next==POKE_PARTY_MAX) blackout(g);
        else { g->forced_switch=1; g->mode=MODE_PARTY; g->cursor=(uint8_t)next; poke_note(g,"Choose a healthy Pokemon."); }
        return 1;
    }
    return 0;
}

static uint32_t staged_stat(uint16_t value,int8_t stage) {
    uint32_t v=stage>=0 ? ((uint32_t)value*(unsigned)(2+stage))/2u :
        ((uint32_t)value*2u)/(unsigned)(2-stage);
    return v ? v : 1;
}

static unsigned type_quarters(uint8_t attack,uint8_t defend) {
    if (attack==TYPE_GRASS) {
        if (defend==TYPE_WATER) return 8;
        if (defend==TYPE_GRASS || defend==TYPE_FIRE || defend==TYPE_FLYING || defend==TYPE_POISON) return 2;
    } else if (attack==TYPE_FIRE) {
        if (defend==TYPE_GRASS) return 8;
        if (defend==TYPE_FIRE || defend==TYPE_WATER) return 2;
    } else if (attack==TYPE_WATER) {
        if (defend==TYPE_FIRE) return 8;
        if (defend==TYPE_GRASS || defend==TYPE_WATER) return 2;
    }
    return 4;
}

static int has_pp(const PokeMon *m) {
    unsigned i;
    for (i=0;i<POKE_MOVE_SLOTS;++i) if (m->moves[i] && m->pp[i]) return 1;
    return 0;
}

static void apply_move(PokeGame *g,int enemy,uint8_t slot) {
    PokeMon *att=enemy ? &g->enemy : &g->party[g->active];
    PokeMon *def=enemy ? &g->party[g->active] : &g->enemy;
    const PokeSpeciesInfo *as=poke_species(att->species),*ds=poke_species(def->species);
    uint8_t id=has_pp(att) ? att->moves[slot] : MOVE_STRUGGLE;
    const PokeMove *mv=poke_move_info(id);
    unsigned ai=enemy ? 1u : 0u,di=1u-ai;
    uint32_t attack,defense,damage;
    unsigned effectiveness;
    int critical;
    if (!att->hp || !def->hp) return;
    if (id!=MOVE_STRUGGLE) --att->pp[slot];
    note_join(g,as->name," used ",mv->name);
    if (poke_random(g)%100u>=mv->accuracy) { poke_note(g,"The move missed."); return; }
    if (id==MOVE_GROWL || id==MOVE_TAIL_WHIP) {
        int8_t *stage=id==MOVE_GROWL ? &g->attack_stage[di] : &g->defense_stage[di];
        if (*stage>-6) { --*stage; poke_note(g,id==MOVE_GROWL ? "Attack fell." : "Defense fell."); }
        else poke_note(g,"The stat cannot go any lower.");
        return;
    }
    attack=mv->type==TYPE_NORMAL ? staged_stat(att->attack,g->attack_stage[ai]) : att->special;
    defense=mv->type==TYPE_NORMAL ? staged_stat(def->defense,g->defense_stage[di]) : def->special;
    damage=(((2u*att->level/5u+2u)*mv->power*attack/defense)/50u)+2u;
    critical=(poke_random(g)&15u)==0;
    if (critical) damage*=2u;
    if (id!=MOVE_STRUGGLE && (mv->type==as->type1 || mv->type==as->type2)) damage=damage*3u/2u;
    effectiveness=id==MOVE_STRUGGLE ? 4u : type_quarters(mv->type,ds->type1);
    if (id!=MOVE_STRUGGLE && ds->type2!=ds->type1) effectiveness=effectiveness*type_quarters(mv->type,ds->type2)/4u;
    damage=damage*effectiveness/4u;
    damage=damage*(85u+poke_random(g)%16u)/100u;
    if (!damage) damage=1;
    if (damage>def->hp) damage=def->hp;
    def->hp=(uint16_t)(def->hp-damage);
    if (critical) poke_note(g,"A critical hit!");
    if (effectiveness>4) poke_note(g,"It is super effective!");
    else if (effectiveness<4) poke_note(g,"It is not very effective.");
    if (id==MOVE_STRUGGLE) {
        uint32_t recoil=damage/4u;
        if (!recoil) recoil=1;
        att->hp=(uint16_t)(att->hp>recoil ? att->hp-recoil : 0);
        poke_note(g,"Struggle caused recoil.");
    }
}

static uint8_t enemy_move(PokeGame *g) {
    uint8_t available[POKE_MOVE_SLOTS];
    unsigned i,count=0;
    for (i=0;i<POKE_MOVE_SLOTS;++i) if (g->enemy.moves[i] && g->enemy.pp[i]) available[count++]=(uint8_t)i;
    return count ? available[poke_random(g)%count] : 0;
}

static void enemy_turn(PokeGame *g) {
    apply_move(g,1,enemy_move(g));
    if (!resolve_faints(g)) { g->mode=MODE_BATTLE; g->cursor=0; }
}

static int accepts_battle_action(const PokeGame *g) {
    return poke_in_battle(g) && !g->forced_switch && g->enemy.hp && g->party[g->active].hp;
}

PokeResult poke_battle_move(PokeGame *g,uint8_t slot) {
    PokeMon *m;
    uint8_t foe_slot;
    int first;
    if (!accepts_battle_action(g)) return POKE_WRONG_MODE;
    m=&g->party[g->active];
    if (slot>=POKE_MOVE_SLOTS) return POKE_INVALID;
    if (has_pp(m)) {
        if (!m->moves[slot]) return POKE_INVALID;
        if (!m->pp[slot]) return POKE_NO_PP;
    }
    foe_slot=enemy_move(g);
    first=m->speed>g->enemy.speed || (m->speed==g->enemy.speed && (poke_random(g)&1u));
    if (g->turns<UINT16_MAX) ++g->turns;
    apply_move(g,first ? 0 : 1,first ? slot : foe_slot);
    if (resolve_faints(g)) return POKE_OK;
    apply_move(g,first ? 1 : 0,first ? foe_slot : slot);
    if (!resolve_faints(g)) { g->mode=MODE_BATTLE; g->cursor=0; }
    return POKE_OK;
}

PokeResult poke_capture(PokeGame *g) {
    uint32_t chance;
    uint8_t mask;
    if (!accepts_battle_action(g)) return POKE_WRONG_MODE;
    if (g->trainer_battle) return POKE_INVALID;
    if (g->party_count==POKE_PARTY_MAX) return POKE_PARTY_FULL;
    if (!g->balls) return POKE_NO_ITEM;
    --g->balls; if (g->turns<UINT16_MAX) ++g->turns;
    /* Gen-I-inspired, deliberately simpler than the original ball algorithm. */
    chance=(3u*g->enemy.max_hp-2u*g->enemy.hp)*poke_species(g->enemy.species)->catch_rate/(3u*g->enemy.max_hp);
    if (chance>245u) chance=245u;
    if (chance<16u) chance=16u;
    poke_note(g,"You threw a Poke Ball...");
    if (poke_random(g)%256u<chance) {
        g->party[g->party_count++]=g->enemy;
        mask=species_mask(g->enemy.species); g->caught_mask|=mask; g->seen_mask|=mask;
        if (g->captures!=UINT32_MAX) ++g->captures;
        g->battle_result=BATTLE_CAUGHT;
        note_join(g,"Caught ",poke_species(g->enemy.species)->name,"!");
        finish_battle(g);
    } else { poke_note(g,"It broke free!"); enemy_turn(g); }
    return POKE_OK;
}

PokeResult poke_run(PokeGame *g) {
    if (!accepts_battle_action(g)) return POKE_WRONG_MODE;
    if (g->trainer_battle) return POKE_INVALID;
    if (g->turns<UINT16_MAX) ++g->turns;
    if (g->party[g->active].speed>=g->enemy.speed || g->turns>=3 || poke_random(g)%4u!=0) {
        g->battle_result=BATTLE_RAN;
        poke_note(g,"Got away safely."); finish_battle(g);
    } else { poke_note(g,"Could not escape!"); enemy_turn(g); }
    return POKE_OK;
}

PokeResult poke_switch(PokeGame *g,uint8_t slot) {
    int battling=poke_in_battle(g),forced=g->forced_switch;
    if (g->mode!=MODE_PARTY && g->mode!=MODE_BATTLE && g->mode!=MODE_FIELD && g->mode!=MODE_MENU) return POKE_WRONG_MODE;
    if (slot>=g->party_count || slot==g->active || !g->party[slot].hp) return POKE_INVALID;
    g->active=slot; g->forced_switch=0; g->attack_stage[0]=0; g->defense_stage[0]=0;
    note_join(g,"Go, ",poke_species(g->party[slot].species)->name,"!");
    if (battling) {
        g->mode=MODE_BATTLE; g->cursor=0;
        if (!forced) { if (g->turns<UINT16_MAX) ++g->turns; enemy_turn(g); }
    } else { g->mode=MODE_FIELD; g->cursor=0; }
    return POKE_OK;
}

PokeResult poke_potion(PokeGame *g) {
    PokeMon *m;
    if (!accepts_battle_action(g)) return POKE_WRONG_MODE;
    if (!g->potions) return POKE_NO_ITEM;
    m=&g->party[g->active];
    if (m->hp==m->max_hp) return POKE_INVALID;
    --g->potions; if (g->turns<UINT16_MAX) ++g->turns;
    m->hp=(uint16_t)(m->hp+20u>m->max_hp ? m->max_hp : m->hp+20u);
    poke_note(g,"Potion restored HP."); enemy_turn(g);
    return POKE_OK;
}

static int absolute(int x) { return x<0 ? -x : x; }

void poke_walk(PokeGame *g,int dx,int dz) {
    int32_t nx,nz;
    unsigned distance;
    if (g->mode!=MODE_FIELD || (!dx && !dz)) return;
    dx=dx<0 ? -1 : dx>0 ? 1 : 0; dz=dz<0 ? -1 : dz>0 ? 1 : 0;
    nx=g->x+dx*(dz ? 23 : 32); nz=g->z+dz*(dx ? 23 : 32);
    /* Radius checks keep the proxy out of walls and prevent diagonal corner cutting. */
    if (!poke_walkable(nx-48,g->z-48) || !poke_walkable(nx+48,g->z+48) ||
        !poke_walkable(nx-48,g->z+48) || !poke_walkable(nx+48,g->z-48)) nx=g->x;
    if (!poke_walkable(nx-48,nz-48) || !poke_walkable(nx+48,nz+48) ||
        !poke_walkable(nx-48,nz+48) || !poke_walkable(nx+48,nz-48)) nz=g->z;
    if (nx==g->x && nz==g->z) return;
    distance=(nx!=g->x && nz!=g->z) ? 32u : (unsigned)(absolute((int)(nx-g->x))+absolute((int)(nz-g->z)));
    g->x=nx; g->z=nz;
    if (g->encounter_cooldown>distance) g->encounter_cooldown=(uint16_t)(g->encounter_cooldown-distance);
    else g->encounter_cooldown=0;
    g->walk_distance=(uint16_t)(g->walk_distance+distance);
    if (g->walk_distance>=POKE_TILE) {
        g->walk_distance-=POKE_TILE;
        if (g->steps!=UINT32_MAX) ++g->steps;
        if (g->party_count && !g->encounter_cooldown && poke_tile((int)(g->x/POKE_TILE),(int)(g->z/POKE_TILE))==TILE_GRASS &&
            poke_random(g)%100u<22u) {
            uint8_t species=(poke_random(g)&1u) ? POKE_RATTATA : POKE_PIDGEY;
            uint8_t level=(uint8_t)(2u+poke_random(g)%3u);
            (void)poke_start_encounter(g,species,level);
        }
    }
}

static int near_tile(const PokeGame *g,int x,int z) {
    return absolute((int)(g->x-(x*POKE_TILE+POKE_TILE/2)))+
        absolute((int)(g->z-(z*POKE_TILE+POKE_TILE/2)))<=2*POKE_TILE;
}

static void interact(PokeGame *g) {
    if (near_tile(g,8,18)) {
        if (!(g->flags&FLAG_STARTER)) { g->mode=MODE_STARTER; g->cursor=0; poke_note(g,"Oak: Choose your partner."); }
        else poke_note(g,"Oak: Catch a wild Pokemon on Route 1!");
    } else if (near_tile(g,13,19)) poke_heal(g);
    else poke_note(g,"A: talk nearby. START: party / save / load.");
}

unsigned poke_menu_count(const PokeGame *g) {
    switch (g->mode) {
        case MODE_STARTER:return 3;
        case MODE_BATTLE:return 4;
        case MODE_MOVES:return has_pp(&g->party[g->active]) ? 4 : 1;
        case MODE_BAG:return 2;
        case MODE_PARTY:return g->party_count;
        case MODE_MENU:return 4;
        default:return 0;
    }
}

const char *poke_menu_label(const PokeGame *g,unsigned index) {
    static const char *const starters[]={"Bulbasaur","Charmander","Squirtle"};
    static const char *const actions[]={"Fight","Bag","Party","Run"};
    static const char *const bag[]={"Poke Ball","Potion"};
    static const char *const menu[]={"Party","Save","Load","Continue"};
    if (index>=poke_menu_count(g)) return "";
    switch (g->mode) {
        case MODE_STARTER:return starters[index];
        case MODE_BATTLE:return actions[index];
        case MODE_MOVES:return has_pp(&g->party[g->active]) ? poke_move_info(g->party[g->active].moves[index])->name : "Struggle";
        case MODE_BAG:return bag[index];
        case MODE_PARTY:return poke_species(g->party[index].species)->name;
        case MODE_MENU:return menu[index];
        default:return "";
    }
}

static void report_result(PokeGame *g,PokeResult result) {
    switch (result) {
        case POKE_NO_PP:poke_note(g,"That move has no PP. Choose another.");break;
        case POKE_NO_ITEM:poke_note(g,"You have none left.");break;
        case POKE_PARTY_FULL:poke_note(g,"Party full. No storage box in this prototype.");break;
        case POKE_INVALID:poke_note(g,"That choice cannot be used now.");break;
        case POKE_WRONG_MODE:poke_note(g,"Choose an available action.");break;
        default:break;
    }
}

void poke_update(PokeGame *g,uint16_t held) {
    uint16_t pressed=(uint16_t)(held & ~g->previous_keys);
    unsigned count;
    PokeResult result=POKE_OK;
    g->previous_keys=held;
    if (g->mode==MODE_FIELD) {
        if (pressed&KEY_START) { g->mode=MODE_MENU; g->cursor=0; return; }
        if (pressed&KEY_A) { interact(g); return; }
        poke_walk(g,!!(held&KEY_RIGHT)-!!(held&KEY_LEFT),!!(held&KEY_DOWN)-!!(held&KEY_UP));
        return;
    }
    count=poke_menu_count(g);
    if (count && g->cursor>=count) g->cursor=0;
    if ((pressed&KEY_UP) && count) g->cursor=(uint8_t)((g->cursor+count-1u)%count);
    else if ((pressed&KEY_DOWN) && count) g->cursor=(uint8_t)((g->cursor+1u)%count);
    if (pressed&KEY_B) {
        if (g->forced_switch) return;
        if (g->mode==MODE_MOVES || g->mode==MODE_BAG || (g->mode==MODE_PARTY && g->enemy.species)) g->mode=MODE_BATTLE;
        else if (g->mode!=MODE_BATTLE) g->mode=MODE_FIELD;
        g->cursor=0; return;
    }
    if (!(pressed&KEY_A) || !count) return;
    switch (g->mode) {
        case MODE_STARTER: {
            static const uint8_t choices[]={POKE_BULBASAUR,POKE_CHARMANDER,POKE_SQUIRTLE};
            result=poke_choose_starter(g,choices[g->cursor]);break;
        }
        case MODE_BATTLE:
            if (g->cursor==0) g->mode=MODE_MOVES;
            else if (g->cursor==1) g->mode=MODE_BAG;
            else if (g->cursor==2) g->mode=MODE_PARTY;
            else result=poke_run(g);
            g->cursor=0;break;
        case MODE_MOVES:result=poke_battle_move(g,g->cursor);break;
        case MODE_BAG:result=g->cursor==0 ? poke_capture(g) : poke_potion(g);break;
        case MODE_PARTY:result=poke_switch(g,g->cursor);break;
        case MODE_MENU:
            if (g->cursor==0) {
                if (g->party_count) { g->mode=MODE_PARTY; g->cursor=0; }
                else poke_note(g,"Talk to Oak to receive your first Pokemon.");
            } else {
                if (g->cursor==1) g->request=REQUEST_SAVE;
                else if (g->cursor==2) g->request=REQUEST_LOAD;
                g->mode=MODE_FIELD; g->cursor=0;
            }
            break;
        default:break;
    }
    report_result(g,result);
}

uint8_t poke_take_request(PokeGame *g) {
    uint8_t request=g->request;
    g->request=REQUEST_NONE;
    return request;
}

const char *poke_objective(const PokeGame *g) {
    if (!(g->flags&FLAG_STARTER)) return "Talk to Oak and choose your starter.";
    if (!g->captures) return "Catch a wild Pokemon in the northern grass.";
    return "Slice complete! Heal, save, and keep exploring.";
}
