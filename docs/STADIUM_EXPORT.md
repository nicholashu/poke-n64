## Animated Bulbasaur and native OoT battle preview

The conversion branch now also includes an opt-in, end-to-end **animated** pipeline. It reads the actual Stadium DSM3 bone tracks, emits an armature and idle/attack animation clips in GLB, and optionally generates F3DEX3-ready C data for native N64.

```sh
# Re-use the DSM3 file you successfully extracted previously.
python3 tools/stadium_export.py --pack assets/private/stadium/001/source.dsm --species 1 --animated

# Bake real skeleton animation into bounded N64 display-list vertex frames.
make stadium-n64

# Build the separate OoT PlayState ROM, with generated private asset if present.
make rom-oot-docker
```

New private outputs:

```text
assets/private/stadium/001/
  source.dsm
  stadium-001-animated.glb
  stadium-001-animated.json
  stadium_bulbasaur_n64.c
```

The skinned GLB has joint weights, inverse-bind matrices, and Stadium **idle** and **attack_default** animation curves where those contexts exist. Animation track frequencies are 30 FPS. Blender should show an armature and animation clips when importing the GLB.

The N64 path is deliberately a separate optimized representation rather than shipping the GLB inside the ROM. It samples at most 12 key poses per animation, bakes weighted mesh geometry offline, batches triangles for the 32-vertex RSP limit, and downsamples textures to RGBA5551 within 4 KiB TMEM. Its source file is generated under ignored `assets/private/` and copied into the OoT checkout at build time. Without it, the native build uses a copyright-free stub.

### In-game controls (temporary Kokiri Forest test)

First choose **Bulbasaur** using L+C-left. The test controls are:

- **L+R+A:** play a Stadium Bulbasaur attack animation next to Link
- **L+R+B:** start a level-4 wild Rattata turn-based battle with a native OoT sub-camera
- **D-pad up/down, A, B:** navigate Pokémon's Fight/Bag/Party/Run and moves; the Pokémon rules resolve HP, PP and turns

The enemy currently has an **original cuboid placeholder**, not a Stadium Rattata model. Kokiri Forest is also a test arena, not a finished battle background. The camera uses OoT's sub-camera system, then returns to its native follow camera when the battle ends.

The normal `make rom-docker` prototype is unchanged. The new asset and battle are enabled only in the experimental OoT total conversion.

### Verification boundary

Automated tests use an original synthetic one-triangle model to verify skinned GLB structure and animation channels, the offline N64 vertex frame generator, texture downsampling and a **real MIPS cross-compile of generated C graphics code**. Those tests do not prove your private ROM's Bulbasaur animations are visually correct, nor do they replace a gameplay test in ParaLLEl N64.

Use your previously working Stadium ROM revision; the source extractor still only explicitly supports the known US 1.0 layout. Never upload generated C, models or the ROM to a public repository.

---

# Pokémon Stadium to OoT asset export

**Status:** First working **static** model exporter. This pipeline produces Blender-readable glTF 2.0 GLB geometry with embedded RGBA textures and a JSON animation index. Full skinned animation export and native OoT actor integration are separate steps.

The source ROM never leaves your computer. All model packs and derived files are placed in the Git-ignored assets/private/stadium/ directory. Do not commit or publish them.

## Quick start

Requires Python 3.10+, Node.js 20+, npm and Git. This exporter runs on your Mac; Docker and the MIPS toolchain aren't needed until we export from Blender into the OoT ROM.

From the feat/stadium-model-export branch:

    # Identify the ROM revision without installing any tools.
    make stadium-inspect

    # Default: export Bulbasaur (#001).
    make stadium-export

    # Another species, e.g. Rattata (#019).
    make stadium-export STADIUM_SPECIES=19

    # Point to a ROM outside roms/, even if the path has spaces:
    STADIUM_ROM="/absolute/path/Pokemon Stadium (USA) (Rev 2).z64" make stadium-export STADIUM_SPECIES=19

If you already have an extracted DSM3 or PVDZ model pack, bypass third-party ROM extraction:

    python3 tools/stadium_export.py --pack "/path/to/019.dsm" --species 19

### How it works

1. The Python tool finds your local roms/Pokemon Stadium ROM, or uses STADIUM_ROM.
2. It normalizes N64 byte order to .z64, records the MD5 and identifies the cartridge revision.
3. It checks out a **pinned** public [Stadium Animation Inspector](https://github.com/Nexhas28/stadium-animation-inspector) revision under build/stadium-animation-inspector/, then uses npm to build the worker. We do not vendor or redistribute that third-party code.
4. The model pack is generated using the inspector's compiled model worker, driven by tools/stadium_extract.mjs.
5. Our Python converter validates DSM3 bones, mesh indices, textures and animation metadata and writes a Blender-ready GLB.

Example outputs for Bulbasaur:

    assets/private/stadium/001/
      source.dsm         # ROM-derived intermediate, private
      stadium-001.glb    # Blender-ready textured static model, private
      stadium-001.json   # species, bounds, animations and move mappings

### Important: your Stadium ROM is Rev 2

The model extractor was developed and tested against **Pokémon Stadium US 1.0**, normalized MD5 ed1378bc12115f71209a77844965ba50.

Your earlier Finder screenshot shows **Pokémon Stadium (USA) (Rev 2)**, a later cartridge revision. The extractor uses fixed model-archive and battle-table addresses derived from US 1.0. **Rev 2 has not been verified compatible**.

Our tool warns when the normalized ROM MD5 differs from US 1.0, attempts local extraction, and validates the resulting pack. It never silently treats an unverified revision as supported. If it fails with an archive/model parsing error, we need to map the Rev 2 model archive and battle pointer table or use a compatible US 1.0 cartridge dump. The repo provides no copyrighted ROMs or downloads.

Use make stadium-inspect first. It prints the actual header revision, normalized MD5, and whether the known US 1.0 model archive at 0x920000 has a valid directory, without installing anything. An archive match does not by itself prove that Rev 2's battle pointer tables and animations work. If the archive probe fails, extraction stops before installing third-party packages.

## Blender → Fast64 → OoT

The GLB is an interchange asset, **not** an OoT actor ready to link.

1. In Blender, File → Import → glTF 2.0, then select stadium-001.glb.
2. Inspect textures, scale and model facing. The exporter rotates the root 180° around Y and targets 1.5 scene units of height by default. Use --height to change that.
3. Install [Fast64](https://github.com/Fast-64/fast64), choose the OoT game mode, enable HackerOoT features and select the local decomp path.
4. Convert imported Blender glTF materials into Fast64 **F3D materials**. Standard PBR materials do not export directly as N64 display lists.
5. Optimize the geometry/textures for N64 memory; export the object through Fast64 and wire its display lists through a battle actor. See [Fast64's OoT guide](https://github.com/Fast-64/fast64/blob/main/fast64_internal/z64/README.md).
6. Check the converted actor visually on F3DEX3-capable ParaLLEl N64 before enabling it in the game.

The GLB may require texture downsampling, batching, geometry simplification and material cleanup before it runs efficiently on original N64 hardware.

## Output coverage

| Stadium content | Current output |
| --- | --- |
| Geometry and triangle indices | GLB |
| Original RGBA textures | Embedded PNGs inside GLB |
| UVs, normals and culling flags | GLB |
| Bone rest-pose transforms | Baked into static mesh |
| Animation names, durations, context slots and move IDs | JSON metadata |
| Live skeleton, skin and animation curves | Not yet |
| Special material effects and texture flipbooks | Metadata only |
| Fast64-native C actor ready for N64 | Not yet |

**Exporting geometry is not the same as completing an animated Stadium battle character.** The next stage is a skinned model with idle and move animations, followed by automated OoT actor export.

## Verification

Run the ROM-free unit tests locally:

    python3 -m unittest tests.test_stadium_export -v
    make test

The tests synthesize an original one-triangle DSM3 model with texture and animation header, verifying the parser, LZ4 decoder, GLB mesh/material structure, invalid-data guards, output reporting and revision detection. No Nintendo assets enter CI.

Real end-to-end extraction must still be tested against your ROM and visually inspected in Blender. Unit tests do not prove Rev 2 compatibility or that a model is playable on N64.

### Troubleshooting

- **ROM not identified:** run make stadium-inspect and verify filename, title and cartridge revision.
- **Model archive not recognized:** the 1.0 model layout may differ in Rev 2. Share the fingerprint and error output; don't substitute arbitrary offsets.
- **Extractor installation fails:** check Node 20+, npm and Git. Its isolated checkout is under build/.
- **GLB imports without textures:** inspect embedded PNGs and convert materials to Fast64 F3D materials.
- **Facing looks reversed:** adjust the Blender root rotation before exporting to OoT.
- **Animations don't play:** expected. This stage bakes the rest pose and lists animation metadata but does not yet export animation curves.
