#include "poke_intro.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void confirm(PokeIntro* s,PokeGame* g) { poke_intro_update(s,g,5,3,KEY_A); }
static void enter(PokeIntro* s,unsigned room,unsigned spawn) {
    assert(s->warp_pending && s->warp_room==room && s->warp_spawn==spawn);
    poke_intro_enter(s,(uint8_t)room);
    assert(!s->warp_pending && !s->warp_armed);
}
static void to_lab(PokeIntro* s,PokeGame* g,int potion) {
    int x,z,px=10,pz=1;
    poke_intro_init(s); poke_intro_enter(s,INTRO_BEDROOM);
    assert(s->stage==INTRO_WAKE && poke_intro_locked(s));
    confirm(s,g);
    assert(s->stage==INTRO_EXPLORE && !poke_intro_locked(s));
    if (potion) {
        poke_intro_update(s,g,0,2,KEY_A);
        assert(s->talk==TALK_PC && g->potions==1);
        confirm(s,g);
        poke_intro_update(s,g,0,2,KEY_A);
        assert(s->talk==TALK_PC_EMPTY && g->potions==1);
        confirm(s,g);
    }
    poke_intro_update(s,g,6,1,0); poke_intro_update(s,g,7,1,0);
    enter(s,INTRO_HOME,0);
    poke_intro_update(s,g,6,1,0); poke_intro_update(s,g,3,7,0);
    enter(s,INTRO_PALLET,0);
    poke_intro_update(s,g,5,6,0); poke_intro_update(s,g,10,1,0);
    assert(s->talk==TALK_OAK_WARNING && s->stage==INTRO_OAK_WARNING);
    confirm(s,g);
    assert(s->stage==INTRO_ESCORT);
    while (poke_intro_escort_target(s,&x,&z)) {
        /* Every escort segment must remain on the original passable cells. */
        while (px!=x || pz!=z) {
            if (px!=x) px+=px<x ? 1 : -1;
            else pz+=pz<z ? 1 : -1;
            assert(poke_intro_walkable(INTRO_PALLET,px,pz));
        }
        poke_intro_escort_arrived(s);
    }
    assert(s->stage==INTRO_LAB_WELCOME);
    enter(s,INTRO_LAB,1); confirm(s,g);
    assert(s->stage==INTRO_CHOOSE);
    poke_intro_update(s,g,4,6,0);
    assert(s->talk==TALK_PICK_FIRST && s->reposition && s->reposition_z==5);
    s->reposition=0; confirm(s,g);
}

static unsigned journey(uint8_t starter,uint32_t seed,int potion) {
    PokeGame g,before;
    PokeIntro s;
    unsigned turns=0;
    int x=starter==POKE_CHARMANDER ? 6 : starter==POKE_SQUIRTLE ? 7 : 8;
    poke_init(&g,seed);
    to_lab(&s,&g,potion);
    poke_intro_update(&s,&g,x,4,KEY_A);
    assert(s.talk==TALK_BALL && s.selection==starter && !g.party_count);
    poke_intro_update(&s,&g,x,4,KEY_B);
    assert(!s.talk && !g.party_count);
    poke_intro_update(&s,&g,x,4,KEY_A);
    confirm(&s,&g);
    assert(s.stage==INTRO_CHOSEN && s.talk==TALK_CHOSEN);
    assert(g.party_count==1 && g.party[0].species==starter && g.party[0].level==5);
    assert(g.balls==0 && g.potions==(unsigned)potion);
    assert(s.rival==poke_intro_rival(starter));
    confirm(&s,&g);
    poke_intro_update(&s,&g,4,6,0);
    assert(s.stage==INTRO_RIVAL_CHALLENGE && !poke_in_battle(&g));
    confirm(&s,&g);
    assert(s.stage==INTRO_RIVAL_BATTLE && g.trainer_battle && poke_in_battle(&g));
    assert(g.enemy.species==s.rival && g.enemy.level==5);
    assert(g.party[0].moves[2]==MOVE_NONE && g.enemy.moves[2]==MOVE_NONE);
    before=g;
    assert(poke_run(&g)==POKE_INVALID && !memcmp(&g,&before,sizeof(g)));
    assert(poke_capture(&g)==POKE_INVALID && !memcmp(&g,&before,sizeof(g)));
    while (poke_in_battle(&g) && turns++<120) assert(poke_battle_move(&g,0)==POKE_OK);
    assert(!poke_in_battle(&g));
    assert(g.battle_result==BATTLE_WON || g.battle_result==BATTLE_LOST);
    poke_intro_update(&s,&g,4,6,0);
    assert(s.stage==INTRO_AFTER_BATTLE && s.talk==TALK_RESULT);
    assert(s.outcome==g.battle_result && g.party[0].hp==g.party[0].max_hp);
    assert(g.party[0].pp[0]==poke_move_info(g.party[0].moves[0])->pp);
    assert(g.balls==0 && g.potions==(unsigned)potion);
    confirm(&s,&g);
    assert(s.stage==INTRO_COMPLETE && !poke_intro_locked(&s));
    poke_intro_update(&s,&g,4,6,0);
    assert(s.stage==INTRO_COMPLETE && !poke_in_battle(&g));
    poke_intro_update(&s,&g,4,11,0);
    enter(&s,INTRO_PALLET,2);
    assert(g.party_count==1 && s.stage==INTRO_COMPLETE);
    assert(poke_valid_game(&g));
    return s.outcome;
}
static void test_entering_lab_early_does_not_skip_oak(void) {
    PokeIntro s;PokeGame g;
    poke_init(&g,1);poke_intro_init(&s);confirm(&s,&g);
    poke_intro_enter(&s,INTRO_LAB);
    poke_intro_update(&s,&g,8,4,KEY_A);
    assert(s.talk==TALK_OAK_AWAY && !g.party_count && s.stage==INTRO_EXPLORE);
}
static void test_facing_distinguishes_oak_blue_and_ball(void) {
    PokeIntro s;PokeGame g;
    poke_init(&g,1);poke_intro_init(&s);
    s.room=INTRO_LAB;s.stage=INTRO_CHOOSE;s.talk=TALK_NONE;
    poke_intro_face(&s,0,-1);poke_intro_update(&s,&g,5,3,KEY_A);
    assert(s.talk==TALK_LAB_WELCOME);confirm(&s,&g);
    poke_intro_face(&s,-1,0);poke_intro_update(&s,&g,5,3,KEY_A);
    assert(s.talk==TALK_BLUE);confirm(&s,&g);
    poke_intro_face(&s,1,0);poke_intro_update(&s,&g,5,3,KEY_A);
    assert(s.talk==TALK_BALL && s.selection==POKE_CHARMANDER);
    poke_intro_update(&s,&g,5,3,KEY_B);
    poke_intro_face(&s,0,1);poke_intro_update(&s,&g,7,2,KEY_A);
    assert(s.talk==TALK_BALL && s.selection==POKE_SQUIRTLE);
    poke_intro_update(&s,&g,7,2,KEY_B);
    poke_intro_face(&s,-1,0);poke_intro_update(&s,&g,9,3,KEY_A);
    assert(s.talk==TALK_BALL && s.selection==POKE_BULBASAUR);
}
static void test_pc_preserves_existing_items_and_waits_for_bag_space(void) {
    PokeIntro s;PokeGame g;
    poke_init(&g,1);poke_intro_init(&s);confirm(&s,&g);
    g.potions=99;
    poke_intro_update(&s,&g,0,2,KEY_A);
    assert(s.talk==TALK_PC_FULL && !s.pc_taken && g.potions==99);
    confirm(&s,&g);g.potions=4;
    poke_intro_update(&s,&g,0,2,KEY_A);
    assert(s.pc_taken && g.potions==5);confirm(&s,&g);
    poke_intro_update(&s,&g,0,2,KEY_A);
    assert(s.talk==TALK_PC_EMPTY && g.potions==5);
}
static void test_early_lab_round_trip_and_right_hand_oak_trigger(void) {
    PokeIntro s;PokeGame g;
    poke_init(&g,1);poke_intro_init(&s);confirm(&s,&g);
    poke_intro_enter(&s,INTRO_PALLET);
    poke_intro_update(&s,&g,12,12,0);poke_intro_update(&s,&g,12,11,0);
    enter(&s,INTRO_LAB,0);
    poke_intro_update(&s,&g,4,11,0);assert(!s.warp_pending);
    poke_intro_update(&s,&g,4,10,0);poke_intro_update(&s,&g,4,11,0);
    enter(&s,INTRO_PALLET,2);
    assert(s.stage==INTRO_EXPLORE && !g.party_count);
    poke_intro_update(&s,&g,12,12,0);poke_intro_update(&s,&g,11,1,0);
    assert(s.stage==INTRO_OAK_WARNING);confirm(&s,&g);
    assert(s.stage==INTRO_ESCORT);
}
int main(void) {
    const uint8_t starters[]={POKE_BULBASAUR,POKE_CHARMANDER,POKE_SQUIRTLE};
    unsigned i,seed,wins=0,losses=0;
    test_entering_lab_early_does_not_skip_oak();
    test_facing_distinguishes_oak_blue_and_ball();
    test_pc_preserves_existing_items_and_waits_for_bag_space();
    test_early_lab_round_trip_and_right_hand_oak_trigger();
    for(i=0;i<3;++i) for(seed=1;seed<=32;++seed) {
        unsigned outcome=journey(starters[i],seed,seed%2);
        if(outcome==BATTLE_WON) ++wins; else ++losses;
    }
    assert(wins && losses);
    printf("opening tests passed: 96 journeys, %u wins / %u losses, all three starters\n",wins,losses);
    return 0;
}
