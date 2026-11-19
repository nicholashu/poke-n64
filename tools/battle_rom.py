"""Import first-playable-area Pokémon stats, moves and initial attacks.

Stat/move offsets are from the pinned pret/pokered symbol reference. The
checked-in tool contains metadata and mappings, never source-ROM records.
The current N64 battle interpreter is intentionally separate and not a
decompilation of the original Gen 1 battle machine.
"""
from __future__ import annotations

from gen1_rom import RomReader, RomError

BASE_START = (0x0E, 0x43DE)  # BaseStats, 28 bytes per Pokédex entry
BASE_SIZE = 28
MOVE_START = (0x0E, 0x4000)  # Moves, 6 bytes per move (ID 1..165)
MOVE_SIZE = 6

# Pokédex numbers, not the unrelated Gen 1 internal species indices.
SPECIES = (
    ("POKE_BULBASAUR", "Bulbasaur", 1),
    ("POKE_CHARMANDER", "Charmander", 4),
    ("POKE_SQUIRTLE", "Squirtle", 7),
    ("POKE_PIDGEY", "Pidgey", 16),
    ("POKE_RATTATA", "Rattata", 19),
)
# Move ID constants are kept in our compact N64 interpreter; cartridge ID
# values are official Red/Blue move indices.
MOVES = (
    ("MOVE_TACKLE", "Tackle", 0x21),
    ("MOVE_GROWL", "Growl", 0x2D),
    ("MOVE_VINE_WHIP", "Vine Whip", 0x16),
    ("MOVE_SCRATCH", "Scratch", 0x0A),
    ("MOVE_EMBER", "Ember", 0x34),
    ("MOVE_TAIL_WHIP", "Tail Whip", 0x27),
    ("MOVE_WATER_GUN", "Water Gun", 0x37),
    ("MOVE_GUST", "Gust", 0x10),
    ("MOVE_STRUGGLE", "Struggle", 0xA5),
)
# Gen 1 type IDs from pret/pokered's constants/type_constants.asm.
TYPES = {0x00:"TYPE_NORMAL",0x02:"TYPE_FLYING",0x03:"TYPE_POISON",
         0x14:"TYPE_FIRE",0x15:"TYPE_WATER",0x16:"TYPE_GRASS"}
MOVE_ID_TO_N64 = {n:"MOVE_"+name.removeprefix("MOVE_") for name,_,n in MOVES}


def extract_battle(rom_data: bytes) -> dict:
    rom = RomReader(rom_data)
    species = []
    for constant, name, dex in SPECIES:
        offset = rom.pointer(BASE_START[0], BASE_START[1] + (dex-1)*BASE_SIZE,
                             BASE_SIZE, f"{name} base stats")
        record = rom.read(offset, BASE_SIZE, f"{name} base stats")
        if record[0] != dex:
            raise RomError(f"{name} Pokédex number mismatch in source ROM")
        hp,atk,defense,speed,special = record[1:6]
        if min(hp,atk,defense,speed,special) == 0:
            raise RomError(f"{name} has impossible zero base stat")
        if record[6] not in TYPES or record[7] not in TYPES:
            raise RomError(f"{name} type requires a new native type adapter")
        first_moves = list(record[15:19])
        if any(move and move not in MOVE_ID_TO_N64 for move in first_moves):
            raise RomError(f"{name} initial moves require new N64 effect adapters")
        species.append({
            "constant":constant,"name":name,"dex":dex,
            "stats":[hp,atk,defense,speed,special],
            "type1":TYPES[record[6]],"type2":TYPES[record[7]],
            "catch_rate":record[8],"base_xp":record[9],
            "initial_moves":[MOVE_ID_TO_N64[m] if m else "MOVE_NONE" for m in first_moves],
            "rom_offset":offset,
        })
    moves = []
    for constant,name,gb_id in MOVES:
        offset=rom.pointer(MOVE_START[0], MOVE_START[1] + (gb_id-1)*MOVE_SIZE,
                           MOVE_SIZE, f"{name} move data")
        record=rom.read(offset,MOVE_SIZE, f"{name} move data")
        if record[0] != gb_id:
            raise RomError(f"{name} ROM move ID mismatch")
        if record[3] not in TYPES:
            raise RomError(f"{name} type is not implemented by N64 battle interpreter")
        if record[5] > 40:
            raise RomError(f"{name} PP out of bounds")
        moves.append({
            "constant":constant,"name":name,"gb_id":gb_id,
            "effect":record[1],"power":record[2],
            "type":TYPES[record[3]],
            "accuracy":(record[4]*100+127)//255,"pp":record[5],
            "rom_offset":offset,
        })
    return {"species":species,"moves":moves,
            "provenance":"pret/pokered BaseStats and Moves symbols at c88672bb"}


def apply_to_core(core_source: str, battle: dict) -> str:
    """Use the cartridge's numbers, not the authored hardcoded C data tables."""
    def splice(start_marker: str, end_marker: str, replacement: str):
        nonlocal core_source
        start=core_source.find(start_marker)
        stop=core_source.find(end_marker,start+len(start_marker))
        if start<0 or stop<0:
            raise ValueError(f"Native core data table missing: {start_marker}")
        core_source=core_source[:start]+replacement+core_source[stop:]
    species=['/* Generated from the supplied Red/Blue ROM. */',
             'static const PokeSpeciesInfo species_table[] = {']
    for e in battle["species"]:
        species.append('    {%s, "%s", %s, %s, %s, %s},' % (
            e["constant"],e["name"],e["type1"],e["type2"],
            ','.join(str(x) for x in e["stats"]), '' ))
    # Emit numeric fields explicitly to make the initializer auditable.
    species=['/* Generated from the supplied Red/Blue ROM. */',
             'static const PokeSpeciesInfo species_table[] = {']
    for e in battle["species"]:
        v=e["stats"]+[e["catch_rate"],e["base_xp"]]
        species.append('    { %s, "%s", %s, %s, %s },' % (
            e["constant"], e["name"],e["type1"],e["type2"],
            ", ".join(map(str,v))))
    species.append('};\n\n')
    splice('static const PokeSpeciesInfo species_table[] = {',
           'static const PokeMove move_table', "\n".join(species))
    moves=['static const PokeMove move_table[MOVE_COUNT] = {',
           '    { MOVE_NONE, "--", TYPE_NORMAL, 0, 0, 0 },']
    for e in battle["moves"]:
        moves.append('    { %s, "%s", %s, %s, %s, %s },' % (
            e["constant"],e["name"],e["type"],e["power"],
            e["accuracy"],e["pp"]))
    moves.append('};\n\n')
    splice('static const PokeMove move_table[MOVE_COUNT] = {',
           'const PokeSpeciesInfo *poke_species', "\n".join(moves))
    initial=['static const uint8_t sCartridgeInitialMoves[][POKE_MOVE_SLOTS] = {']
    for e in battle["species"]:
        initial.append('    { %s },' % ", ".join(e["initial_moves"]))
    initial += ['};',
        'static const uint8_t sCartridgeInitialSpecies[] = {',
        '    '+', '.join(e["constant"] for e in battle["species"]),
        '};',
        'static void learn_moves(PokeMon *m) {',
        '    /* Later level-up moves still require the GB evolution/learnset adapter. */',
        '    (void)m;',
        '}',
        '\n']
    splice('static void learn_moves(PokeMon *m) {',
           'void poke_make_mon(PokeMon *m,uint8_t species,uint8_t level) {',
           "\n".join(initial))
    before='''    give_move(m,0,species==POKE_CHARMANDER ? MOVE_SCRATCH :
                    species==POKE_PIDGEY ? MOVE_GUST : MOVE_TACKLE);
    give_move(m,1,(species==POKE_SQUIRTLE || species==POKE_RATTATA) ? MOVE_TAIL_WHIP : MOVE_GROWL);
    learn_moves(m);'''
    after='''    {
        unsigned i,j;
        for (i=0;i<sizeof(sCartridgeInitialSpecies)/sizeof(sCartridgeInitialSpecies[0]);++i)
            if (species==sCartridgeInitialSpecies[i]) {
                for (j=0;j<POKE_MOVE_SLOTS;++j)
                    if (sCartridgeInitialMoves[i][j] != MOVE_NONE)
                        give_move(m,j,sCartridgeInitialMoves[i][j]);
                break;
            }
    }
    learn_moves(m);'''
    if core_source.count(before)!=1: raise ValueError("Native initial attack pattern changed")
    core_source=core_source.replace(before,after)
    return core_source
