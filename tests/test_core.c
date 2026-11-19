#include "poke.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void press(PokeGame *g, uint16_t key) {
    poke_update(g, 0);
    poke_update(g, key);
}

static PokeGame started(uint8_t species, uint8_t level) {
    PokeGame g;
    poke_init(&g, 3);
    g.mode = MODE_STARTER;
    assert(poke_choose_starter(&g, species) == POKE_OK);
    poke_make_mon(&g.party[0], species, level);
    assert(poke_valid_game(&g));
    return g;
}

static void add_partner(PokeGame *g) {
    assert(g->party_count < POKE_PARTY_MAX);
    poke_make_mon(&g->party[g->party_count], g->party[0].species, g->party[0].level);
    ++g->party_count;
}

static void assert_unchanged(const PokeGame *g, const unsigned char *before) {
    assert(memcmp(g, before, sizeof(*g)) == 0);
}

static void test_starter_input_and_idempotency(void) {
    PokeGame g;
    unsigned char before[sizeof(g)];
    poke_init(&g, 3);
    assert(g.party_count == 0 && g.mode == MODE_FIELD);
    assert(poke_start_encounter(&g, POKE_RATTATA, 3) == POKE_WRONG_MODE);
    press(&g, KEY_A);
    assert(g.mode == MODE_STARTER);
    poke_update(&g, KEY_A);
    assert(g.mode == MODE_STARTER && g.party_count == 0);
    memcpy(before, &g, sizeof(g));
    assert(poke_choose_starter(&g, POKE_RATTATA) == POKE_INVALID);
    assert_unchanged(&g, before);
    press(&g, KEY_A);
    assert(g.mode == MODE_FIELD && g.party_count == 1);
    assert(g.party[0].species == POKE_BULBASAUR && g.party[0].level == 5);
    assert(g.balls == 10 && g.potions == 3 && g.flags == FLAG_STARTER);
    memcpy(before, &g, sizeof(g));
    assert(poke_choose_starter(&g, POKE_CHARMANDER) == POKE_WRONG_MODE);
    assert_unchanged(&g, before);
    poke_update(&g, KEY_A);
    assert_unchanged(&g, before);
    assert(poke_valid_game(&g));
}

static void test_movement_encounter_distance(void) {
    PokeGame g = started(POKE_BULBASAUR, 5);
    uint32_t rng;
    uint32_t steps;
    int32_t x;
    unsigned i;
    g.x = 5 * POKE_TILE + POKE_TILE / 2;
    g.z = 5 * POKE_TILE + POKE_TILE / 2;
    rng = g.rng;
    for (i = 0; i < 1000; ++i) poke_walk(&g, 0, 0);
    assert(g.rng == rng && g.steps == 0 && g.walk_distance == 0);
    for (i = 0; i < 7; ++i) poke_walk(&g, 1, 0);
    assert(g.mode == MODE_FIELD && g.rng == rng && g.steps == 0);
    assert(g.walk_distance == 224);
    poke_walk(&g, 1, 0);
    assert(g.steps == 1 && g.rng != rng);
    assert(g.mode == MODE_BATTLE); /* Seed 3's first grass roll succeeds. */
    x = g.x;
    poke_walk(&g, 1, 0);
    assert(g.x == x);

    g = started(POKE_BULBASAUR, 5);
    g.x = POKE_TILE + 48;
    g.z = 20 * POKE_TILE + POKE_TILE / 2;
    rng = g.rng;
    x = g.x;
    steps = g.steps;
    for (i = 0; i < 100; ++i) poke_walk(&g, -1, 0);
    assert(g.x == x && g.steps == steps && g.rng == rng);
    assert(g.walk_distance == 0);
    assert(poke_valid_game(&g));
}

static void test_rejected_actions_do_not_take_a_turn(void) {
    PokeGame g = started(POKE_BULBASAUR, 5);
    unsigned char before[sizeof(g)];
    assert(poke_start_encounter(&g, POKE_RATTATA, 3) == POKE_OK);
    memcpy(before, &g, sizeof(g));
    assert(poke_battle_move(&g, 255) == POKE_INVALID);
    assert_unchanged(&g, before);
    assert(poke_battle_move(&g, 2) == POKE_INVALID);
    assert_unchanged(&g, before);
    assert(poke_switch(&g, 0) == POKE_INVALID);
    assert_unchanged(&g, before);
    assert(poke_switch(&g, 6) == POKE_INVALID);
    assert_unchanged(&g, before);
    assert(poke_potion(&g) == POKE_INVALID);
    assert_unchanged(&g, before);
    poke_heal(&g);
    assert_unchanged(&g, before);
    g.party[0].pp[0] = 0;
    memcpy(before, &g, sizeof(g));
    assert(poke_battle_move(&g, 0) == POKE_NO_PP);
    assert_unchanged(&g, before);
    g.balls = 0;
    memcpy(before, &g, sizeof(g));
    assert(poke_capture(&g) == POKE_NO_ITEM);
    assert_unchanged(&g, before);
    g.potions = 0;
    memcpy(before, &g, sizeof(g));
    assert(poke_potion(&g) == POKE_NO_ITEM);
    assert_unchanged(&g, before);
    while (g.party_count < POKE_PARTY_MAX) add_partner(&g);
    g.balls = 10;
    memcpy(before, &g, sizeof(g));
    assert(poke_capture(&g) == POKE_PARTY_FULL);
    assert_unchanged(&g, before);
    assert(g.turns == 0);
}

static void test_held_button_cannot_repeat_turns(void) {
    PokeGame g = started(POKE_BULBASAUR, 20);
    uint32_t rng;
    uint16_t hp;
    uint8_t pp;
    unsigned i;
    assert(poke_start_encounter(&g, POKE_SQUIRTLE, 20) == POKE_OK);
    press(&g, KEY_A);
    assert(g.mode == MODE_MOVES && g.turns == 0);
    for (i = 0; i < 20; ++i) poke_update(&g, KEY_A);
    assert(g.mode == MODE_MOVES && g.turns == 0);
    press(&g, KEY_A);
    assert(g.mode == MODE_BATTLE && g.turns == 1);
    pp = g.party[0].pp[0];
    hp = g.party[0].hp;
    rng = g.rng;
    for (i = 0; i < 20; ++i) poke_update(&g, KEY_A);
    assert(g.mode == MODE_BATTLE && g.turns == 1);
    assert(g.party[0].pp[0] == pp && g.party[0].hp == hp && g.rng == rng);
}

static void test_first_attack_ko_and_no_double_xp(void) {
    PokeGame g = started(POKE_CHARMANDER, 100);
    uint16_t hp = g.party[0].hp;
    uint8_t pp = g.party[0].pp[0];
    unsigned char before[sizeof(g)];
    assert(poke_start_encounter(&g, POKE_RATTATA, 2) == POKE_OK);
    g.enemy.hp = 1;
    assert(poke_battle_move(&g, 0) == POKE_OK);
    assert(g.mode == MODE_FIELD && g.wins == 1);
    assert(g.party[0].hp == hp && g.party[0].pp[0] == pp - 1);
    assert(g.party[0].xp == 1000000 && g.party[0].level == 100);
    assert(g.enemy.species == POKE_NONE);
    memcpy(before, &g, sizeof(g));
    assert(poke_battle_move(&g, 0) == POKE_WRONG_MODE);
    assert_unchanged(&g, before);
    assert(poke_valid_game(&g));
}

static void force_enemy_scratch(PokeGame *g) {
    assert(poke_start_encounter(g, POKE_CHARMANDER, 100) == POKE_OK);
    g->enemy.pp[1] = 0;
    g->enemy.pp[2] = 0;
    g->party[0].hp = 1;
}

static void test_faint_forced_switch_and_blackout(void) {
    PokeGame g = started(POKE_BULBASAUR, 5);
    unsigned char before[sizeof(g)];
    uint8_t pp = g.party[0].pp[0];
    uint16_t replacement_hp;
    uint16_t turns;
    add_partner(&g);
    replacement_hp = g.party[1].hp;
    force_enemy_scratch(&g);
    assert(poke_battle_move(&g, 0) == POKE_OK);
    assert(g.mode == MODE_PARTY && g.forced_switch && g.active == 0);
    assert(g.party[0].hp == 0 && g.party[0].pp[0] == pp);
    assert(g.enemy.hp == g.enemy.max_hp);
    memcpy(before, &g, sizeof(g));
    assert(poke_battle_move(&g, 0) == POKE_WRONG_MODE);
    assert_unchanged(&g, before);
    assert(poke_capture(&g) == POKE_WRONG_MODE);
    assert_unchanged(&g, before);
    assert(poke_run(&g) == POKE_WRONG_MODE);
    assert_unchanged(&g, before);
    assert(poke_switch(&g, 0) == POKE_INVALID);
    assert_unchanged(&g, before);
    press(&g, KEY_B);
    assert(g.mode == MODE_PARTY && g.forced_switch);
    turns = g.turns;
    assert(poke_switch(&g, 1) == POKE_OK);
    assert(g.mode == MODE_BATTLE && !g.forced_switch && g.active == 1);
    assert(g.party[1].hp == replacement_hp && g.turns == turns);
    assert(poke_valid_game(&g));

    g = started(POKE_BULBASAUR, 5);
    force_enemy_scratch(&g);
    assert(poke_battle_move(&g, 0) == POKE_OK);
    assert(g.mode == MODE_FIELD && g.party[0].hp == g.party[0].max_hp);
    assert(g.party[0].pp[0] == poke_move_info(g.party[0].moves[0])->pp);
    assert(g.x == 12 * POKE_TILE + POKE_TILE / 2);
    assert(g.z == 19 * POKE_TILE + POKE_TILE / 2);
    assert(g.wins == 0 && g.enemy.species == POKE_NONE && !g.forced_switch);
    assert(poke_valid_game(&g));
}

static void test_capture_success_and_failure(void) {
    PokeGame g = started(POKE_BULBASAUR, 5);
    uint32_t xp = g.party[0].xp;
    uint8_t balls = (uint8_t)g.balls;
    unsigned char before[sizeof(g)];
    assert(poke_start_encounter(&g, POKE_BULBASAUR, 2) == POKE_OK);
    g.enemy.pp[0] = 0; /* Opponent only Growls after the failed throw. */
    g.rng = 1;
    assert(poke_capture(&g) == POKE_OK);
    assert(g.mode == MODE_BATTLE && g.party_count == 1 && g.turns == 1);
    assert(g.balls == balls - 1 && g.captures == 0 && g.enemy.pp[1] == 39);
    assert(g.attack_stage[0] == -1);
    g.rng = 8;
    assert(poke_capture(&g) == POKE_OK);
    assert(g.mode == MODE_FIELD && g.party_count == 2 && g.captures == 1);
    assert(g.balls == balls - 2 && g.party[0].xp == xp);
    assert(g.party[1].species == POKE_BULBASAUR && g.party[1].level == 2);
    assert(g.party[1].pp[0] == 0 && g.party[1].pp[1] == 39);
    assert(g.attack_stage[0] == 0 && g.defense_stage[0] == 0);
    memcpy(before, &g, sizeof(g));
    assert(poke_capture(&g) == POKE_WRONG_MODE);
    assert_unchanged(&g, before);
    assert(poke_valid_game(&g));
}

static void test_growl_floor_and_voluntary_switch(void) {
    PokeGame g = started(POKE_BULBASAUR, 100);
    uint16_t hp;
    uint16_t foe_hp;
    unsigned i;
    assert(poke_start_encounter(&g, POKE_CHARMANDER, 100) == POKE_OK);
    g.enemy.pp[0] = 0;
    g.enemy.pp[2] = 0;
    hp = g.party[0].hp;
    foe_hp = g.enemy.hp;
    for (i = 0; i < 8; ++i) assert(poke_battle_move(&g, 1) == POKE_OK);
    assert(g.attack_stage[0] == -6 && g.attack_stage[1] == -6);
    assert(g.party[0].hp == hp && g.enemy.hp == foe_hp);
    assert(g.party[0].pp[1] == 32 && g.enemy.pp[1] == 32);
    add_partner(&g);
    g.defense_stage[0] = -4;
    assert(poke_switch(&g, 1) == POKE_OK);
    assert(g.active == 1 && g.turns == 9 && g.mode == MODE_BATTLE);
    assert(g.attack_stage[0] == -1 && g.defense_stage[0] == 0);
    assert(g.attack_stage[1] == -6);
    assert(poke_valid_game(&g));
}

static void test_potion_clamps_and_consumes_one_turn(void) {
    PokeGame g = started(POKE_BULBASAUR, 5);
    uint16_t potions = g.potions;
    assert(poke_start_encounter(&g, POKE_BULBASAUR, 2) == POKE_OK);
    g.enemy.pp[0] = 0;
    g.party[0].hp = 1;
    assert(poke_potion(&g) == POKE_OK);
    assert(g.party[0].hp == g.party[0].max_hp);
    assert(g.potions == potions - 1 && g.turns == 1);
    assert(g.enemy.pp[1] == 39 && g.attack_stage[0] == -1);
    assert(g.mode == MODE_BATTLE);
    assert(poke_valid_game(&g));
}

static void test_struggle_is_available_and_causes_recoil(void) {
    PokeGame g = started(POKE_CHARMANDER, 20);
    uint16_t hp = g.party[0].hp;
    uint16_t enemy_hp;
    unsigned i;
    assert(poke_start_encounter(&g, POKE_BULBASAUR, 2) == POKE_OK);
    enemy_hp = g.enemy.hp;
    memset(g.party[0].pp, 0, sizeof(g.party[0].pp));
    g.mode = MODE_MOVES;
    assert(poke_menu_count(&g) == 1);
    assert(strcmp(poke_menu_label(&g, 0), "Struggle") == 0);
    assert(poke_battle_move(&g, 0) == POKE_OK);
    assert(g.mode == MODE_FIELD && g.wins == 1);
    assert(g.party[0].hp == hp - enemy_hp / 4);
    for (i = 0; i < POKE_MOVE_SLOTS; ++i) assert(g.party[0].pp[i] == 0);
    assert(poke_valid_game(&g));
}

static void test_level_up_learns_move_and_preserves_damage(void) {
    PokeGame g = started(POKE_BULBASAUR, 6);
    uint16_t old_max = g.party[0].max_hp;
    uint8_t old_pp = g.party[0].pp[0];
    g.party[0].xp = 342;
    g.party[0].hp -= 2;
    assert(poke_start_encounter(&g, POKE_RATTATA, 2) == POKE_OK);
    g.enemy.hp = 1;
    g.rng = 1;
    assert(poke_battle_move(&g, 0) == POKE_OK);
    assert(g.mode == MODE_FIELD && g.wins == 1);
    assert(g.party[0].level == 7 && g.party[0].xp == 358);
    assert(g.party[0].max_hp > old_max && g.party[0].hp == g.party[0].max_hp - 2);
    assert(g.party[0].moves[2] == MOVE_VINE_WHIP && g.party[0].pp[2] == 10);
    assert(g.party[0].pp[0] == old_pp - 1);
    assert(poke_valid_game(&g));
}

static void complete_journey(uint8_t *save) {
    PokeGame g;
    PokeGame restored;
    uint8_t resaved[POKE_SAVE_SIZE];
    unsigned i, j;
    poke_init(&g, 3);
    press(&g, KEY_A);
    press(&g, KEY_A);
    for (i = 0; i < 80; ++i) poke_walk(&g, 0, -1);
    for (i = 0; i < 8; ++i) poke_walk(&g, -1, 0);
    assert(g.mode == MODE_BATTLE && g.party_count == 1);
    assert(g.enemy.species == POKE_PIDGEY || g.enemy.species == POKE_RATTATA);
    assert(poke_battle_move(&g, 1) == POKE_OK);
    assert(g.mode == MODE_BATTLE);
    g.rng = 8;
    assert(poke_capture(&g) == POKE_OK);
    assert(g.mode == MODE_FIELD && g.party_count == 2 && g.captures == 1);
    for (i = 0; i < 8; ++i) poke_walk(&g, 1, 0);
    for (i = 0; i < 80; ++i) poke_walk(&g, 0, 1);
    for (i = 0; i < 24; ++i) poke_walk(&g, 1, 0);
    assert(g.mode == MODE_FIELD);
    press(&g, KEY_A);
    for (i = 0; i < g.party_count; ++i) {
        assert(g.party[i].hp == g.party[i].max_hp);
        for (j = 0; j < POKE_MOVE_SLOTS; ++j)
            assert(g.party[i].pp[j] == poke_move_info(g.party[i].moves[j])->pp);
    }
    press(&g, KEY_START);
    press(&g, KEY_DOWN);
    press(&g, KEY_A);
    assert(g.mode == MODE_FIELD);
    assert(poke_take_request(&g) == REQUEST_SAVE);
    assert(poke_take_request(&g) == REQUEST_NONE);
    assert(poke_save_encode(&g, save, POKE_SAVE_SIZE) == POKE_SAVE_SIZE);
    poke_init(&restored, 42);
    assert(poke_save_decode(&restored, save, POKE_SAVE_SIZE));
    assert(poke_save_encode(&restored, resaved, sizeof(resaved)) == POKE_SAVE_SIZE);
    assert(memcmp(save, resaved, POKE_SAVE_SIZE) == 0);
    assert(poke_start_encounter(&restored, POKE_RATTATA, 2) == POKE_OK);
    assert(poke_run(&restored) == POKE_OK);
    assert(restored.mode == MODE_FIELD && restored.party_count == 2);
    assert(poke_valid_game(&restored));
}

static void test_deterministic_complete_journey(void) {
    uint8_t a[POKE_SAVE_SIZE], b[POKE_SAVE_SIZE];
    complete_journey(a);
    complete_journey(b);
    assert(memcmp(a, b, sizeof(a)) == 0);
}

int main(void) {
    test_starter_input_and_idempotency();
    test_movement_encounter_distance();
    test_rejected_actions_do_not_take_a_turn();
    test_held_button_cannot_repeat_turns();
    test_first_attack_ko_and_no_double_xp();
    test_faint_forced_switch_and_blackout();
    test_capture_success_and_failure();
    test_growl_floor_and_voluntary_switch();
    test_potion_clamps_and_consumes_one_turn();
    test_struggle_is_available_and_causes_recoil();
    test_level_up_learns_move_and_preserves_damage();
    test_deterministic_complete_journey();
    puts("core tests passed");
    return 0;
}
