#include "poke.h"

#include <string.h>

/* Version 1, exactly 256 bytes. Offsets and widths are part of the file format.
 * Header: magic[4], version:u16, size:u16.
 * 8: rng:u32, x:i32, z:i32, steps:u32, wins:u32, captures:u32.
 * 32: balls:u16, potions:u16, flags:u16, walk_distance:u16, cooldown:u16.
 * 42: party_count:u8, active:u8, seen_mask:u8, caught_mask:u8, reserved[2].
 * 48: six 26-byte monsters. Each: species:u8, level:u8, hp:u16,
 * max_hp:u16, attack:u16, defense:u16, speed:u16, special:u16, xp:u32,
 * moves[4], pp[4]. Inactive monster slots are all zero.
 * 204: reserved[48], all zero. 252: CRC32 of bytes 0 through 251.
 * Integers are little-endian; signed coordinates use two's complement.
 */
enum {
    SAVE_HEADER_SIZE = 48,
    SAVE_MON_SIZE = 26,
    SAVE_RESERVED_OFFSET = SAVE_HEADER_SIZE + POKE_PARTY_MAX * SAVE_MON_SIZE,
    SAVE_CRC_OFFSET = POKE_SAVE_SIZE - 4
};

static void write_u16(uint8_t *out, uint16_t value) {
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
}

static void write_u32(uint8_t *out, uint32_t value) {
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
    out[2] = (uint8_t)(value >> 16);
    out[3] = (uint8_t)(value >> 24);
}

static uint16_t read_u16(const uint8_t *in) {
    return (uint16_t)((uint16_t)in[0] | ((uint16_t)in[1] << 8));
}

static uint32_t read_u32(const uint8_t *in) {
    return (uint32_t)in[0] | ((uint32_t)in[1] << 8) |
           ((uint32_t)in[2] << 16) | ((uint32_t)in[3] << 24);
}

static int32_t read_i32(const uint8_t *in) {
    uint32_t value = read_u32(in);
    /* Avoid implementation-defined conversion of an out-of-range uint32_t. */
    return value <= INT32_MAX ? (int32_t)value : -1 - (int32_t)(~value);
}

static int bytes_are_zero(const uint8_t *bytes, size_t length) {
    size_t i;
    for (i = 0; i < length; ++i) {
        if (bytes[i] != 0) {
            return 0;
        }
    }
    return 1;
}

uint32_t poke_crc32(const uint8_t *bytes, size_t length) {
    uint32_t crc = UINT32_MAX;
    size_t i;
    unsigned bit;
    if (bytes == NULL) {
        return 0;
    }
    for (i = 0; i < length; ++i) {
        crc ^= bytes[i];
        for (bit = 0; bit < 8; ++bit) {
            uint32_t mask = 0u - (crc & 1u);
            crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & mask);
        }
    }
    return ~crc;
}

static void encode_mon(uint8_t *out, const PokeMon *mon) {
    out[0] = mon->species;
    out[1] = mon->level;
    write_u16(out + 2, mon->hp);
    write_u16(out + 4, mon->max_hp);
    write_u16(out + 6, mon->attack);
    write_u16(out + 8, mon->defense);
    write_u16(out + 10, mon->speed);
    write_u16(out + 12, mon->special);
    write_u32(out + 14, mon->xp);
    memcpy(out + 18, mon->moves, POKE_MOVE_SLOTS);
    memcpy(out + 22, mon->pp, POKE_MOVE_SLOTS);
}

static void decode_mon(PokeMon *mon, const uint8_t *bytes) {
    mon->species = bytes[0];
    mon->level = bytes[1];
    mon->hp = read_u16(bytes + 2);
    mon->max_hp = read_u16(bytes + 4);
    mon->attack = read_u16(bytes + 6);
    mon->defense = read_u16(bytes + 8);
    mon->speed = read_u16(bytes + 10);
    mon->special = read_u16(bytes + 12);
    mon->xp = read_u32(bytes + 14);
    memcpy(mon->moves, bytes + 18, POKE_MOVE_SLOTS);
    memcpy(mon->pp, bytes + 22, POKE_MOVE_SLOTS);
}

size_t poke_save_encode(const PokeGame *game, uint8_t *out, size_t capacity) {
    uint8_t bytes[POKE_SAVE_SIZE] = {0};
    unsigned i;
    if (game == NULL || out == NULL || capacity < POKE_SAVE_SIZE ||
        (game->mode != MODE_FIELD && game->mode != MODE_MENU) ||
        !poke_valid_game(game)) {
        return 0;
    }
    memcpy(bytes, "PK64", 4);
    write_u16(bytes + 4, POKE_SAVE_VERSION);
    write_u16(bytes + 6, POKE_SAVE_SIZE);
    write_u32(bytes + 8, game->rng);
    write_u32(bytes + 12, (uint32_t)game->x);
    write_u32(bytes + 16, (uint32_t)game->z);
    write_u32(bytes + 20, game->steps);
    write_u32(bytes + 24, game->wins);
    write_u32(bytes + 28, game->captures);
    write_u16(bytes + 32, game->balls);
    write_u16(bytes + 34, game->potions);
    write_u16(bytes + 36, game->flags);
    write_u16(bytes + 38, game->walk_distance);
    write_u16(bytes + 40, game->encounter_cooldown);
    bytes[42] = game->party_count;
    bytes[43] = game->active;
    bytes[44] = game->seen_mask;
    bytes[45] = game->caught_mask;
    for (i = 0; i < game->party_count; ++i) {
        encode_mon(bytes + SAVE_HEADER_SIZE + i * SAVE_MON_SIZE, &game->party[i]);
    }
    write_u32(bytes + SAVE_CRC_OFFSET, poke_crc32(bytes, SAVE_CRC_OFFSET));
    memcpy(out, bytes, sizeof(bytes));
    return sizeof(bytes);
}

int poke_save_decode(PokeGame *game, const uint8_t *bytes, size_t length) {
    PokeGame restored;
    unsigned i;
    if (game == NULL || bytes == NULL || length != POKE_SAVE_SIZE ||
        bytes[0] != 'P' || bytes[1] != 'K' || bytes[2] != '6' || bytes[3] != '4' ||
        read_u16(bytes + 4) != POKE_SAVE_VERSION ||
        read_u16(bytes + 6) != POKE_SAVE_SIZE ||
        read_u32(bytes + SAVE_CRC_OFFSET) != poke_crc32(bytes, SAVE_CRC_OFFSET) ||
        bytes[42] > POKE_PARTY_MAX ||
        !bytes_are_zero(bytes + 46, 2) ||
        !bytes_are_zero(bytes + SAVE_RESERVED_OFFSET, SAVE_CRC_OFFSET - SAVE_RESERVED_OFFSET)) {
        return 0;
    }
    /* Keep the caller's live state intact even when semantic validation fails. */
    memset(&restored, 0, sizeof(restored));
    restored.rng = read_u32(bytes + 8);
    restored.x = read_i32(bytes + 12);
    restored.z = read_i32(bytes + 16);
    restored.steps = read_u32(bytes + 20);
    restored.wins = read_u32(bytes + 24);
    restored.captures = read_u32(bytes + 28);
    restored.balls = read_u16(bytes + 32);
    restored.potions = read_u16(bytes + 34);
    restored.flags = read_u16(bytes + 36);
    restored.walk_distance = read_u16(bytes + 38);
    restored.encounter_cooldown = read_u16(bytes + 40);
    restored.party_count = bytes[42];
    restored.active = bytes[43];
    restored.seen_mask = bytes[44];
    restored.caught_mask = bytes[45];
    restored.mode = MODE_FIELD;
    for (i = 0; i < restored.party_count; ++i) {
        decode_mon(&restored.party[i], bytes + SAVE_HEADER_SIZE + i * SAVE_MON_SIZE);
        if (!poke_valid_mon(&restored.party[i])) {
            return 0;
        }
    }
    for (; i < POKE_PARTY_MAX; ++i) {
        if (!bytes_are_zero(bytes + SAVE_HEADER_SIZE + i * SAVE_MON_SIZE, SAVE_MON_SIZE)) {
            return 0;
        }
    }
    if (!poke_valid_game(&restored)) {
        return 0;
    }
    *game = restored;
    return 1;
}
