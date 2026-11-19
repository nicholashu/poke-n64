#include "poke_pallet_import.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* Invented content and map geometry: no ROM fixture or extracted dialogue. */
static uint8_t grid[8 * 8];
static const char* const texts[POKE_PALLET_TEXT_COUNT] = {
    0, "Wait at the town boundary.", "Please follow me to the lab.",
    "First line.\nSecond line.\nThird line.\nFourth line.",
    "An invented fisher greeting.", "Research building.", "A small test town.",
    "The player's home.", "The neighbour's home."
};
static const PokePalletObject objects[] = {
    {1, 2, 4, 5, 0, POKE_PALLET_TEXT_OAK_HEY_WAIT},
    {2, 1, 4, 6, 1, POKE_PALLET_TEXT_GIRL},
    {3, 6, 5, 7, 1, POKE_PALLET_TEXT_FISHER}
};
static const PokePalletWarp warps[] = {
    {1, 6, 37, 0, "Player's home"}, {6, 6, 40, 1, "Test laboratory"}
};
static const PokePalletSign signs[] = {{6, 3, POKE_PALLET_TEXT_LAB_SIGN}};
static const PokePalletConnection connections[] = {
    {POKE_PALLET_NORTH, 12, "North route"},
    {POKE_PALLET_SOUTH, 32, "South route"}
};

static PokePalletMap fixture(void) {
    PokePalletMap map = {
        .enabled = 1, .width = 8, .height = 8, .spawn_x = 4, .spawn_y = 5,
        .oak_object_id = 1, .lab_warp_index = 1, .walkable = grid,
        .object_count = 3, .warp_count = 2, .sign_count = 1, .connection_count = 2,
        .objects = objects, .warps = warps, .signs = signs,
        .connections = connections, .texts = texts
    };
    memset(grid, 1, sizeof(grid));
    /* A wall forces Oak's escort to route around it. */
    grid[3 * 8 + 3] = grid[3 * 8 + 4] = grid[3 * 8 + 6] = 0;
    return map;
}

static void tick(PokePalletState* state, const PokePalletMap* map, uint16_t keys) {
    poke_pallet_update(state, map, state->player_x, state->player_y, keys);
}

static void at(PokePalletState* state, const PokePalletMap* map, int x, int y, uint16_t keys) {
    poke_pallet_update(state, map, x * POKE_PALLET_CELL, y * POKE_PALLET_CELL, keys);
}

static void close_text(PokePalletState* state, const PokePalletMap* map) {
    unsigned pages = 0;
    while (state->talking) {
        assert(++pages < 100);
        tick(state, map, 16);
    }
}

static void test_validation(void) {
    PokePalletMap map = fixture();
    PokePalletState state;
    assert(poke_pallet_validate(&map));
    assert(poke_pallet_init(&state, &map));
    assert(state.active && !state.oak_visible && !state.followed_oak_into_lab);
    assert(!poke_pallet_static_walkable(&map, -1, 2));
    assert(!poke_pallet_static_walkable(&map, 8, 2));
    assert(!poke_pallet_static_walkable(&map, 3, 3));
    map.lab_warp_index = 2;
    assert(!poke_pallet_init(&state, &map));
    assert(!state.active);
    map = fixture(); map.enabled = 0;
    assert(!poke_pallet_init(&state, &map));
    map = fixture(); map.object_count = 0;
    assert(!poke_pallet_validate(&map));
    map = fixture(); grid[0] = 2;
    assert(!poke_pallet_validate(&map));
    map = fixture(); map.width = 33;
    assert(!poke_pallet_validate(&map));
    map = fixture(); map.texts = 0;
    assert(!poke_pallet_validate(&map));
    map = fixture(); map.spawn_x = 3; map.spawn_y = 3;
    assert(!poke_pallet_validate(&map));
}

static void test_facing_text_and_blocked_cells(void) {
    PokePalletMap map = fixture();
    PokePalletState state;
    map.spawn_x = 1; map.spawn_y = 5;
    assert(poke_pallet_init(&state, &map));
    poke_pallet_face(&state, -1, 0);
    tick(&state, &map, 16);
    assert(!state.talking);
    poke_pallet_face(&state, 0, -1);
    tick(&state, &map, 16);
    assert(state.text_id == POKE_PALLET_TEXT_GIRL);
    assert(state.talking && state.page_more && poke_pallet_locked(&state));
    assert(!strcmp(state.lines[0], "First line."));
    assert(!strcmp(state.lines[2], "Third line."));
    at(&state, &map, 4, 5, 0);
    assert(state.player_x == POKE_PALLET_CELL && state.player_y == 5 * POKE_PALLET_CELL);
    tick(&state, &map, 16);
    assert(state.talking && !state.page_more);
    assert(!strcmp(state.lines[0], "Fourth line."));
    tick(&state, &map, 16);
    assert(!state.talking && !poke_pallet_locked(&state));
    at(&state, &map, 1, 4, 0); /* Visible NPC occupies this walkable floor. */
    assert(state.player_y == 5 * POKE_PALLET_CELL);
    at(&state, &map, 3, 3, 0); /* Imported wall. */
    assert(state.player_x == POKE_PALLET_CELL && state.player_y == 5 * POKE_PALLET_CELL);
    at(&state, &map, -1, 5, 0);
    assert(state.player_x == POKE_PALLET_CELL);
    at(&state, &map, 5, 3, 0);
    poke_pallet_face(&state, 1, 0);
    tick(&state, &map, 16);
    assert(state.talking && state.text_id == POKE_PALLET_TEXT_LAB_SIGN);
}

static void test_unsupported_destinations_and_rearming(void) {
    PokePalletMap map = fixture();
    PokePalletState state;
    map.spawn_x = 1; map.spawn_y = 5;
    assert(poke_pallet_init(&state, &map));
    tick(&state, &map, 0); /* Arm only after leaving a boundary. */
    at(&state, &map, 1, 6, 0);
    assert(state.talking && strstr(state.notice, "Player's home"));
    assert(strstr(state.notice, "not included"));
    assert(!state.followed_oak_into_lab);
    close_text(&state, &map);
    tick(&state, &map, 0);
    assert(!state.talking);
    at(&state, &map, 1, 5, 0);
    at(&state, &map, 1, 6, 0);
    assert(state.talking); /* Leaving and returning creates a new interaction. */
    close_text(&state, &map);
    at(&state, &map, 2, 6, 0);
    at(&state, &map, 2, 7, 0);
    assert(state.talking && strstr(state.notice, "South route"));
    close_text(&state, &map);
    at(&state, &map, 2, 2, 0);
    at(&state, &map, 2, 0, 0);
    assert(state.talking && strstr(state.notice, "North route"));
}

static void assert_on_floor(const PokePalletState* state, const PokePalletMap* map) {
    assert(poke_pallet_static_walkable(map,
            (state->player_x + 40) / 80, (state->player_y + 40) / 80));
    if (state->oak_visible)
        assert(poke_pallet_static_walkable(map,
                (state->oak_x + 40) / 80, (state->oak_y + 40) / 80));
}

static void test_oak_sequence_and_frame_movement(void) {
    PokePalletMap map = fixture();
    PokePalletState state;
    unsigned frames = 0;
    map.spawn_x = 4; map.spawn_y = 2;
    assert(poke_pallet_init(&state, &map));
    assert(!poke_pallet_object_visible(&state, &map, 0));
    at(&state, &map, 4, 1, 0);
    assert(state.stage == POKE_PALLET_OAK_CALL && state.talking);
    assert(state.text_id == POKE_PALLET_TEXT_OAK_HEY_WAIT && !state.oak_visible);
    close_text(&state, &map);
    assert(state.stage == POKE_PALLET_OAK_APPROACH && state.oak_visible);
    while (state.stage == POKE_PALLET_OAK_APPROACH) {
        int old_x = state.oak_x, old_y = state.oak_y;
        tick(&state, &map, 0);
        assert(++frames < 1000);
        assert(state.oak_x - old_x <= 4 && state.oak_x - old_x >= -4);
        assert(state.oak_y - old_y <= 4 && state.oak_y - old_y >= -4);
        assert(state.player_x == 4 * 80 && state.player_y == 80);
        assert_on_floor(&state, &map);
    }
    assert(frames > 40); /* Movement happens over real frames, not one teleport. */
    assert(state.stage == POKE_PALLET_OAK_WARNING && state.talking);
    assert(state.text_id == POKE_PALLET_TEXT_OAK_UNSAFE);
    close_text(&state, &map);
    assert(state.stage == POKE_PALLET_ESCORT);
    while (state.stage == POKE_PALLET_ESCORT) {
        int old_x = state.player_x, old_y = state.player_y;
        tick(&state, &map, 0);
        assert(++frames < 2000);
        assert(state.player_x - old_x <= 4 && state.player_x - old_x >= -4);
        assert(state.player_y - old_y <= 4 && state.player_y - old_y >= -4);
        assert_on_floor(&state, &map);
    }
    assert(state.stage == POKE_PALLET_LAB_BOUNDARY && state.talking);
    assert(state.player_x == 6 * 80 && state.player_y == 6 * 80);
    assert(strstr(state.notice, "Test laboratory"));
    assert(!state.followed_oak_into_lab);
    close_text(&state, &map);
    tick(&state, &map, 0);
    assert(!state.talking); /* No endlessly repeating doorway prompt. */
    at(&state, &map, 4, 1, 0);
    assert(state.stage == POKE_PALLET_LAB_BOUNDARY && !state.talking);
    assert(!state.followed_oak_into_lab); /* Re-entering the row cannot fake completion. */
}

static void test_unreachable_lab_fails_without_teleport(void) {
    PokePalletMap map = fixture();
    PokePalletState state;
    unsigned x;
    for (x = 0; x < 8; ++x) grid[3 * 8 + x] = 0;
    map.spawn_x = 4; map.spawn_y = 2;
    assert(poke_pallet_init(&state, &map));
    at(&state, &map, 4, 1, 0);
    tick(&state, &map, 16);
    assert(state.stage == POKE_PALLET_SCRIPT_BLOCKED);
    assert(state.talking && strstr(state.notice, "blocked"));
    assert(state.player_x == 4 * 80 && state.player_y == 80);
    assert(!state.followed_oak_into_lab);
}

static void test_long_text_wraps_without_loss(void) {
    static const char long_text[] =
        "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    const char* custom[POKE_PALLET_TEXT_COUNT];
    PokePalletMap map = fixture();
    PokePalletState state;
    char output[sizeof(long_text)];
    unsigned i, at_out = 0, pages = 0;
    for (i = 0; i < POKE_PALLET_TEXT_COUNT; ++i) custom[i] = texts[i];
    custom[POKE_PALLET_TEXT_GIRL] = long_text;
    map.texts = custom; map.spawn_x = 1; map.spawn_y = 5;
    assert(poke_pallet_init(&state, &map));
    poke_pallet_face(&state, 0, -1);
    tick(&state, &map, 16);
    while (state.talking) {
        assert(++pages < 10);
        for (i = 0; i < POKE_PALLET_TEXT_LINES; ++i) {
            unsigned length = (unsigned)strlen(state.lines[i]);
            assert(length <= POKE_PALLET_TEXT_WIDTH);
            memcpy(output + at_out, state.lines[i], length);
            at_out += length;
        }
        tick(&state, &map, 16);
    }
    output[at_out] = '\0';
    assert(pages == 2 && !strcmp(output, long_text));
}

int main(void) {
    test_validation();
    test_facing_text_and_blocked_cells();
    test_unsupported_destinations_and_rearming();
    test_oak_sequence_and_frame_movement();
    test_unreachable_lab_fails_without_teleport();
    test_long_text_wraps_without_loss();
    puts("Pallet import runtime: all checks passed.");
    return 0;
}
