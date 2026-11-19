"""Binary-format tests use invented bytes, never an original ROM or text dump."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import gen1_rom


def offset(bank: int, address: int) -> int:
    return address if address < 0x4000 else bank * 0x4000 + address - 0x4000


def word(value: int) -> bytes:
    return value.to_bytes(2, "little")


def checksums(data: bytearray) -> None:
    data[0x14D] = (-sum(data[0x134:0x14D]) - 25) & 0xFF
    data[0x14E:0x150] = ((sum(data[:0x14E]) + sum(data[0x150:])) & 0xFFFF).to_bytes(2, "big")


def synthetic_rom(*, mixed_objects: bool = False) -> bytearray:
    """Construct a deliberately fictional map with the documented binary layout."""
    profile = gen1_rom.PROFILES[0]
    data = bytearray(profile.size)

    def write(bank: int, address: int, values: bytes) -> None:
        begin = offset(bank, address)
        data[begin:begin + len(values)] = values

    # Minimal valid header for unit testing the validator. This synthetic file
    # has no Nintendo logo, executable, game content or known retail checksum.
    data[0x134:0x13F] = b"POKEMON RED"
    data[0x147:0x14A] = b"\x13\x05\x03"
    data[0x14A] = 1
    data[profile.map_banks] = 6
    data[profile.map_pointers:profile.map_pointers + 2] = word(0x42A1)
    for map_id in (12, 33):
        data[profile.map_banks + map_id] = 7
        data[profile.map_pointers + map_id * 2:profile.map_pointers + map_id * 2 + 2] = word(0x4000)
    write(7, 0x4000, bytes((0, 18, 10)) + word(0x4100) + word(0x5000) + word(0x5100) + b"\0")
    # Two north/south connections prove source pointers use the DESTINATION's
    # bank. This bank's same addresses intentionally contain unrelated bytes.
    connection = (bytes((12,)) + word(0x4196) + word(0xC700) + bytes((10, 10, 35, 0)) + word(0xC800))
    connection += (bytes((33,)) + word(0x4100) + word(0xC780) + bytes((10, 10, 0, 0xFE)) + word(0xC900))
    header = bytes((0, 9, 10)) + word(0x42FD) + word(0x4F88) + word(0x4E5B) + b"\x0c"
    write(6, 0x42A1, header + connection + word(0x42C3))
    # Two test doors, four sign IDs and three objects. Positions are invented.
    objects = bytearray((2, 2, 4, 3, 0, 37, 6, 15, 1, 0xFF, 4))
    for index in range(4):
        objects.extend((8, 5 + index, 4 + index))
    objects.append(3)
    objects.extend((9, 6, 5, 0xFF, 0xFF, 1))
    objects.extend((10, 7, 6, 0xFE, 0, 0x42 if mixed_objects else 2))
    if mixed_objects:
        objects.extend((201, 9))
    objects.extend((11, 9, 8, 0xFE, 0, 0x83 if mixed_objects else 3))
    if mixed_objects:
        objects.append(23)
    for x, y in ((3, 4), (15, 6)):
        objects.extend(word(profile.overworld_ram + 7 + 10 + 16 * (y // 2) + x // 2))
        objects.extend((y, x))
    # Give the variable-length fixture room without overlapping block data.
    write(6, 0x6000, objects)
    write(6, 0x42C1, word(0x6000))
    write(6, 0x42FD, bytes((1,)) * 90)
    write(0x19, 0x45F0, bytes(range(16, 32)))
    data[profile.tilesets:profile.tilesets + 12] = (bytes((0x19,)) + word(0x45E0) + word(0x4000)
                                                  + word(0x1735) + bytes((255, 255, 255, 20, 2)))
    write(0, 0x1735, bytes((20, 30, 0xFF)))
    data[profile.toggle_pointers:profile.toggle_pointers + 2] = word(0x4AEA)
    write(3, 0x4AEA, bytes((0, 1, 0x11, 1)))  # next map terminates Pallet's list
    write(6, 0x4F88, word(0x4F96))
    write(6, 0x4F96, b"\x08")  # Oak's first pointer is ASM and must never run.
    for text_id in range(2, 8):
        wrapper_address = 0x5000 + text_id * 8
        string_address = 0x4500 + text_id * 16
        write(6, 0x4F88 + (text_id - 1) * 2, word(wrapper_address))
        write(6, wrapper_address, b"\x17" + word(string_address) + bytes((0x29, 0x50)))
        # A different single letter plus dynamic player/rival names.
        write(0x29, string_address, bytes((0, 0x80 + text_id, 0x52, 0x4F, 0x53, 0x57)))
    write(*profile.oak_hey_wait, bytes((0, 0x80, 0x50, 0x50)))
    write(*profile.oak_unsafe, bytes((0, 0x81, 0x51, 0x82, 0x57)))
    write(*profile.oak_movement, bytes((0, 3, 0x80, 2, 0xE0, 1, 0xFF)))
    write(*profile.player_movement, bytes((0x40, 2, 0x80, 3, 0xFF)))
    checksums(data)
    return data


class RomIdentificationTests(unittest.TestCase):
    def test_unknown_full_size_rom_is_rejected_even_with_valid_header(self) -> None:
        data = bytes(synthetic_rom())
        gen1_rom.validate_header(data, gen1_rom.PROFILES[0])
        with self.assertRaisesRegex(gen1_rom.RomError, "Unsupported ROM SHA-1"):
            gen1_rom.extract_pallet(data)

    def test_truncated_or_extended_rom_is_rejected_before_parsing(self) -> None:
        for data in (b"", b"test", bytes(gen1_rom.ROM_SIZE - 1), bytes(gen1_rom.ROM_SIZE + 1)):
            with self.subTest(length=len(data)), self.assertRaises(gen1_rom.RomError):
                gen1_rom.extract_pallet(data)

    def test_strict_entry_point_uses_identification_before_parser(self) -> None:
        data = bytes(synthetic_rom())
        # Inject a synthetic profile into the test only. There is no production
        # option, environment variable or CLI switch for disabling the hashes.
        profile = replace(gen1_rom.PROFILES[0], sha1=hashlib.sha1(data).hexdigest())
        with patch.object(gen1_rom, "PROFILES", (profile,)):
            scene = gen1_rom.extract_pallet(data)
        self.assertTrue(scene["source"]["verified_profile"])
        self.assertEqual(scene["source"]["sha256"], hashlib.sha256(data).hexdigest())

    def test_blue_profile_keeps_version_metadata_and_the_shared_format(self) -> None:
        data = synthetic_rom()
        data[0x134:0x144] = b"POKEMON BLUE".ljust(16, b"\0")
        checksums(data)
        profile = replace(gen1_rom.PROFILES[1], sha1=hashlib.sha1(data).hexdigest())
        with patch.object(gen1_rom, "PROFILES", (profile,)):
            scene = gen1_rom.extract_pallet(bytes(data))
        self.assertEqual(scene["source"]["game"], "blue")
        self.assertTrue(scene["source"]["symbols_reference"].endswith("/pokeblue.sym"))
        self.assertEqual(scene["map"]["cells"][0][0]["collision_tile"], 20)

    def test_header_checksum_and_global_checksum_are_independent(self) -> None:
        data = synthetic_rom()
        data[0x14D] ^= 1
        with self.assertRaisesRegex(gen1_rom.RomError, "header checksum"):
            gen1_rom.validate_header(bytes(data), gen1_rom.PROFILES[0])
        data = synthetic_rom()
        data[-1] ^= 1
        with self.assertRaisesRegex(gen1_rom.RomError, "global checksum"):
            gen1_rom.validate_header(bytes(data), gen1_rom.PROFILES[0])

    def test_wrong_cartridge_fields_or_revision_are_rejected(self) -> None:
        for position in (0x134, 0x147, 0x148, 0x149, 0x14A, 0x14C):
            data = synthetic_rom()
            data[position] ^= 1
            checksums(data)
            with self.subTest(position=position), self.assertRaises(gen1_rom.RomError):
                gen1_rom.validate_header(bytes(data), gen1_rom.PROFILES[0])


class PalletParsingTests(unittest.TestCase):
    def parse(self, data: bytes | bytearray | None = None) -> dict:
        return gen1_rom.parse_pallet(bytes(synthetic_rom() if data is None else data), gen1_rom.PROFILES[0])

    def test_tile_quadrants_and_bottom_left_collision(self) -> None:
        scene = self.parse()
        town = scene["map"]
        self.assertEqual((town["width"], town["height"]), (20, 18))
        self.assertEqual(town["cells"][0][0]["tiles"], [16, 17, 20, 21])
        self.assertEqual(town["cells"][0][1]["tiles"], [18, 19, 22, 23])
        self.assertEqual(town["cells"][1][0]["tiles"], [24, 25, 28, 29])
        self.assertEqual(town["cells"][1][1]["tiles"], [26, 27, 30, 31])
        self.assertTrue(town["cells"][0][0]["walkable"])
        self.assertFalse(town["cells"][0][1]["walkable"])
        self.assertFalse(town["cells"][1][0]["walkable"])
        self.assertTrue(town["cells"][1][1]["walkable"])
        self.assertEqual(town["tileset"]["collision_rom_offset"], 0x1735)
        self.assertFalse(scene["source"]["verified_profile"])

    def test_warps_signs_and_object_offsets_are_preserved(self) -> None:
        town = self.parse()["map"]
        self.assertEqual(town["destination_warp_indexing"], "zero-based")
        self.assertEqual((town["warps"][0]["x"], town["warps"][0]["y"]), (3, 4))
        self.assertEqual(town["warps"][0]["destination_map"], 37)
        self.assertEqual(town["warps"][0]["destination_warp"], 0)
        self.assertTrue(town["warps"][1]["destination_uses_last_map"])
        self.assertEqual((town["objects"][0]["x"], town["objects"][0]["y"]), (1, 2))
        self.assertFalse(town["objects"][0]["visible_on_start"])
        self.assertTrue(town["objects"][1]["visible_on_start"])
        self.assertEqual(town["signs"][0], {"x": 5, "y": 8, "text_id": 4})
        self.assertEqual((town["spawn_warps"][1]["x"], town["spawn_warps"][1]["y"]), (15, 6))

    def test_variable_length_trainer_and_item_records_do_not_shift_spawns(self) -> None:
        town = self.parse(synthetic_rom(mixed_objects=True))["map"]
        trainer, item = town["objects"][1:]
        self.assertEqual((trainer["kind"], trainer["trainer_class"], trainer["trainer_number"]),
                         ("trainer", 201, 9))
        self.assertEqual((item["kind"], item["item_id"]), ("item", 23))
        self.assertEqual(town["spawn_warps"][0]["x"], 3)

    def test_connection_uses_destination_bank_and_signed_alignment(self) -> None:
        north, south = self.parse()["map"]["connections"]
        self.assertEqual(north["direction"], "north")
        self.assertEqual(north["source_blocks_rom_offset"], offset(7, 0x4196))
        self.assertEqual(south["x_alignment"], -2)

    def test_dialogue_is_from_bytes_and_names_remain_dynamic(self) -> None:
        texts = self.parse()["texts"]
        self.assertEqual(texts["girl"]["text"], "C<PLAYER>\n<RIVAL>")
        self.assertEqual(texts["oak_hey_wait"]["text"], "A")
        self.assertEqual(texts["oak_unsafe"]["text"], "B\n\nC")
        self.assertEqual(texts["girl"]["rom_offset"], offset(0x29, 0x4520))
        self.assertEqual(texts["girl"]["wrapper_rom_offset"], offset(6, 0x5010))

    def test_escort_paths_are_chronological_for_each_encoding(self) -> None:
        script = self.parse()["map"]["script"]
        self.assertEqual(script["movements"]["oak_to_lab"]["runs"],
                         [{"direction": "down", "count": 3}, {"direction": "left", "count": 2},
                          {"direction": "face", "count": 1}])
        self.assertEqual(script["movements"]["player_to_lab"]["runs"],
                         [{"direction": "down", "count": 3}, {"direction": "up", "count": 2}])
        self.assertEqual(script["coverage"]["arbitrary_gb_assembly"], "unsupported")

    def test_result_is_json_serializable_and_deterministic(self) -> None:
        data = bytes(synthetic_rom())
        self.assertEqual(json.dumps(self.parse(data), sort_keys=True), json.dumps(self.parse(data), sort_keys=True))

    def test_bad_map_pointers_counts_and_tile_ids_fail_closed(self) -> None:
        mutations = {
            "bank": (gen1_rom.PROFILES[0].map_banks, bytes((64,))),
            "header-pointer": (gen1_rom.PROFILES[0].map_pointers, word(0x8000)),
            "dimensions": (offset(6, 0x42A2), bytes((0,))),
            "connections-mask": (offset(6, 0x42AA), bytes((0x10,))),
            "warp-count": (offset(6, 0x6001), bytes((33,))),
            "block-id": (offset(6, 0x42FD), bytes((128,))),
            "tile-id": (offset(0x19, 0x45F0), bytes((96,))),
            "collision-id": (0x1735, bytes((96,))),
            "npc-x": (offset(6, 0x6000) + 26, bytes((0,))),
            "visibility": (offset(3, 0x4AEC), bytes((1,))),
            "text-asm": (offset(0x29, 0x4520), bytes((8,))),
            "movement-opcode": (offset(6, 0x64DC), bytes((0xFE,))),
        }
        for name, (location, values) in mutations.items():
            data = synthetic_rom()
            data[location:location + len(values)] = values
            with self.subTest(name=name), self.assertRaises(gen1_rom.RomError):
                self.parse(data)

    def test_corrupted_warp_spawn_is_rejected(self) -> None:
        data = synthetic_rom()
        # 2-byte prefix + 2 warps + count + 4 signs + count + 3 objects.
        spawn_offset = offset(6, 0x6000) + 2 + 8 + 1 + 12 + 1 + 18
        data[spawn_offset] ^= 1
        with self.assertRaisesRegex(gen1_rom.RomError, "Warp spawn displacement"):
            self.parse(data)


class PointerAndTextTests(unittest.TestCase):
    def test_rom0_pointer_ignores_selected_bank(self) -> None:
        rom = gen1_rom.RomReader(bytes(gen1_rom.ROM_SIZE))
        self.assertEqual(rom.pointer(0x19, 0x1735), 0x1735)
        self.assertEqual(rom.pointer(0x19, 0x45E0), 0x645E0)

    def test_bank_crossing_and_non_rom_pointers_are_rejected(self) -> None:
        rom = gen1_rom.RomReader(bytes(gen1_rom.ROM_SIZE))
        for bank, address, length in ((0, 0x4000, 1), (1, 0x8000, 1), (64, 0x4000, 1),
                                      (1, 0x7FFF, 2), (0, 0x3FFF, 2), (1, -1, 1)):
            with self.subTest(bank=bank, address=address), self.assertRaises(gen1_rom.RomError):
                rom.pointer(bank, address, length)

    def test_cyclic_far_text_is_rejected(self) -> None:
        data = bytearray(0x8000)
        data[0x4100:0x4105] = b"\x17\x00\x41\x01\x50"
        with self.assertRaisesRegex(gen1_rom.RomError, "Cyclic"):
            gen1_rom.decode_text(gen1_rom.RomReader(bytes(data)), 1, 0x4100)

    def test_text_length_limit_and_bank_boundary_are_enforced(self) -> None:
        data = bytearray(b"\x80" * 0x8000)
        for address in (0x4000, 0x7FF0):
            data[address] = 0
            with self.subTest(address=address), self.assertRaises(gen1_rom.RomError):
                gen1_rom.decode_text(gen1_rom.RomReader(bytes(data)), 1, address)

    def test_asm_after_far_wrapper_is_never_silently_executed(self) -> None:
        data = bytearray(0x8000)
        data[0x4100:0x4105] = b"\x17\x00\x42\x01\x08"
        data[0x4200:0x4203] = b"\x00\x80\x57"
        with self.assertRaisesRegex(gen1_rom.RomError, "unsupported continuation"):
            gen1_rom.decode_text(gen1_rom.RomReader(bytes(data)), 1, 0x4100)


if __name__ == "__main__":
    unittest.main()
