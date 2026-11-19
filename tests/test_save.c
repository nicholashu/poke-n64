#include "poke.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

/* These offsets are the public v1 file contract, not a sizeof(struct) layout. */
enum { CRC_OFFSET = 252, FIRST_MON = 48, MON_SIZE = 26 };

static void put_u32(uint8_t *out, uint32_t value) {
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
    out[2] = (uint8_t)(value >> 16);
    out[3] = (uint8_t)(value >> 24);
}

static void fix_checksum(uint8_t *bytes) {
    put_u32(bytes + CRC_OFFSET, poke_crc32(bytes, CRC_OFFSET));
}

static PokeGame example_game(void) {
    PokeGame game;
    poke_init(&game, UINT32_C(0x12345678));
    game.mode = MODE_STARTER;
    assert(poke_choose_starter(&game, POKE_BULBASAUR) == POKE_OK);
    game.mode = MODE_FIELD;
    game.steps = UINT32_C(0x01020304);
    game.wins = 7;
    game.captures = 2;
    game.balls = 12;
    game.potions = 9;
    game.walk_distance = 17;
    game.encounter_cooldown = 3;
    assert(poke_valid_game(&game));
    return game;
}

static void same_mon(const PokeMon *a, const PokeMon *b) {
    assert(a->species == b->species);
    assert(a->level == b->level);
    assert(a->hp == b->hp);
    assert(a->max_hp == b->max_hp);
    assert(a->attack == b->attack);
    assert(a->defense == b->defense);
    assert(a->speed == b->speed);
    assert(a->special == b->special);
    assert(a->xp == b->xp);
    assert(memcmp(a->moves, b->moves, POKE_MOVE_SLOTS) == 0);
    assert(memcmp(a->pp, b->pp, POKE_MOVE_SLOTS) == 0);
}

static void same_persistent_state(const PokeGame *a, const PokeGame *b) {
    unsigned i;
    assert(a->rng == b->rng);
    assert(a->x == b->x && a->z == b->z);
    assert(a->steps == b->steps);
    assert(a->wins == b->wins);
    assert(a->captures == b->captures);
    assert(a->balls == b->balls && a->potions == b->potions);
    assert(a->flags == b->flags);
    assert(a->walk_distance == b->walk_distance);
    assert(a->encounter_cooldown == b->encounter_cooldown);
    assert(a->party_count == b->party_count && a->active == b->active);
    assert(a->seen_mask == b->seen_mask && a->caught_mask == b->caught_mask);
    for (i = 0; i < a->party_count; ++i) {
        same_mon(&a->party[i], &b->party[i]);
    }
}

static void assert_rejected_unchanged(const uint8_t *bytes, size_t length) {
    PokeGame target;
    uint8_t snapshot[sizeof(target)];
    memset(&target, 0xa5, sizeof(target));
    memcpy(snapshot, &target, sizeof(target));
    assert(poke_save_decode(&target, bytes, length) == 0);
    assert(memcmp(snapshot, &target, sizeof(target)) == 0);
}

static void test_crc_known_vector(void) {
    static const uint8_t text[] = "123456789";
    assert(poke_crc32(text, sizeof(text) - 1) == UINT32_C(0xcbf43926));
    assert(poke_crc32(text, 0) == 0);
    assert(poke_crc32(NULL, 0) == 0);
}

static void test_roundtrip_and_transient_reset(void) {
    uint8_t bytes[POKE_SAVE_SIZE];
    uint8_t again[POKE_SAVE_SIZE];
    PokeGame game = example_game();
    PokeGame target;
    unsigned i;
    game.mode = MODE_MENU;
    game.cursor = 2;
    game.previous_keys = KEY_START | KEY_A;
    game.request = REQUEST_SAVE;
    game.turns = 77;
    game.attack_stage[0] = -3;
    game.defense_stage[1] = 2;
    poke_note(&game, "Do not serialize UI logs.");
    assert(poke_save_encode(&game, bytes, sizeof(bytes)) == POKE_SAVE_SIZE);
    memset(&target, 0xa5, sizeof(target));
    assert(poke_save_decode(&target, bytes, sizeof(bytes)) == 1);
    same_persistent_state(&game, &target);
    assert(target.mode == MODE_FIELD);
    assert(target.cursor == 0 && target.previous_keys == 0);
    assert(target.request == REQUEST_NONE && target.forced_switch == 0);
    assert(target.turns == 0 && target.enemy.species == POKE_NONE);
    for (i = 0; i < 2; ++i) {
        assert(target.attack_stage[i] == 0 && target.defense_stage[i] == 0);
    }
    for (i = 0; i < POKE_LOG_LINES; ++i) {
        assert(target.log[i][0] == '\0');
    }
    assert(poke_save_encode(&target, again, sizeof(again)) == POKE_SAVE_SIZE);
    assert(memcmp(bytes, again, sizeof(bytes)) == 0);
}

static void test_empty_and_full_party(void) {
    PokeGame game;
    PokeGame loaded;
    uint8_t bytes[POKE_SAVE_SIZE];
    unsigned i;
    poke_init(&game, 99);
    assert(game.party_count == 0);
    assert(poke_save_encode(&game, bytes, sizeof(bytes)) == POKE_SAVE_SIZE);
    assert(poke_save_decode(&loaded, bytes, sizeof(bytes)));
    same_persistent_state(&game, &loaded);
    game = example_game();
    for (i = 1; i < POKE_PARTY_MAX; ++i) {
        poke_make_mon(&game.party[i], POKE_BULBASAUR, (uint8_t)(5 + i));
        game.party[i].hp -= 1;
        game.party[i].pp[0] -= 1;
    }
    game.party_count = POKE_PARTY_MAX;
    game.active = POKE_PARTY_MAX - 1;
    assert(poke_valid_game(&game));
    assert(poke_save_encode(&game, bytes, sizeof(bytes)) == POKE_SAVE_SIZE);
    assert(poke_save_decode(&loaded, bytes, sizeof(bytes)));
    same_persistent_state(&game, &loaded);
}

static void test_byte_order_fixture(void) {
    PokeGame game = example_game();
    uint8_t bytes[POKE_SAVE_SIZE];
    static const uint8_t header[] = {'P', 'K', '6', '4', 1, 0, 0, 1};
    static const uint8_t rng[] = {0x78, 0x56, 0x34, 0x12};
    static const uint8_t steps[] = {4, 3, 2, 1};
    /* Selecting a starter may consume random numbers; pin this fixture explicitly. */
    game.rng = UINT32_C(0x12345678);
    assert(poke_save_encode(&game, bytes, sizeof(bytes)) == POKE_SAVE_SIZE);
    assert(memcmp(bytes, header, sizeof(header)) == 0);
    assert(memcmp(bytes + 8, rng, sizeof(rng)) == 0);
    assert(memcmp(bytes + 20, steps, sizeof(steps)) == 0);
    assert(bytes[32] == 12 && bytes[33] == 0);
    assert(bytes[42] == 1 && bytes[43] == 0);
    assert(bytes[FIRST_MON] == POKE_BULBASAUR);
    /* First starter is level 5: the MVP cubic curve gives 125 XP. */
    assert(bytes[FIRST_MON + 1] == 5);
    assert(bytes[FIRST_MON + 14] == 125);
    assert(bytes[FIRST_MON + 15] == 0 && bytes[FIRST_MON + 16] == 0 && bytes[FIRST_MON + 17] == 0);
}

static void test_truncation_and_tamper(void) {
    PokeGame game = example_game();
    uint8_t bytes[POKE_SAVE_SIZE];
    uint8_t corrupt[POKE_SAVE_SIZE];
    size_t i;
    assert(poke_save_encode(&game, bytes, sizeof(bytes)) == POKE_SAVE_SIZE);
    for (i = 0; i < POKE_SAVE_SIZE; ++i) {
        assert_rejected_unchanged(bytes, i);
        memcpy(corrupt, bytes, sizeof(corrupt));
        corrupt[i] ^= 0x01;
        assert_rejected_unchanged(corrupt, sizeof(corrupt));
    }
    assert_rejected_unchanged(bytes, POKE_SAVE_SIZE + 1);
    assert_rejected_unchanged(NULL, POKE_SAVE_SIZE);
    assert(poke_save_decode(NULL, bytes, sizeof(bytes)) == 0);
}

static void test_semantic_rejection_after_valid_checksum(void) {
    PokeGame game = example_game();
    uint8_t bytes[POKE_SAVE_SIZE];
    uint8_t bad[POKE_SAVE_SIZE];
    static const struct {
        size_t offset;
        uint8_t value;
    } mutations[] = {
        {0, 'X'}, {4, 2}, {6, 0xff}, {42, 7}, {43, 6}, {37, 0x80},
        {44, 0x80}, {45, 0x80}, {46, 1}, {204, 1},
        {FIRST_MON, 255}, {FIRST_MON + 1, 1}, {FIRST_MON + 3, 255},
        {FIRST_MON + 5, 255}, {FIRST_MON + 18, 255}, {FIRST_MON + 22, 255},
        {FIRST_MON + MON_SIZE, POKE_RATTATA}
    };
    size_t i;
    assert(poke_save_encode(&game, bytes, sizeof(bytes)) == POKE_SAVE_SIZE);
    for (i = 0; i < sizeof(mutations) / sizeof(mutations[0]); ++i) {
        memcpy(bad, bytes, sizeof(bad));
        bad[mutations[i].offset] = mutations[i].value;
        fix_checksum(bad);
        assert_rejected_unchanged(bad, sizeof(bad));
    }
    memcpy(bad, bytes, sizeof(bad));
    put_u32(bad + 12, UINT32_C(0xffffffff));
    fix_checksum(bad);
    assert_rejected_unchanged(bad, sizeof(bad));
    /* The center is on a path, but the actor's collision radius overlaps trees. */
    memcpy(bad, bytes, sizeof(bad));
    put_u32(bad + 12, POKE_TILE + 1);
    put_u32(bad + 16, 20 * POKE_TILE + POKE_TILE / 2);
    fix_checksum(bad);
    assert_rejected_unchanged(bad, sizeof(bad));
    memcpy(bad, bytes, sizeof(bad));
    put_u32(bad + FIRST_MON + 14, UINT32_MAX);
    fix_checksum(bad);
    assert_rejected_unchanged(bad, sizeof(bad));
}

static void test_encode_failure_and_output_capacity(void) {
    PokeGame game = example_game();
    uint8_t out[POKE_SAVE_SIZE + 8];
    uint8_t unchanged[sizeof(out)];
    unsigned mode;
    memset(out, 0xa5, sizeof(out));
    memcpy(unchanged, out, sizeof(out));
    assert(poke_save_encode(&game, out, POKE_SAVE_SIZE - 1) == 0);
    assert(memcmp(out, unchanged, sizeof(out)) == 0);
    assert(poke_save_encode(NULL, out, sizeof(out)) == 0);
    assert(memcmp(out, unchanged, sizeof(out)) == 0);
    assert(poke_save_encode(&game, NULL, POKE_SAVE_SIZE) == 0);
    for (mode = MODE_STARTER; mode <= MODE_PARTY; ++mode) {
        game.mode = (uint8_t)mode;
        assert(poke_save_encode(&game, out, sizeof(out)) == 0);
        assert(memcmp(out, unchanged, sizeof(out)) == 0);
    }
    game.mode = MODE_FIELD;
    game.party_count = POKE_PARTY_MAX + 1;
    assert(poke_save_encode(&game, out, sizeof(out)) == 0);
    assert(memcmp(out, unchanged, sizeof(out)) == 0);
    game = example_game();
    assert(poke_save_encode(&game, out, sizeof(out)) == POKE_SAVE_SIZE);
    assert(memcmp(out + POKE_SAVE_SIZE, unchanged + POKE_SAVE_SIZE, 8) == 0);
}

int main(void) {
    test_crc_known_vector();
    test_roundtrip_and_transient_reset();
    test_empty_and_full_party();
    test_byte_order_fixture();
    test_truncation_and_tamper();
    test_semantic_rejection_after_valid_checksum();
    test_encode_failure_and_output_capacity();
    puts("save tests passed");
    return 0;
}
