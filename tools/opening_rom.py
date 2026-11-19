"""Extract opening-area dialogue from a user-supplied Pokémon Red/Blue ROM.

Only symbol coordinates and scene-to-dialogue bindings are distributed.
The original dialogue is decoded from the user's verified ROM at build time.
Addresses refer to pret/pokered symbols at c88672bb; Red and Blue agree.
"""
from __future__ import annotations

from gen1_rom import RomReader, decode_text

# (bank, banked CPU address); all entries are source symbols, not dialogue.
SOURCE = {
    "oak_hey": (0x29, 0x4245),
    "oak_unsafe": (0x29, 0x4264),
    "mom": (0x25, 0x4b07),
    "mom_rest": (0x25, 0x4b6d),
    "mom_healed": (0x25, 0x4b94),
    "tv": (0x25, 0x4bd7),
    "tv_wrong_side": (0x25, 0x4c29),
    "daisy_before_dex": (0x25, 0x4c3c),
    "daisy_walking": (0x25, 0x4cfd),
    "town_map": (0x25, 0x4d3b),
    "rival_no_oak": (0x25, 0x4d5b),
    "rival_choose_first": (0x25, 0x4d79),
    "rival_stronger": (0x25, 0x4dbd),
    "balls": (0x25, 0x4ddf),
    "charmander": (0x25, 0x4e06),
    "squirtle": (0x25, 0x4e2f),
    "bulbasaur": (0x25, 0x4e57),
    "last_mon": (0x25, 0x4eb6),
    "oak_which": (0x25, 0x4ed2),
    "oak_fight": (0x25, 0x4ef8),
    "oak_raise": (0x25, 0x4f36),
    "girl_lab": (0x25, 0x526b),
    "rival_impatient": (0x25, 0x52bb),
    "oak_choose": (0x25, 0x52df),
    "rival_what_about": (0x25, 0x53dc),
    "oak_patient": (0x25, 0x53fc),
    "oak_dont_leave": (0x25, 0x5427),
    "rival_take_one": (0x25, 0x5444),
    "rival_challenge": (0x25, 0x5477),
    "rival_lost": (0x25, 0x54b6),
    "rival_won": (0x25, 0x54e4),
    "rival_goodbye": (0x25, 0x5502),
    "scientist": (0x25, 0x57eb),
}

# Real event branches in pret/pokered's PalletTown/OaksLab/house scripts.
# The N64 runtime still implements those state transitions; this mapping
# chooses the original text for the corresponding scripted presentation.
EVENT_TEXT = {
    "TALK_OAK_WARNING": ("oak_hey", "oak_unsafe"),
    "TALK_LAB_WELCOME": ("rival_impatient", "oak_choose",
                         "rival_what_about", "oak_patient"),
    "TALK_CHOSEN": ("rival_take_one",),
    "TALK_RIVAL_CHALLENGE": ("rival_challenge",),
    "TALK_MOM": ("mom",),
    "TALK_HEALED": ("mom_rest", "mom_healed"),
    "TALK_TV": ("tv",),
    "TALK_DAISY": ("daisy_before_dex",),
    "TALK_OAK_AWAY": ("oak_dont_leave",),
    "TALK_PICK_FIRST": ("oak_which",),
    "TALK_LAB_AIDE": ("scientist",),
    "TALK_BLUE": ("rival_no_oak",),
    "TALK_OAK_DONE": ("oak_raise",),
}

PALLET_TEXT = {
    "TALK_GIRL": "girl",
    "TALK_FISHER": "fisher",
    "TALK_RED_SIGN": "player_house_sign",
    "TALK_BLUE_SIGN": "rival_house_sign",
    "TALK_TOWN_SIGN": "town_sign",
    "TALK_LAB_SIGN": "lab_sign",
}


def extract_opening_texts(rom_bytes: bytes, pallet_texts: dict) -> dict:
    """Parse every referenced passage from the supplied ROM, never from ASM."""
    rom = RomReader(rom_bytes)
    decoded = {name: decode_text(rom, *source) for name, source in SOURCE.items()}
    def sequence(keys):
        # Form-feed is a page boundary between separate Game Boy speeches.
        return "\f".join(decoded[key]["text"] for key in keys)
    talks = {key: sequence(parts) for key, parts in EVENT_TEXT.items()}
    for talk, source_key in PALLET_TEXT.items():
        talks[talk] = pallet_texts[source_key]["text"]
    # Keep choice and battle-result branches distinct: choosing a different
    # starter must actually select a different ROM passage.
    return {
        "talks": talks,
        "ball": {
            "bulbasaur": sequence(("bulbasaur",)),
            "charmander": sequence(("charmander",)),
            "squirtle": sequence(("squirtle",)),
        },
        "result": {
            "won": sequence(("rival_lost", "rival_goodbye")),
            "lost": sequence(("rival_won", "rival_goodbye")),
        },
        "sources": {
            name: {"bank": SOURCE[name][0], "address": SOURCE[name][1],
                   "rom_offset": value["rom_offset"]}
            for name, value in decoded.items()
        },
        "unsupported": [
            "PC item and empty-PC interactions", "bedroom game-console",
            "generic bookshelf messages", "later story events",
            "dynamic GB text_asm functions", "battle engine narration",
        ],
    }


def emit_opening_c(opening: dict, encode) -> str:
    """Generate N64-resident text tables; use NULL for unsupported interactions."""
    lines = [
        '/* Private dialogue decoded from a user-provided Red/Blue ROM. */',
        '#include "poke_intro.h"',
        'const unsigned gPokeOpeningTextEnabled = 1;',
        'const char* const gPokeOpeningTalks[TALK_PC_FULL + 1] = {',
    ]
    for talk, text in sorted(opening["talks"].items()):
        lines.append(f'    [{talk}] = {encode(text)},')
    lines.extend(['};', 'const char* const gPokeOpeningStarters[3] = {',
                  f'    {encode(opening["ball"]["bulbasaur"])},',
                  f'    {encode(opening["ball"]["charmander"])},',
                  f'    {encode(opening["ball"]["squirtle"])},',
                  '};', 'const char* const gPokeOpeningResults[2] = {',
                  f'    {encode(opening["result"]["won"])},',
                  f'    {encode(opening["result"]["lost"])},',
                  '};', ''])
    return "\n".join(lines)
