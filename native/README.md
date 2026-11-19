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

On power-up, `Poke_Init` initializes letterbox state, which the engine's framebuffer setup requires, then enters a simple **blue framebuffer-clear probe** before the world renderer runs. Matrix, camera and game-state initialization are deferred until after the first A press. Press A to load SRAM and enter the game, or Z+A to enter without the SRAM read. This isolates early engine boot, persistence and scene drawing in that order. A black screen before the blue probe is not evidence of an unsupported Expansion Pak. The probe deliberately uses no imported assets, HUD font or geometry, so it can still appear when those systems fail.


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
`tools/bootstrap.py` creates an isolated checkout under `build/engine` for native
builds. The Docker wrappers use `build/docker-engine-arm64` or
`build/docker-engine-amd64`, according to the Docker daemon's architecture, and
pass that directory beneath `/project` as `--engine`. These checkouts stay
separate so each build uses tools, objects and Python environments made for its
host architecture.

The installer checks the pinned commit, validates exact source anchors, and
installs the project sources. It adds the game state to the state table, both
table-consuming implementation files, the boot transition and the resident code
segment in `spec/spec`.

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

## Build and verify

### Docker toolchain

On macOS, install and open Docker Desktop, and wait until its engine is running.
Use the Apple Silicon installer on Apple Silicon. The wrapper reads the Docker
daemon's architecture and uses its native `linux/arm64` or `linux/amd64` platform
for both image creation and execution. Docker Engine on Linux is also supported.
The host needs Python 3 and `make`; the container supplies GNU Make and the MIPS
cross toolchain. The resulting game targets the N64 on either build platform.

Run from the repository root:

```sh
# Build the toolchain, Python dependencies, host tools and six MIPS objects.
# No ROM is needed.
make check-native-docker

# Build the game using the checksum-matching OoT image in roms/.
make rom-docker

# Or select a local image explicitly, including a path outside the project.
make rom-docker ROM="/absolute/path/with spaces/oot-ntsc-1.2.z64"
```

`roms/` discovery and explicit `ROM=` inputs use the same size, byte-order and
checksum validation as `make check-rom` and `make rom`. The full Docker build
validates its input before image downloads or build writes. A Pokémon Stadium
image is not an input to this slice.

The image build uses the minimal `tools/docker-context` directory and the root
`Dockerfile`; no project source or ROM bytes are included in that context.
Runtime mounts make the project available at `/project`, the selected image
read-only at `/inputs/base.z64`, and `roms/` read-only when it exists. Generated
engine files remain in `build/docker-engine-arm64` or `build/docker-engine-amd64`.
The final outputs are unchanged:

```text
build/poke-n64.z64
build/poke-n64.bps
```

### Native host toolchain

`make rom` uses `build/engine` and requires GNU Make 4 or newer plus a complete
supported big-endian MIPS GCC/binutils toolchain on `PATH`. Its `gcc`, `as`, `ld`,
`objcopy`, `objdump`, `nm` and `strip` must share a supported prefix such as
`mips-linux-gnu-`. `tools/build_env.py` checks the prerequisites and follows the
pinned engine's toolchain selection order before engine installation or ROM
copying. The other upstream build dependencies are still required.

macOS's bundled Make is insufficient for the upstream engine. Homebrew's `make`
package supplies `gmake`, which the helper detects, but does not provide a MIPS
cross compiler. Use `make rom-docker` if the native toolchain is unavailable.

### Verification boundaries

`tools/check_native.py --require-mips` compiles the project, boot route, state
table and graphics dispatch with the pinned engine's actual headers into
six big-endian VR4300 objects. It requires an installed MIPS GCC or `MIPS_CC`.
Without that compiler, `make check-native` explicitly falls back to a 32-bit host
syntax check. `MIPS_CC` applies to this checker, not to the full upstream ROM
build. No mocked engine header is used in either mode.

`make check-native-docker` runs the build preflight and requires real MIPS object
compilation inside the actual image. It also installs the engine's Python
dependencies and compiles its host tools, exercising the upstream Makefile and
tool setup without a ROM. CI runs this command on native AMD64
(`ubuntu-24.04`) and ARM64 (`ubuntu-24.04-arm`) runners. These checks do not
extract game assets, link a complete ROM or run the game.

`tools/build_rom.py --rom /path/to/oot-ntsc-1.2.z64` validates the user's base ROM,
normalizes supported byte orders, extracts assets locally, links and compresses
the ROM, and writes a BPS patch. This step needs the original OoT US NTSC 1.2 ROM
and upstream build dependencies. It is intentionally not faked in CI.

The native sources and boot hooks have passed actual MIPS object compilation.
A complete ROM was linked locally and its blue boot screen verified in ParaLLEl
N64 through RetroArch on 19 November 2026. The earlier startup TLB load fault at
`Letterbox_GetSize` came from delaying letterbox initialization until after A;
framebuffer setup already needs that state on the first frame. Native gameplay,
cartridge saving and real hardware remain unverified. The Docker object check
alone does not establish ROM linking or emulator results.

The runtime uses F3DEX3. Test with an LLE-capable emulator such as ares or ParaLLEl
and 8 MiB RAM, then on original N64 hardware. Building a `.z64`, emulator booting,
completing the gameplay loop and power-cycle save recovery are distinct gates.
