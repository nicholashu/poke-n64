"""Read Pallet Town from a locally supplied, unmodified English Red/Blue ROM.

This module contains format knowledge and addresses, never a copy of a map,
dialogue, sprite, or ROM.  ``extract_pallet`` is the production entry point and
requires a known whole-ROM digest.  ``parse_pallet`` deliberately separates the
binary parser from identification so tests can use entirely synthetic bytes.

Format reference: pret/pokered ba9c0568f64ae602fadda577a08c66639f93082a,
macros/scripts/maps.asm, data/tilesets/tileset_headers.asm, home/overworld.asm,
engine/overworld/player_state.asm, scripts/PalletTown.asm, and
engine/overworld/auto_movement.asm. Addresses are from the public pokered.sym
and pokeblue.sym at SYMBOL_REFERENCE_COMMIT; the relevant addresses agree.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any


REFERENCE_COMMIT = "ba9c0568f64ae602fadda577a08c66639f93082a"
SYMBOL_REFERENCE_COMMIT = "c88672bb44df548ac21d7f6651047ffc43fd3750"
SYMBOL_BLOBS = {"red": "c1eb442ceb5de957995f1f69ca9d6a0aec0d01d4",
                "blue": "f3203b82645d944db43c9c4f479dd57cd573fcb1"}
ROM_SIZE = 0x100000
BANK_SIZE = 0x4000
MAX_MAPS = 0xF8
MAX_TEXT_BYTES = 4096


class RomError(ValueError):
    """Unsupported input or malformed data, without modifying any output."""


@dataclass(frozen=True)
class RomProfile:
    game: str
    sha1: str
    title: str
    size: int = ROM_SIZE
    map_pointers: int = 0x01AE
    map_banks: int = 0xC23D
    tilesets: int = 0xC7BE
    toggle_pointers: int = 0xC8F5
    overworld_block_count: int = 128
    overworld_ram: int = 0xC6E8
    oak_hey_wait: tuple[int, int] = (0x29, 0x4245)
    oak_unsafe: tuple[int, int] = (0x29, 0x4264)
    oak_movement: tuple[int, int] = (0x06, 0x64DC)
    player_movement: tuple[int, int] = (0x06, 0x64E9)


PROFILES = (
    RomProfile("red", "ea9bcae617fdf159b045185467ae58b2e4a48b9a", "POKEMON RED"),
    RomProfile("blue", "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2", "POKEMON BLUE"),
)


def validate_header(data: bytes, profile: RomProfile) -> None:
    """Validate size, English retail cartridge fields and both GB checksums."""
    if len(data) != profile.size:
        raise RomError(f"Expected {profile.size} ROM bytes, received {len(data)}")
    if len(data) < 0x150:
        raise RomError("ROM is shorter than a Game Boy cartridge header")
    if data[0x134:0x144].rstrip(b"\0") != profile.title.encode("ascii"):
        raise RomError("ROM title does not match the supported version")
    # RGBDS retail build flags in pret/pokered: MBC3+RAM+BATTERY, 1 MiB,
    # 32 KiB RAM, non-Japanese, revision zero. Hash remains the authority.
    if data[0x147:0x14A] != bytes((0x13, 0x05, 0x03)):
        raise RomError("Unsupported cartridge type, ROM size or RAM size header")
    if data[0x14A] != 1 or data[0x14C] != 0:
        raise RomError("Only the supported English retail revision is accepted")
    header_checksum = 0
    for value in data[0x134:0x14D]:
        header_checksum = (header_checksum - value - 1) & 0xFF
    if data[0x14D] != header_checksum:
        raise RomError("Game Boy header checksum mismatch")
    global_checksum = (sum(data[:0x14E]) + sum(data[0x150:])) & 0xFFFF
    if int.from_bytes(data[0x14E:0x150], "big") != global_checksum:
        raise RomError("Game Boy global checksum mismatch")


def identify_rom(data: bytes) -> RomProfile:
    if len(data) != ROM_SIZE:
        raise RomError(f"Expected a {ROM_SIZE}-byte English Pokémon Red or Blue ROM")
    digest = hashlib.sha1(data).hexdigest()
    for profile in PROFILES:
        if digest == profile.sha1:
            validate_header(data, profile)
            return profile
    raise RomError(
        "Unsupported ROM SHA-1 " + digest + ". Only the unmodified English "
        "Red/Blue revisions listed in PROFILES are supported; Yellow, translated "
        "ROMs and hacks need their own verified profiles."
    )


class RomReader:
    """Bounded ROM reads with Game Boy ROM0/ROMX bank semantics."""

    def __init__(self, data: bytes):
        self.data = data

    def read(self, offset: int, length: int, context: str = "ROM data") -> bytes:
        if offset < 0 or length < 0 or offset > len(self.data) - length:
            raise RomError(f"{context}: read outside ROM at 0x{offset:x} ({length} bytes)")
        if length and offset // BANK_SIZE != (offset + length - 1) // BANK_SIZE:
            raise RomError(f"{context}: read crosses a 16 KiB ROM bank")
        return self.data[offset:offset + length]

    def pointer(self, bank: int, address: int, length: int = 1,
                context: str = "ROM pointer") -> int:
        if not 0 <= address < 0x8000:
            raise RomError(f"{context}: 0x{address:04x} is not a ROM address")
        if address < BANK_SIZE:
            offset = address  # ROM0 is fixed, even if a nonzero bank was supplied.
        else:
            if bank <= 0 or bank * BANK_SIZE >= len(self.data):
                raise RomError(f"{context}: invalid switchable ROM bank {bank}")
            offset = bank * BANK_SIZE + address - BANK_SIZE
        self.read(offset, length, context)
        return offset

    def byte(self, offset: int, context: str = "byte") -> int:
        return self.read(offset, 1, context)[0]

    def word(self, offset: int, context: str = "word") -> int:
        return int.from_bytes(self.read(offset, 2, context), "little")


class _Cursor:
    def __init__(self, rom: RomReader, offset: int, context: str):
        self.rom, self.start, self.offset, self.context = rom, offset, offset, context

    def read(self, length: int) -> bytes:
        # Individual reads may fit while the whole record crosses the bank.
        self.rom.read(self.start, self.offset - self.start + length, self.context)
        result = self.rom.read(self.offset, length, self.context)
        self.offset += length
        return result

    def byte(self) -> int:
        return self.read(1)[0]

    def word(self) -> int:
        return int.from_bytes(self.read(2), "little")


def _count(cursor: _Cursor, maximum: int, name: str) -> int:
    count = cursor.byte()
    if count > maximum:
        raise RomError(f"Too many {name}: {count}, maximum {maximum}")
    return count


def _coordinates(x: int, y: int, width: int, height: int, what: str) -> None:
    if not (0 <= x < width and 0 <= y < height):
        raise RomError(f"{what}: ({x}, {y}) is outside {width} x {height} walking cells")


def _map_location(rom: RomReader, profile: RomProfile, map_id: int) -> tuple[int, int]:
    if not 0 <= map_id < MAX_MAPS:
        raise RomError(f"Invalid map ID {map_id}")
    bank = rom.byte(profile.map_banks + map_id, "map bank table")
    address = rom.word(profile.map_pointers + map_id * 2, "map pointer table")
    return bank, rom.pointer(bank, address, 10, f"map {map_id} header")


def _signed_byte(value: int) -> int:
    return value - 256 if value >= 128 else value


def _objects(rom: RomReader, profile: RomProfile, bank: int, address: int,
             width: int, height: int) -> dict[str, Any]:
    offset = rom.pointer(bank, address, context="Pallet object data")
    cur = _Cursor(rom, offset, "Pallet object data")
    border = cur.byte()
    warps = []
    for index in range(_count(cur, 32, "warps")):
        y, x, destination_warp, destination_map = cur.read(4)
        _coordinates(x, y, width, height, "warp")
        if destination_map != 0xFF and destination_map >= MAX_MAPS:
            raise RomError("Invalid warp destination map")
        if destination_warp >= 32:
            raise RomError("Invalid destination warp index")
        warps.append({"id": index, "x": x, "y": y,
                      "destination_map": destination_map,
                      "destination_warp": destination_warp,
                      "destination_uses_last_map": destination_map == 0xFF})
    signs = []
    for _ in range(_count(cur, 16, "signs")):
        y, x, text_id = cur.read(3)
        _coordinates(x, y, width, height, "sign")
        if not 1 <= text_id <= 0x3F:
            raise RomError("Invalid sign text ID")
        signs.append({"x": x, "y": y, "text_id": text_id})
    objects = []
    for index in range(_count(cur, 16, "objects")):
        sprite, stored_y, stored_x, movement, facing, flags = cur.read(6)
        x, y = stored_x - 4, stored_y - 4
        _coordinates(x, y, width, height, "object")
        if flags & 0xC0 == 0xC0:
            raise RomError("Object cannot be both a trainer and an item")
        text_id = flags & 0x3F
        if not text_id:
            raise RomError("Object text ID cannot be zero")
        obj = {"id": index + 1, "x": x, "y": y, "sprite_id": sprite,
               "movement": movement, "range_or_facing": facing,
               "text_id": text_id, "text_flags": flags,
               "kind": "npc", "visible_on_start": True}
        if flags & 0x40:
            obj.update(kind="trainer", trainer_class=cur.byte(), trainer_number=cur.byte())
        elif flags & 0x80:
            obj.update(kind="item", item_id=cur.byte())
        objects.append(obj)
    spawns = []
    for index, warp in enumerate(warps):
        ram_pointer, y, x = cur.word(), cur.byte(), cur.byte()
        _coordinates(x, y, width, height, "warp spawn")
        expected = (profile.overworld_ram + 7 + width // 2
                    + (width // 2 + 6) * (y >> 1) + (x >> 1))
        if ram_pointer != expected or (x, y) != (warp["x"], warp["y"]):
            raise RomError("Warp spawn displacement does not match its map coordinates")
        spawns.append({"id": index, "x": x, "y": y, "gb_ram_pointer": ram_pointer})

    # Initial visibility is stored separately from each object record. OFF/ON
    # are 0x11/0x15, not booleans. Stop when a different map begins.
    toggle_bank = profile.toggle_pointers // BANK_SIZE
    toggle_address = rom.word(profile.toggle_pointers, "Pallet toggle pointer")
    toggle = _Cursor(rom, rom.pointer(toggle_bank, toggle_address,
                                     context="Pallet object toggles"), "Pallet object toggles")
    seen = set()
    for _ in range(17):
        map_id = toggle.byte()
        if map_id != 0:
            break
        object_id, state = toggle.byte(), toggle.byte()
        if not 1 <= object_id <= len(objects) or object_id in seen:
            raise RomError("Invalid or repeated toggleable object ID")
        if state not in (0x11, 0x15):
            raise RomError("Invalid initial object visibility")
        seen.add(object_id)
        objects[object_id - 1]["visible_on_start"] = state == 0x15
    else:
        raise RomError("Unterminated Pallet toggle data")
    return {"object_rom_offset": offset, "border_block": border, "warps": warps,
            "signs": signs, "objects": objects, "spawn_warps": spawns}


# Alphabet ranges and control-token meanings are format definitions. Original
# game strings are only read from the user's ROM, and never appear here.
_CHARS = {
    0x49: "\n\n", 0x4A: "<PKMN>", 0x4B: "\n", 0x4C: "\n", 0x4E: "\n", 0x4F: "\n",
    0x51: "\n\n", 0x52: "<PLAYER>", 0x53: "<RIVAL>", 0x54: "POKé", 0x55: "\n",
    0x56: "……", 0x59: "<TARGET>", 0x5A: "<USER>", 0x5B: "PC", 0x5C: "TM",
    0x5D: "TRAINER", 0x5E: "ROCKET", 0x70: "‘", 0x71: "’", 0x72: "“", 0x73: "”",
    0x75: "…", 0x7F: " ", 0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";",
    0x9E: "[", 0x9F: "]", 0xBA: "é", 0xBB: "'d", 0xBC: "'l", 0xBD: "'s",
    0xBE: "'t", 0xBF: "'v", 0xE0: "'", 0xE1: "<PK>", 0xE2: "<MN>",
    0xE3: "-", 0xE4: "'r", 0xE5: "'m", 0xE6: "?", 0xE7: "!", 0xE8: ".",
    0xEC: "▷", 0xED: "▶", 0xEE: "▼", 0xEF: "♂", 0xF0: "¥", 0xF1: "×",
    0xF2: ".", 0xF3: "/", 0xF4: ",", 0xF5: "♀",
}
_CHARS.update({0x80 + index: chr(ord("A") + index) for index in range(26)})
_CHARS.update({0xA0 + index: chr(ord("a") + index) for index in range(26)})
_CHARS.update({0xF6 + index: str(index) for index in range(10)})


def decode_text(rom: RomReader, bank: int, address: int,
                _seen: frozenset[int] = frozenset()) -> dict[str, Any]:
    """Decode inline text or simple TX_FAR wrappers, never execute TX_START_ASM."""
    offset = rom.pointer(bank, address, context="text")
    if offset in _seen or len(_seen) >= 8:
        raise RomError("Cyclic or excessively nested text pointer")
    command = rom.byte(offset, "text command")
    if command == 0x17:  # TX_FAR: opcode, little-endian address, bank.
        wrapper = rom.read(offset, 5, "far text wrapper")
        if wrapper[4] != 0x50:
            raise RomError("Text wrapper has an unsupported continuation")
        nested = decode_text(rom, wrapper[3], int.from_bytes(wrapper[1:3], "little"),
                             _seen | {offset})
        return {**nested, "wrapper_rom_offset": offset}
    if command != 0:
        raise RomError(f"Unsupported text command 0x{command:02x}; assembly needs an adapter")
    cur = _Cursor(rom, offset, "inline text")
    cur.byte()  # TX_START
    result = []
    for _ in range(MAX_TEXT_BYTES):
        value = cur.byte()
        if value in (0x50, 0x57, 0x58):
            return {"text": "".join(result), "rom_offset": offset,
                    "terminator": value, "bytes_read": cur.offset - offset}
        if value not in _CHARS:
            raise RomError(f"Unsupported inline text byte 0x{value:02x}")
        result.append(_CHARS[value])
    raise RomError("Text did not terminate within the supported length")


def _texts(rom: RomReader, profile: RomProfile, bank: int, address: int) -> dict[str, Any]:
    table = rom.pointer(bank, address, 14, "Pallet text pointer table")
    targets = (("girl", 2, "PalletTownGirlText"),
               ("fisher", 3, "PalletTownFisherText"),
               ("lab_sign", 4, "PalletTownOaksLabSignText"),
               ("town_sign", 5, "PalletTownSignText"),
               ("player_house_sign", 6, "PalletTownPlayersHouseSignText"),
               ("rival_house_sign", 7, "PalletTownRivalsHouseSignText"))
    result = {}
    for name, text_id, symbol in targets:
        pointer = rom.word(table + 2 * (text_id - 1), "Pallet text pointer")
        result[name] = {**decode_text(rom, bank, pointer), "text_id": text_id,
                        "source_symbol": symbol}
    # Text ID 1 starts with assembly that chooses between two passages. These
    # two known data addresses bypass that code; the N64 event adapter chooses.
    for name, location, symbol in (
        ("oak_hey_wait", profile.oak_hey_wait, "_PalletTownOakHeyWaitDontGoOutText"),
        ("oak_unsafe", profile.oak_unsafe, "_PalletTownOakItsUnsafeText"),
    ):
        result[name] = {**decode_text(rom, *location), "text_id": 1,
                        "source_symbol": symbol, "adapter_selected": True}
    return result


def _movement(rom: RomReader, location: tuple[int, int], player: bool) -> dict[str, Any]:
    offset = rom.pointer(*location, context="Oak escort movement")
    cur = _Cursor(rom, offset, "Oak escort movement")
    directions = ({0x80: "down", 0x40: "up", 0x20: "left", 0x10: "right"}
                  if player else
                  {0x00: "down", 0x40: "up", 0x80: "left", 0xC0: "right", 0xE0: "face"})
    raw, steps = [], 0
    for _ in range(64):
        code = cur.byte()
        if code == 0xFF:
            # Simulated joypad entries are consumed backwards; NPC commands
            # run forwards. Return chronological runs in both cases.
            return {"rom_offset": offset, "runs": list(reversed(raw)) if player else raw,
                    "source_order": "reverse" if player else "forward"}
        count = cur.byte()
        if code not in directions or not 1 <= count <= 64:
            raise RomError("Unsupported escort movement opcode or run length")
        steps += count
        if steps > 256:
            raise RomError("Escort movement exceeds its bounded path budget")
        raw.append({"direction": directions[code], "count": count})
    raise RomError("Unterminated escort movement")


def parse_pallet(data: bytes, profile: RomProfile) -> dict[str, Any]:
    """Parse an explicitly chosen format profile (synthetic-fixture test seam).

    Production callers must call ``extract_pallet`` so unknown ROMs cannot be
    silently interpreted using these fixed addresses. No GB CPU code is run.
    """
    if len(data) != profile.size:
        raise RomError(f"Expected {profile.size} bytes for the chosen profile")
    rom = RomReader(data)
    bank, header_offset = _map_location(rom, profile, 0)
    cur = _Cursor(rom, header_offset, "Pallet map header")
    tileset_id, height_blocks, width_blocks = cur.read(3)
    if tileset_id != 0:
        raise RomError("Pallet Town must use the supported Overworld tileset")
    if (width_blocks, height_blocks) != (10, 9):
        raise RomError("Unexpected Pallet Town dimensions (expected 10 x 9 blocks)")
    width, height = width_blocks * 2, height_blocks * 2
    blocks_address, text_address, script_address = cur.word(), cur.word(), cur.word()
    mask = cur.byte()
    if mask & ~0xF:
        raise RomError("Invalid connection direction mask")
    connections = []
    for direction, bit in (("north", 8), ("south", 4), ("west", 2), ("east", 1)):
        if mask & bit:
            destination_map = cur.byte()
            source_pointer, buffer_pointer = cur.word(), cur.word()
            length, connected_width, y, x = cur.read(4)
            window_pointer = cur.word()
            destination_bank, dest_header = _map_location(rom, profile, destination_map)
            dimensions = rom.read(dest_header + 1, 2, "connected map dimensions")
            if connected_width != dimensions[1] or not (length and connected_width):
                raise RomError("Connection dimensions do not match the destination map")
            if length > (dimensions[1] if direction in ("north", "south") else dimensions[0]):
                raise RomError("Connection strip exceeds destination dimensions")
            if not (0xC000 <= buffer_pointer < 0xE000 and 0xC000 <= window_pointer < 0xE000):
                raise RomError("Connection contains an invalid GB map-buffer address")
            connections.append({"direction": direction, "destination_map": destination_map,
                                "source_blocks_rom_offset": rom.pointer(destination_bank, source_pointer,
                                                                          context="connection blocks"),
                                "strip_length": length, "destination_width_blocks": connected_width,
                                "y_alignment": _signed_byte(y), "x_alignment": _signed_byte(x),
                                "gb_buffer_pointer": buffer_pointer, "gb_window_pointer": window_pointer})
    object_address = cur.word()
    objects = _objects(rom, profile, bank, object_address, width, height)
    tileset_header = rom.read(profile.tilesets + tileset_id * 12, 12, "tileset header")
    tile_bank = tileset_header[0]
    block_address = int.from_bytes(tileset_header[1:3], "little")
    gfx_address = int.from_bytes(tileset_header[3:5], "little")
    collision_address = int.from_bytes(tileset_header[5:7], "little")
    block_offset = rom.pointer(tile_bank, block_address, profile.overworld_block_count * 16,
                               "Overworld blockset")
    collision_offset = rom.pointer(tile_bank, collision_address, context="collision whitelist")
    collision_cursor = _Cursor(rom, collision_offset, "collision whitelist")
    passable = set()
    for _ in range(97):
        tile = collision_cursor.byte()
        if tile == 0xFF:
            break
        if tile >= 96 or tile in passable:
            raise RomError("Invalid or duplicated collision-whitelist tile")
        passable.add(tile)
    else:
        raise RomError("Unterminated collision whitelist")
    block_map_offset = rom.pointer(bank, blocks_address, width_blocks * height_blocks, "map blocks")
    block_ids = rom.read(block_map_offset, width_blocks * height_blocks, "map blocks")
    if max((*block_ids, objects["border_block"])) >= profile.overworld_block_count:
        raise RomError("Map references a block outside the Overworld blockset")
    blocks = [list(block_ids[i:i + width_blocks]) for i in range(0, len(block_ids), width_blocks)]
    cells = []
    for y in range(height):
        row = []
        for x in range(width):
            block_id = blocks[y // 2][x // 2]
            block = rom.read(block_offset + block_id * 16, 16, "map block")
            at = (y % 2) * 8 + (x % 2) * 2
            tiles = [block[at], block[at + 1], block[at + 4], block[at + 5]]
            if max(tiles) >= 96:
                raise RomError("Block references a tile outside the Overworld tileset")
            row.append({"block_id": block_id, "tiles": tiles, "collision_tile": tiles[2],
                        "walkable": tiles[2] in passable})
        cells.append(row)
    digest = hashlib.sha1(data).hexdigest()
    return {
        "schema_version": 1,
        "source": {"game": profile.game, "title": profile.title, "size": len(data),
                   "sha1": digest, "sha256": hashlib.sha256(data).hexdigest(),
                   "verified_profile": digest == profile.sha1,
                   "reference": f"https://github.com/pret/pokered/tree/{REFERENCE_COMMIT}",
                   "symbols_reference": (f"https://github.com/pret/pokered/blob/{SYMBOL_REFERENCE_COMMIT}/"
                                         f"poke{profile.game}.sym"),
                   "symbols_blob": SYMBOL_BLOBS.get(profile.game)},
        "map": {"id": 0, "name": "PalletTown", "bank": bank, "rom_offset": header_offset,
                "width_blocks": width_blocks, "height_blocks": height_blocks,
                "width": width, "height": height, "tileset_id": tileset_id,
                "blocks": blocks, "blocks_rom_offset": block_map_offset, "cells": cells,
                "destination_warp_indexing": "zero-based", "connections": connections,
                **objects,
                "tileset": {"bank": tile_bank, "block_rom_offset": block_offset,
                            "gfx_rom_offset": rom.pointer(tile_bank, gfx_address, context="tileset graphics"),
                            "collision_rom_offset": collision_offset, "collision_tiles": sorted(passable),
                            "counter_tiles": list(tileset_header[7:10]), "grass_tile": tileset_header[10],
                            "animations": tileset_header[11]},
                "script": {"adapter": "gen1_pallet_oak_v1",
                           "rom_offset": rom.pointer(bank, script_address, context="map script"),
                           "bank": bank, "address": script_address,
                           "trigger_y": 1,
                           "movements": {"oak_to_lab": _movement(rom, profile.oak_movement, False),
                                         "player_to_lab": _movement(rom, profile.player_movement, True)},
                           "coverage": {"oak_interception": "known_behaviour_adapter",
                                        "arbitrary_gb_assembly": "unsupported",
                                        "post_pokedex_and_daisy": "unsupported"}}},
        "texts": _texts(rom, profile, bank, text_address),
    }


def extract_pallet(rom: bytes) -> dict[str, Any]:
    """Strict public entry point: recognize a complete ROM, then extract data."""
    profile = identify_rom(rom)
    world = parse_pallet(rom, profile)
    # The verified cartridge contains the original dialogue for the entire
    # opening sequence, not just Pallet's signs. No copyrighted text is stored
    # in the converter's source tree.
    from opening_rom import extract_opening_texts
    world["opening_texts"] = extract_opening_texts(rom, world["texts"])
    return world
