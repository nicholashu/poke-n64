#include "poke_pallet_import.h"
#include <string.h>

#define CONFIRM 16u
#define WALK_SPEED 4

static int in_bounds(const PokePalletMap* map, int x, int y) {
    return map && x >= 0 && y >= 0 && x < map->width && y < map->height;
}

int poke_pallet_static_walkable(const PokePalletMap* map, int x, int y) {
    return in_bounds(map, x, y) && map->walkable &&
           map->walkable[y * map->width + x] == 1;
}

static int bounded_string(const char* text, unsigned limit) {
    unsigned i;
    if (!text) return 0;
    for (i = 0; i < limit; ++i) {
        unsigned char c = (unsigned char)text[i];
        if (!c) return 1;
        if ((c < 32 || c > 126) && c != '\n' && c != '\f') return 0;
    }
    return 0;
}

int poke_pallet_validate(const PokePalletMap* map) {
    unsigned i, j, oak_count = 0;
    if (!map || !map->enabled || !map->width || !map->height ||
        map->width > 32 || map->height > 32 ||
        (unsigned)map->width * map->height > POKE_PALLET_MAX_CELLS ||
        !map->walkable || !map->texts ||
        !map->object_count || map->object_count > 32 || !map->objects ||
        !map->warp_count || map->warp_count > 16 || !map->warps ||
        map->lab_warp_index >= map->warp_count || map->sign_count > 32 ||
        (map->sign_count && !map->signs) || map->connection_count > 4 ||
        (map->connection_count && !map->connections) ||
        !poke_pallet_static_walkable(map, map->spawn_x, map->spawn_y)) return 0;
    for (i = 0; i < (unsigned)map->width * map->height; ++i)
        if (map->walkable[i] > 1) return 0;
    for (i = 1; i < POKE_PALLET_TEXT_COUNT; ++i)
        if (!bounded_string(map->texts[i], POKE_PALLET_TEXT_LIMIT)) return 0;
    for (i = 0; i < map->object_count; ++i) {
        const PokePalletObject* object = &map->objects[i];
        if (!object->id || object->visible > 1 ||
            object->text_id >= POKE_PALLET_TEXT_COUNT ||
            !poke_pallet_static_walkable(map, object->x, object->y)) return 0;
        if (object->id == map->oak_object_id) ++oak_count;
        if (object->visible && object->x == map->spawn_x && object->y == map->spawn_y)
            return 0;
        for (j = 0; j < i; ++j)
            if (map->objects[j].id == object->id) return 0;
    }
    if (oak_count != 1) return 0;
    for (i = 0; i < map->warp_count; ++i) {
        const PokePalletWarp* warp = &map->warps[i];
        if (!poke_pallet_static_walkable(map, warp->x, warp->y) ||
            !bounded_string(warp->destination_name, 64)) return 0;
    }
    for (i = 0; i < map->sign_count; ++i)
        if (!in_bounds(map, map->signs[i].x, map->signs[i].y) ||
            !map->signs[i].text_id || map->signs[i].text_id >= POKE_PALLET_TEXT_COUNT)
            return 0;
    for (i = 0; i < map->connection_count; ++i) {
        const PokePalletConnection* connection = &map->connections[i];
        if (connection->direction > POKE_PALLET_EAST ||
            !bounded_string(connection->destination_name, 64)) return 0;
        for (j = 0; j < i; ++j)
            if (map->connections[j].direction == connection->direction) return 0;
    }
    return 1;
}

int poke_pallet_init(PokePalletState* state, const PokePalletMap* map) {
    unsigned i;
    if (!state) return 0;
    memset(state, 0, sizeof(*state));
    if (!poke_pallet_validate(map)) return 0;
    state->active = 1;
    state->stage = POKE_PALLET_EXPLORE;
    state->face_y = 1;
    state->player_x = (int16_t)(map->spawn_x * POKE_PALLET_CELL);
    state->player_y = (int16_t)(map->spawn_y * POKE_PALLET_CELL);
    for (i = 0; i < map->object_count; ++i)
        if (map->objects[i].id == map->oak_object_id) {
            state->oak_x = (int16_t)(map->objects[i].x * POKE_PALLET_CELL);
            state->oak_y = (int16_t)(map->objects[i].y * POKE_PALLET_CELL);
        }
    /* Pallet's Oak is hidden until the first north-exit encounter. */
    state->oak_visible = 0;
    return 1;
}

int poke_pallet_locked(const PokePalletState* state) {
    return state && state->active && (state->talking ||
           state->stage == POKE_PALLET_OAK_APPROACH ||
           state->stage == POKE_PALLET_ESCORT);
}

int poke_pallet_object_visible(const PokePalletState* state,
                               const PokePalletMap* map, unsigned index) {
    if (!state || !map || index >= map->object_count) return 0;
    return map->objects[index].id == map->oak_object_id ?
           state->oak_visible : map->objects[index].visible;
}

void poke_pallet_face(PokePalletState* state, int x, int y) {
    if (!state || poke_pallet_locked(state)) return;
    state->face_x = (int8_t)(x < 0 ? -1 : x > 0 ? 1 : 0);
    state->face_y = state->face_x ? 0 : (int8_t)(y < 0 ? -1 : y > 0 ? 1 : 0);
}

static int cell(int value) {
    /* Callers reject values below the first cell edge before this division. */
    return (value + POKE_PALLET_CELL / 2) / POKE_PALLET_CELL;
}

static int occupied(const PokePalletState* state, const PokePalletMap* map,
                    int x, int y, int include_oak) {
    unsigned i;
    for (i = 0; i < map->object_count; ++i) {
        const PokePalletObject* object = &map->objects[i];
        if (!poke_pallet_object_visible(state, map, i)) continue;
        if (object->id == map->oak_object_id) {
            if (include_oak && cell(state->oak_x) == x && cell(state->oak_y) == y) return 1;
        } else if (object->x == x && object->y == y) return 1;
    }
    return 0;
}

static void page(PokePalletState* state) {
    unsigned line, cursor = state->text_offset;
    const char* text = state->message;
    memset(state->lines, 0, sizeof(state->lines));
    for (line = 0; line < POKE_PALLET_TEXT_LINES && text[cursor]; ++line) {
        unsigned start, length = 0;
        int space = -1;
        while (text[cursor] == ' ') ++cursor;
        if (text[cursor] == '\f') { ++cursor; break; }
        start = cursor;
        while (text[cursor] && text[cursor] != '\n' && text[cursor] != '\f' &&
               length < POKE_PALLET_TEXT_WIDTH) {
            if (text[cursor] == ' ') space = (int)length;
            state->lines[line][length++] = text[cursor++];
        }
        if (length == POKE_PALLET_TEXT_WIDTH && text[cursor] &&
            text[cursor] != '\n' && text[cursor] != '\f' && space >= 0) {
            length = (unsigned)space;
            cursor = start + length + 1;
        }
        while (length && state->lines[line][length - 1] == ' ') --length;
        state->lines[line][length] = '\0';
        if (text[cursor] == '\n') ++cursor;
        else if (text[cursor] == '\f') { ++cursor; break; }
    }
    state->text_offset = (uint16_t)cursor;
    state->page_more = text[cursor] != '\0';
}

static void say(PokePalletState* state, const PokePalletMap* map, unsigned text_id) {
    state->talking = 1;
    state->text_id = (uint8_t)text_id;
    state->text_offset = 0;
    state->message = map->texts[text_id];
    page(state);
}

static void append(char* out, unsigned capacity, const char* value) {
    unsigned at = 0;
    while (at + 1 < capacity && out[at]) ++at;
    while (at + 1 < capacity && *value) out[at++] = *value++;
    out[at] = '\0';
}

static void notice(PokePalletState* state, const char* first, const char* rest) {
    state->notice[0] = '\0';
    append(state->notice, sizeof(state->notice), first);
    append(state->notice, sizeof(state->notice), rest);
    state->message = state->notice;
    state->text_id = POKE_PALLET_TEXT_NONE;
    state->text_offset = 0;
    state->talking = 1;
    page(state);
}

static void unsupported(PokePalletState* state, const char* destination) {
    notice(state, destination, "\nThis destination is not included.\nNo scene transition was performed.");
    state->boundary_armed = 0;
}

/* Breadth-first paths use only imported walkable cells and visible object
 * positions. No synthetic straight-line move is allowed through a building. */
static int path(PokePalletState* state, const PokePalletMap* map,
                int start_x, int start_y, int goal_x, int goal_y, int avoid_player) {
    int16_t parent[POKE_PALLET_MAX_CELLS];
    uint16_t queue[POKE_PALLET_MAX_CELLS];
    unsigned head = 0, tail = 0, count = (unsigned)map->width * map->height, i;
    int start, goal, current;
    static const int8_t dx[4] = {0, -1, 1, 0};
    static const int8_t dy[4] = {1, 0, 0, -1};
    state->path_length = state->path_index = 0;
    if (!poke_pallet_static_walkable(map, start_x, start_y) ||
        !poke_pallet_static_walkable(map, goal_x, goal_y) ||
        occupied(state, map, goal_x, goal_y, 0)) return 0;
    start = start_y * map->width + start_x;
    goal = goal_y * map->width + goal_x;
    for (i = 0; i < count; ++i) parent[i] = -1;
    parent[start] = (int16_t)start;
    queue[tail++] = (uint16_t)start;
    while (head < tail && parent[goal] < 0) {
        current = queue[head++];
        for (i = 0; i < 4; ++i) {
            int x = current % map->width + dx[i], y = current / map->width + dy[i];
            int next;
            if (!poke_pallet_static_walkable(map, x, y) || occupied(state, map, x, y, 0)) continue;
            if (avoid_player && x == cell(state->player_x) && y == cell(state->player_y)) continue;
            next = y * map->width + x;
            if (parent[next] >= 0) continue;
            parent[next] = (int16_t)current;
            queue[tail++] = (uint16_t)next;
        }
    }
    if (parent[goal] < 0) return 0;
    current = goal;
    for (;;) {
        state->path[state->path_length++] = (uint16_t)current;
        if (current == start) break;
        current = parent[current];
    }
    for (i = 0; i < state->path_length / 2; ++i) {
        uint16_t temp = state->path[i];
        state->path[i] = state->path[state->path_length - 1 - i];
        state->path[state->path_length - 1 - i] = temp;
    }
    return 1;
}

static void blocked(PokePalletState* state) {
    state->stage = POKE_PALLET_SCRIPT_BLOCKED;
    state->path_length = 0;
    notice(state, "Oak's route is blocked.", "\nThe event stopped safely.\nStory progress has not advanced.");
}

static void approach(PokePalletState* state, const PokePalletMap* map) {
    const PokePalletWarp* lab = &map->warps[map->lab_warp_index];
    int target;
    state->oak_visible = 1;
    if (!path(state, map, cell(state->player_x), cell(state->player_y), lab->x, lab->y, 0) ||
        state->path_length < 2) { blocked(state); return; }
    target = state->path[1];
    if (!path(state, map, cell(state->oak_x), cell(state->oak_y),
              target % map->width, target / map->width, 1)) { blocked(state); return; }
    state->stage = POKE_PALLET_OAK_APPROACH;
    state->path_index = 0;
}

static void escort(PokePalletState* state, const PokePalletMap* map) {
    const PokePalletWarp* lab = &map->warps[map->lab_warp_index];
    if (!path(state, map, cell(state->player_x), cell(state->player_y), lab->x, lab->y, 0) ||
        state->path_length < 2) { blocked(state); return; }
    state->stage = POKE_PALLET_ESCORT;
    state->path_index = 0;
}

static int move(int16_t* x, int16_t* y, int target_x, int target_y) {
    int delta;
    if (*x != target_x) {
        delta = target_x - *x;
        *x = (int16_t)(*x + (delta > WALK_SPEED ? WALK_SPEED : delta < -WALK_SPEED ? -WALK_SPEED : delta));
    } else if (*y != target_y) {
        delta = target_y - *y;
        *y = (int16_t)(*y + (delta > WALK_SPEED ? WALK_SPEED : delta < -WALK_SPEED ? -WALK_SPEED : delta));
    }
    return *x == target_x && *y == target_y;
}

static void scripted_step(PokePalletState* state, const PokePalletMap* map) {
    unsigned target = state->path[state->path_index];
    int x = (int)(target % map->width) * POKE_PALLET_CELL;
    int y = (int)(target / map->width) * POKE_PALLET_CELL;
    if (state->stage == POKE_PALLET_OAK_APPROACH) {
        if (move(&state->oak_x, &state->oak_y, x, y) && ++state->path_index == state->path_length) {
            state->stage = POKE_PALLET_OAK_WARNING;
            say(state, map, POKE_PALLET_TEXT_OAK_UNSAFE);
        }
    } else {
        int player_arrived = move(&state->player_x, &state->player_y, x, y);
        int oak_arrived;
        unsigned ahead = state->path_index + 1;
        if (ahead >= state->path_length) {
            state->oak_visible = 0;
            oak_arrived = 1;
        } else {
            target = state->path[ahead];
            oak_arrived = move(&state->oak_x, &state->oak_y,
                               (int)(target % map->width) * POKE_PALLET_CELL,
                               (int)(target / map->width) * POKE_PALLET_CELL);
        }
        if (player_arrived && oak_arrived && ++state->path_index == state->path_length) {
            state->stage = POKE_PALLET_LAB_BOUNDARY;
            unsupported(state, map->warps[map->lab_warp_index].destination_name);
            /* The original flag is set after entering the lab. The scene
             * is not imported here, so do not claim that event occurred. */
            state->followed_oak_into_lab = 0;
        }
    }
}

static int on_boundary(PokePalletState* state, const PokePalletMap* map,
                       int x, int y, int activate) {
    unsigned i;
    for (i = 0; i < map->warp_count; ++i)
        if (map->warps[i].x == x && map->warps[i].y == y) {
            if (activate) unsupported(state, map->warps[i].destination_name);
            return 1;
        }
    for (i = 0; i < map->connection_count; ++i) {
        unsigned direction = map->connections[i].direction;
        if ((direction == POKE_PALLET_NORTH && y == 0) ||
            (direction == POKE_PALLET_SOUTH && y == map->height - 1) ||
            (direction == POKE_PALLET_WEST && x == 0) ||
            (direction == POKE_PALLET_EAST && x == map->width - 1)) {
            if (activate) unsupported(state, map->connections[i].destination_name);
            return 1;
        }
    }
    return 0;
}

void poke_pallet_update(PokePalletState* state, const PokePalletMap* map,
                        int player_x, int player_y, uint16_t pressed) {
    unsigned i;
    int x, y;
    if (!state || !state->active || !map) return;
    if (state->talking) {
        if (!(pressed & CONFIRM)) return;
        if (state->page_more) { page(state); return; }
        state->talking = 0;
        if (state->stage == POKE_PALLET_OAK_CALL) approach(state, map);
        else if (state->stage == POKE_PALLET_OAK_WARNING) escort(state, map);
        return;
    }
    if (state->stage == POKE_PALLET_OAK_APPROACH || state->stage == POKE_PALLET_ESCORT) {
        scripted_step(state, map);
        return;
    }
    if (player_x >= -POKE_PALLET_CELL / 2 && player_y >= -POKE_PALLET_CELL / 2 &&
        player_x < map->width * POKE_PALLET_CELL - POKE_PALLET_CELL / 2 &&
        player_y < map->height * POKE_PALLET_CELL - POKE_PALLET_CELL / 2) {
        x = cell(player_x); y = cell(player_y);
        if (poke_pallet_static_walkable(map, x, y) && !occupied(state, map, x, y, 1)) {
            state->player_x = (int16_t)player_x;
            state->player_y = (int16_t)player_y;
        }
    }
    x = cell(state->player_x); y = cell(state->player_y);
    if (state->stage == POKE_PALLET_EXPLORE && y == 1) {
        state->stage = POKE_PALLET_OAK_CALL;
        state->face_x = 0; state->face_y = 1;
        say(state, map, POKE_PALLET_TEXT_OAK_HEY_WAIT);
        return;
    }
    if (on_boundary(state, map, x, y, state->boundary_armed)) return;
    state->boundary_armed = 1;
    if (!(pressed & CONFIRM)) return;
    x += state->face_x; y += state->face_y;
    for (i = 0; i < map->object_count; ++i) {
        const PokePalletObject* object = &map->objects[i];
        if (!poke_pallet_object_visible(state, map, i)) continue;
        if ((object->id == map->oak_object_id && cell(state->oak_x) == x && cell(state->oak_y) == y) ||
            (object->id != map->oak_object_id && object->x == x && object->y == y)) {
            if (object->text_id) say(state, map, object->text_id);
            return;
        }
    }
    for (i = 0; i < map->sign_count; ++i)
        if (map->signs[i].x == x && map->signs[i].y == y) {
            say(state, map, map->signs[i].text_id);
            return;
        }
    (void)on_boundary(state, map, x, y, 1);
}
