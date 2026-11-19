"""Synthetic ROM tables verify the battle data comes from source bytes."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools"))
import battle_rom
from gen1_rom import RomError


def fixture():
    data=bytearray(1024*1024)
    def put(bank,address,record):
        off=bank*0x4000+address-0x4000
        data[off:off+len(record)]=record
    for _,_,dex in battle_rom.SPECIES:
        record=bytearray(28)
        record[0]=dex
        record[1:6]=bytes([40+dex,45,46,47,48])
        record[6]=0
        record[7]=0
        record[8:10]=b"\x5a\x40"
        record[15:19]=b"\x21\x2d\0\0"
        put(0x0e,battle_rom.BASE_START[1]+(dex-1)*28,record)
    for _,_,move_id in battle_rom.MOVES:
        record=bytes([move_id,0,35,0,242,35])
        put(0x0e,battle_rom.MOVE_START[1]+(move_id-1)*6,record)
    return data


class BattleSourceTests(unittest.TestCase):
    def test_stats_move_effects_and_start_moves_are_read_from_rom(self):
        data=fixture()
        original=battle_rom.extract_battle(bytes(data))
        self.assertEqual(original["species"][0]["stats"][0],41)
        self.assertEqual(original["species"][0]["initial_moves"][0],"MOVE_TACKLE")
        addr=0x0e*0x4000+(battle_rom.BASE_START[1]-0x4000)+1
        data[addr]=99
        updated=battle_rom.extract_battle(bytes(data))
        self.assertEqual(updated["species"][0]["stats"][0],99)
        self.assertNotEqual(original["species"][0]["stats"],updated["species"][0]["stats"])

    def test_wrong_species_id_does_not_silently_import(self):
        data=fixture()
        loc=0x0e*0x4000+(battle_rom.BASE_START[1]-0x4000)
        data[loc]=2
        with self.assertRaisesRegex(RomError,"Pokédex number"):
            battle_rom.extract_battle(bytes(data))

    def test_generated_native_core_is_compilable_and_source_driven(self):
        imported=battle_rom.extract_battle(bytes(fixture()))
        transformed=battle_rom.apply_to_core((ROOT/"src/core.c").read_text(),imported)
        self.assertIn("Generated from the supplied Red/Blue ROM",transformed)
        self.assertIn("POKE_BULBASAUR",transformed)
        self.assertNotIn("species==POKE_CHARMANDER ? MOVE_SCRATCH",transformed)
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/"core.c"
            target.write_text(transformed)
            subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",
                            "-pedantic","-I",str(ROOT/"include"),
                            "-c",str(target),"-o",str(Path(tmp)/"core.o")],
                           capture_output=True,text=True,check=True)


if __name__=="__main__":
    unittest.main()
