"""Test source-backed speech extraction without bundling a Pokémon cartridge."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import opening_rom


def offset(bank, address):
    return bank * 0x4000 + address - 0x4000 if address >= 0x4000 else address


class OpeningDialogueTests(unittest.TestCase):
    def sample(self):
        data = bytearray(1024 * 1024)
        for bank, address in opening_rom.SOURCE.values():
            data[offset(bank, address):offset(bank,address)+3] = b"\x00\x80\x50"
        pallet = {value: {"text": "PALLET"} for value in opening_rom.PALLET_TEXT.values()}
        return data, pallet

    def test_every_reference_reads_its_own_user_rom_bytes(self):
        data, pallet = self.sample()
        a = opening_rom.extract_opening_texts(data, pallet)
        bank, address = opening_rom.SOURCE["rival_challenge"]
        data[offset(bank,address) + 1] = 0x81
        b = opening_rom.extract_opening_texts(data, pallet)
        self.assertEqual(a["talks"]["TALK_RIVAL_CHALLENGE"], "A")
        self.assertEqual(b["talks"]["TALK_RIVAL_CHALLENGE"], "B")
        self.assertEqual(a["talks"]["TALK_GIRL"], "PALLET")
        self.assertEqual(len(a["sources"]), len(opening_rom.SOURCE))

    def test_dialogue_branches_are_separate_and_complete(self):
        data, pallet = self.sample()
        a = opening_rom.extract_opening_texts(data, pallet)
        self.assertEqual(a["talks"]["TALK_LAB_WELCOME"], "A\fA\fA\fA")
        self.assertEqual(set(a["ball"]), {"bulbasaur","charmander","squirtle"})
        self.assertEqual(set(a["result"]), {"won","lost"})

    def test_c_emitter_contains_no_authored_dialogue_fallback(self):
        data, pallet = self.sample()
        a = opening_rom.extract_opening_texts(data, pallet)
        source = opening_rom.emit_opening_c(a, lambda text: '"' + text.replace("\f", "\\f") + '"')
        self.assertIn("gPokeOpeningTextEnabled = 1", source)
        self.assertIn("[TALK_RIVAL_CHALLENGE]", source)
        self.assertNotIn("Wait, RED! Battle me", source)


if __name__ == "__main__":
    unittest.main()
