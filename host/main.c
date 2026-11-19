#define _POSIX_C_SOURCE 200809L

/* Development frontend for the exact rules module used by the N64 adapter. */
#include "poke.h"

#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct {
    const char *save_path;
    int clear;
} Host;

static const char *mon_name(const PokeMon *mon) {
    const PokeSpeciesInfo *species = poke_species(mon->species);
    return species ? species->name : "Unknown";
}

static void usage(const char *program) {
    printf("Usage: %s [--seed NUMBER] [--save FILE] [--no-clear]\n\n", program);
    puts("Pokemon N64 development console. This runs the same C rules as the N64 target.");
    puts("A valid existing save is loaded on startup. No automatic saves are made.");
    puts("\nCommands (press Enter after each):");
    puts("  w/a/s/d or up/left/down/right   Walk one tile; navigate a menu");
    puts("  j, confirm, or an empty line   A button: talk, interact, confirm");
    puts("  k or back                      B button: cancel");
    puts("  p or menu                      Start button: open field menu");
    puts("  1 through 6                    Select and confirm a visible menu entry");
    puts("  save / load                    Save or load while in the field");
    puts("  help                           Show these controls");
    puts("  q or quit                      Exit without saving");
    puts("\nMap: @ you, O Oak, + healing, : tall grass, # trees, H building, = door.");
    puts("Talk to Oak for a starter, head north into grass, then return to heal.");
    puts("--seed accepts a decimal or 0x-prefixed 32-bit integer (default 1).");
    puts("--save defaults to poke-n64.sav. Invalid existing saves are never overwritten.");
}

/* Returns 1 for a valid save, 0 for a missing file, -1 for invalid/unreadable. */
static int read_save(const char *path, PokeGame *game) {
    uint8_t bytes[POKE_SAVE_SIZE + 1];
    size_t count;
    int failed;
    FILE *file = fopen(path, "rb");
    if (!file) {
        return errno == ENOENT ? 0 : -1;
    }
    count = fread(bytes, 1, sizeof(bytes), file);
    failed = ferror(file);
    if (fclose(file) != 0) {
        failed = 1;
    }
    if (failed || count != POKE_SAVE_SIZE) {
        return -1;
    }
    return poke_save_decode(game, bytes, count) ? 1 : -1;
}

static int write_save(const char *path, const PokeGame *game) {
    uint8_t bytes[POKE_SAVE_SIZE];
    char *temporary;
    size_t length = strlen(path);
    size_t encoded;
    int fd;
    int ok = 1;
    FILE *file;
    PokeGame existing;

    encoded = poke_save_encode(game, bytes, sizeof(bytes));
    if (encoded != sizeof(bytes)) {
        return 0;
    }
    /* A broken save may be recoverable: do not silently replace it. */
    if (read_save(path, &existing) < 0) {
        return -1;
    }
    if (length > 4096) {
        return 0;
    }
    temporary = malloc(length + sizeof(".tmp.XXXXXX"));
    if (!temporary) {
        return 0;
    }
    memcpy(temporary, path, length);
    memcpy(temporary + length, ".tmp.XXXXXX", sizeof(".tmp.XXXXXX"));
    fd = mkstemp(temporary);
    if (fd < 0) {
        free(temporary);
        return 0;
    }
    file = fdopen(fd, "wb");
    if (!file) {
        close(fd);
        unlink(temporary);
        free(temporary);
        return 0;
    }
    if (fwrite(bytes, 1, encoded, file) != encoded || fflush(file) != 0) {
        ok = 0;
    }
    if (ok && fsync(fileno(file)) != 0) {
        ok = 0;
    }
    if (fclose(file) != 0) {
        ok = 0;
    }
    if (ok && rename(temporary, path) != 0) {
        ok = 0;
    }
    if (!ok) {
        unlink(temporary);
    }
    free(temporary);
    return ok;
}

static void request_io(Host *host, PokeGame *game, uint8_t request) {
    int result;
    if (request == REQUEST_NONE) {
        return;
    }
    if (game->mode != MODE_FIELD || poke_in_battle(game)) {
        poke_note(game, "Return to the field before saving or loading.");
        return;
    }
    if (request == REQUEST_SAVE) {
        result = write_save(host->save_path, game);
        if (result > 0) {
            poke_note(game, "Progress saved.");
        } else if (result < 0) {
            poke_note(game, "Existing save is invalid; it was kept untouched.");
            poke_note(game, "Restart with --save and a different file path.");
        } else {
            poke_note(game, "Save failed. Check the path and available storage.");
        }
    } else if (request == REQUEST_LOAD) {
        result = read_save(host->save_path, game);
        if (result > 0) {
            poke_note(game, "Progress loaded.");
        } else if (result == 0) {
            poke_note(game, "No save file exists yet.");
        } else {
            poke_note(game, "Invalid or unreadable save. Current game unchanged.");
        }
    }
}

static void tick(Host *host, PokeGame *game, uint16_t keys) {
    poke_update(game, keys);
    request_io(host, game, poke_take_request(game));
}

static void tap(Host *host, PokeGame *game, uint16_t key) {
    tick(host, game, key);
    tick(host, game, 0);
}

static void direction(Host *host, PokeGame *game, uint16_t key) {
    unsigned i;
    int32_t start_x = game->x;
    int32_t start_z = game->z;
    if (game->mode != MODE_FIELD) {
        tap(host, game, key);
        return;
    }
    /* Field commands traverse one tile regardless of the core's per-tick speed. */
    for (i = 0; i < 64; i++) {
        int32_t old_x = game->x;
        int32_t old_z = game->z;
        int32_t distance;
        tick(host, game, key);
        if (game->mode != MODE_FIELD) {
            break;
        }
        distance = abs(game->x - start_x) + abs(game->z - start_z);
        if (distance >= POKE_TILE || (game->x == old_x && game->z == old_z)) {
            break;
        }
    }
    tick(host, game, 0);
}

static char tile_symbol(PokeTile tile) {
    switch (tile) {
        case TILE_GRASS: return ':';
        case TILE_TREE: return '#';
        case TILE_WALL: return 'H';
        case TILE_HEAL: return '+';
        case TILE_OAK: return 'O';
        case TILE_DOOR: return '=';
        default: return '.';
    }
}

static void draw_mon(const PokeMon *mon, const char *label) {
    printf("  %-8s %-12s Lv%u  HP %u/%u  XP %" PRIu32 "\n",
           label, mon_name(mon), (unsigned)mon->level, (unsigned)mon->hp,
           (unsigned)mon->max_hp, mon->xp);
}

static void draw(const Host *host, const PokeGame *game) {
    unsigned i;
    unsigned count;
    if (host->clear) {
        fputs("\033[2J\033[H", stdout);
    }
    puts("\nPOKE N64 | Development console");
    printf("Balls %u   Potions %u   Wins %" PRIu32 "   Caught %" PRIu32 "\n",
           (unsigned)game->balls, (unsigned)game->potions, game->wins, game->captures);
    puts(poke_objective(game));
    if (!poke_in_battle(game)) {
        int x, z;
        int player_x = (int)(game->x / POKE_TILE);
        int player_z = (int)(game->z / POKE_TILE);
        for (z = 0; z < POKE_MAP_H; z++) {
            fputs("  ", stdout);
            for (x = 0; x < POKE_MAP_W; x++) {
                putchar(x == player_x && z == player_z ? '@' : tile_symbol(poke_tile(x, z)));
            }
            if (z == 1) fputs("  @ You    O Oak    + Heal", stdout);
            if (z == 2) fputs("  : Grass  # Trees  H Building", stdout);
            if (z == 4) printf("  Tile %d,%d", player_x, player_z);
            putchar('\n');
        }
    } else {
        puts("\nWILD ENCOUNTER");
        draw_mon(&game->enemy, "Wild");
        if (game->active < game->party_count) {
            draw_mon(&game->party[game->active], "Yours");
        }
        if (game->forced_switch) puts("  Choose a healthy party member.");
    }
    if (game->mode == MODE_PARTY || game->mode == MODE_FIELD) {
        puts("\nPARTY");
        if (!game->party_count) puts("  No Pokemon yet. Talk to Oak.");
        for (i = 0; i < game->party_count; i++) {
            printf("  %c %u. %-12s Lv%u HP %u/%u\n", i == game->active ? '*' : ' ',
                   i + 1, mon_name(&game->party[i]), (unsigned)game->party[i].level,
                   (unsigned)game->party[i].hp, (unsigned)game->party[i].max_hp);
        }
    }
    count = poke_menu_count(game);
    if (count) {
        puts("\nMENU");
        for (i = 0; i < count; i++) {
            printf("  %c %u. %s", i == game->cursor ? '>' : ' ', i + 1,
                   poke_menu_label(game, i));
            if (game->mode == MODE_MOVES && i < POKE_MOVE_SLOTS && game->active < game->party_count) {
                const PokeMon *mon = &game->party[game->active];
                const PokeMove *move = poke_move_info(mon->moves[i]);
                if (move && mon->moves[i] != MOVE_NONE) {
                    printf("  (PP %u/%u)", (unsigned)mon->pp[i], (unsigned)move->pp);
                }
            }
            putchar('\n');
        }
    }
    puts("\nRECENT");
    for (i = 0; i < POKE_LOG_LINES; i++) {
        if (game->log[i][0]) printf("  %s\n", game->log[i]);
    }
    puts("\nw/a/s/d move | j confirm | k back | p menu | 1-6 select | help | q quit");
    fputs("> ", stdout);
    fflush(stdout);
}

static void trim(char *text) {
    size_t length = strlen(text);
    size_t start = 0;
    while (start < length && isspace((unsigned char)text[start])) start++;
    while (length > start && isspace((unsigned char)text[length - 1])) length--;
    memmove(text, text + start, length - start);
    text[length - start] = '\0';
}

int main(int argc, char **argv) {
    Host host = { "poke-n64.sav", 0 };
    PokeGame game;
    uint32_t seed = 1;
    char command[256];
    int i;
    host.clear = isatty(STDOUT_FILENO) && isatty(STDIN_FILENO);
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            usage(argv[0]);
            return 0;
        } else if (strcmp(argv[i], "--no-clear") == 0) {
            host.clear = 0;
        } else if (strcmp(argv[i], "--save") == 0 && i + 1 < argc) {
            host.save_path = argv[++i];
            if (!host.save_path[0]) {
                fputs("--save requires a nonempty path.\n", stderr);
                return 2;
            }
        } else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) {
            char *end;
            unsigned long parsed;
            errno = 0;
            i++;
            parsed = strtoul(argv[i], &end, 0);
            if (errno || argv[i][0] == '-' || end == argv[i] || *end || parsed > UINT32_MAX) {
                fputs("--seed requires a 32-bit unsigned integer.\n", stderr);
                return 2;
            }
            seed = (uint32_t)parsed;
        } else {
            fprintf(stderr, "Unknown or incomplete option: %s\n", argv[i]);
            usage(argv[0]);
            return 2;
        }
    }
    poke_init(&game, seed);
    i = read_save(host.save_path, &game);
    if (i > 0) poke_note(&game, "Existing progress loaded.");
    if (i < 0) poke_note(&game, "Existing save invalid; it will not be overwritten.");
    for (;;) {
        unsigned count;
        draw(&host, &game);
        if (!fgets(command, sizeof(command), stdin)) {
            putchar('\n');
            break;
        }
        if (!strchr(command, '\n') && !feof(stdin)) {
            int c;
            while ((c = getchar()) != '\n' && c != EOF) {}
            poke_note(&game, "Command too long. Type help for controls.");
            continue;
        }
        trim(command);
        if (!strcmp(command, "q") || !strcmp(command, "quit")) break;
        if (!strcmp(command, "help") || !strcmp(command, "?")) {
            usage(argv[0]);
        } else if (!strcmp(command, "w") || !strcmp(command, "up")) {
            direction(&host, &game, KEY_UP);
        } else if (!strcmp(command, "s") || !strcmp(command, "down")) {
            direction(&host, &game, KEY_DOWN);
        } else if (!strcmp(command, "a") || !strcmp(command, "left")) {
            direction(&host, &game, KEY_LEFT);
        } else if (!strcmp(command, "d") || !strcmp(command, "right")) {
            direction(&host, &game, KEY_RIGHT);
        } else if (!command[0] || !strcmp(command, "j") || !strcmp(command, "confirm")) {
            tap(&host, &game, KEY_A);
        } else if (!strcmp(command, "k") || !strcmp(command, "back")) {
            tap(&host, &game, KEY_B);
        } else if (!strcmp(command, "p") || !strcmp(command, "menu")) {
            tap(&host, &game, KEY_START);
        } else if (!strcmp(command, "save")) {
            request_io(&host, &game, REQUEST_SAVE);
        } else if (!strcmp(command, "load")) {
            request_io(&host, &game, REQUEST_LOAD);
        } else if (command[0] >= '1' && command[0] <= '6' && !command[1]) {
            unsigned desired = (unsigned)(command[0] - '1');
            count = poke_menu_count(&game);
            if (desired >= count) {
                poke_note(&game, "Choose one of the visible menu entries.");
            } else {
                unsigned attempts;
                for (attempts = 0; game.cursor != desired && attempts < count; attempts++) {
                    tap(&host, &game, KEY_DOWN);
                }
                if (game.cursor == desired) tap(&host, &game, KEY_A);
            }
        } else {
            poke_note(&game, "Unknown command. Type help for controls.");
        }
    }
    puts("Exited. Only explicitly saved progress is retained.");
    return ferror(stdin) ? 1 : 0;
}
