# Native N64 integration

This directory implements the first native presentation of the shared C game in
HackerOoT. It is a **custom resident GameState**, booted directly after engine
setup. It uses HackerOoT's scheduler, N64 controller polling, graphics buffers,
View camera, RSP/RDP display lists, text renderer and SRAM DMA. It does not enter
Zelda's player controller, file selector or gameplay save initialization.

The tile world, encounter rules and menu state come from `src/core.c`. Movement
and battle logic are therefore the same code as the host development harness.
The runtime is not a PC port, and the host harness is not the ROM.

## Native implementation

- A perspective tracking camera renders a small Pallet/Route 1 layout.
- Floor, buildings, trees, trainer, Oak and healer use original generated geometry.
- Battles show original block-model proxies for the five supported species.
- Native menus include moves, PP, HP bars, party, bag, run, save and load.
- D-pad or analog stick moves/selects; A confirms/interacts; B backs out; Start
  opens the field menu. Simulation advances at 30 updates/sec on NTSC.
- Dynamic vertex allocations are capped per frame. Overlay and opaque buffers are
  increased by the installer; the target remains the 8 MiB Expansion Pak.

Stadium and Snap models are **not imported**. `Creature()` is the explicit proxy
rendering boundary to replace after the extraction, skeleton and material
conversion pipeline has been validated. No copyrighted source ROM or ripped
asset is checked into this repository.

## Engine overlay

`upstream.json` pins HackerOoT to one exact commit and one supported base ROM.
`tools/bootstrap.py` creates an isolated checkout under `build/engine`, checks its
commit, validates exact source anchors, and installs the project sources. It adds
the game state to the state table, both table-consuming implementation files,
the boot transition and the resident code segment in `spec/spec`.

The installer refuses unknown edits and records hashes of installed files so
rerunning it can safely refresh our own changes. It does not reset or clean an
existing checkout. The native game has the ROM title `POKE N64 MVP` and game ID
`PK`; emulators/flashcarts may need save type explicitly set to **SRAM 32 KiB**.

## Cartridge save layout

The runtime owns a separate format; do not use an existing Zelda save file.
The stock SRAM initializer is never called. Two 512-byte records start at byte
0 and byte 512 of the 32 KiB cartridge SRAM:

| Offset | Bytes | Meaning |
|---|---:|---|
| 0 | 4 | `PK64` journal signature |
| 4 | 4 | Journal version, little-endian, currently 1 |
| 8 | 4 | Sequence number, little-endian |
| 12 | 4 | Payload length, currently 256 |
| 16 | 256 | Portable game save, with its own version and CRC |
| 272 | 4 | CRC32 over record bytes 0 through 271 |
| 276 | 236 | Zero padding |

At load, both records are checked, including the inner game codec and semantic
validation. The newest valid sequence wins. At save, only the other slot is
written, then read back and compared. Until validation succeeds, the previous
slot remains current. This preserves a valid prior save if a write is interrupted.
The implementation needs emulator and real cartridge testing before persistence
can be considered verified; a successful compile alone does not establish that.

## Build verification boundaries

`tools/check_native.py --require-mips` compiles the project, boot route, state
table and graphics dispatch with the pinned engine's actual headers into
big-endian VR4300 objects. It requires an installed MIPS GCC or `MIPS_CC`. Without
that compiler, the default command explicitly falls back to a 32-bit host syntax
check. No mocked engine header is used in either mode.

`tools/build_rom.py --rom /path/to/oot-ntsc-1.2.z64` validates the user's base ROM,
normalizes supported byte orders, extracts assets locally, links and compresses
the ROM, and writes a BPS patch. This step needs the original OoT US NTSC 1.2 ROM
and upstream build dependencies. It is intentionally not faked in CI.

The runtime uses F3DEX3. Test with an LLE-capable emulator such as ares or ParaLLEl
and 8 MiB RAM, then on original N64 hardware. Building a `.z64`, emulator booting,
completing the gameplay loop and power-cycle save recovery are distinct gates.
