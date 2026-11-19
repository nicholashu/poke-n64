# Build performance and slim-ROM roadmap

## Why the old build was slow

The legacy `tools/build_rom.py` called HackerOoT `make setup` every time. In
HackerOoT, `setup` depends on `venv` and invokes several ROM extraction tasks:
decompressing the source ROM, extracting its individual segments, generating
graphics assets, text and audio data. Those tasks are preparatory work, not
normal incremental compilation.

In addition, `tools/bootstrap.py` rewrote every overlaid source file even
when unchanged, altering timestamps and invalidating Make's dependency graph.

Finally, HackerOoT's `make compress` target unconditionally touches `spec`
and `src/boot/z_std_dma.c`. This forces an extra link/compression round
even when the previous compressed ROM remains current.

## What the incremental build changes

1. **Extract once:** after a successful `setup`, store
   `.poke-setup-cache.json` inside the isolated upstream engine checkout.
   The stamp pins the source engine commit, game version, region and validated
   input ROM digest. The cache is reused if these match and expected extracted
   outputs exist. Incomplete or failed setups are never cached.
2. **Keep timestamps stable:** only write a patched source, copied Pokémon
   source or manifest when its content genuinely changes. This lets Make
   recompile the individual object files affected by the edit.
3. **Don't rewrite the 32 MiB input:** if an identical base ROM was already
   copied, keep its original timestamp.
4. **Recompress only when the raw linked ROM changed:** after the normal
   incremental Make pass, compare the uncompressed and compressed ROM
   timestamps. If the compressed build is still current, skip HackerOoT's
   forced-touch `compress` target. Otherwise run it unchanged.
5. **Refresh explicitly:** run `python3 tools/docker_rom.py
   --oot-conversion --refresh-setup` if changing upstream asset extraction
   rules or intentionally recreating extracted files.

HackerOoT's own Make dependencies continue to decide which C files, scenes
and assets compile. This wrapper does **not** replace its linker or its scene
format.

### Expected build stages

| Situation | Upstream extraction | Compile/assemble | ROM link/compress |
| --- | --- | --- | --- |
| First build for the selected engine | Full | Full baseline | Yes |
| Build again without edits | Reused | Make checks timestamps, normally no rebuild | Reuse compressed ROM |
| Edit Pokémon C code / battle logic | Reused | Changed objects and dependent build inputs | Yes |
| Replace a generated Stadium model | Reused | Asset object and affected dependencies | Yes |
| Change OoT scene XML / extraction input | Explicit refresh may be required | Affected generated assets | Yes |
| Delete extracted assets or cached engine | Full setup | Rebuild as necessary | Yes |

No performance ratio is claimed without a before/after timed build using the
user's local ROM and Docker configuration.

## Why we still ship unused OoT scenes for now

The total conversion currently boots into Kokiri Forest and uses OoT's original
player actor, camera, collision and scene infrastructure. Upstream
`spec/spec` includes the original `scenes_n64.inc` and other segment
definitions, while scene/entrance/object tables contain hardcoded IDs and
addresses. Removing individual scenes from the build without updating these
references can yield broken DMA tables, blank scene loads or out-of-range
asset references.

Most unused scene and texture data lives in **ROM storage** and is loaded into
RAM on demand. Removing it may reduce output size and first-build processing,
but does not automatically make gameplay faster or free the same amount of RAM.

A deliberately slim ROM should be a separate milestone:

1. Finish a native Pallet Town and Route 1 scene with collision and a Red
   player actor, retaining a working emulator boot test.
2. Inventory all referenced scenes, rooms, objects, actors, cutscenes, sound
   banks and animations, including runtime transitions, rather than guessing
   from directory names.
3. Create a Kanto-only scene registry or guarded configuration that retains
   stable IDs/stubs for any references still expected by the engine.
4. Remove unreachable scene/object segments from the ROM spec and adjust
   scene/object tables and DMA mappings together.
5. Iteratively cut unused Zelda gameplay systems and assets while checking
   the linked ROM, startup, model rendering, battle transitions and save
   behaviour in ParaLLEl N64 and ultimately original hardware.

Do **not** delete upstream asset directories to make builds "faster". That is
not a safe way to produce a smaller ROM.

## Validation

Cache and source-timestamp behaviour is covered by
`tests/test_build_cache.py` and `tests/test_tools.py`, which use synthetic
files and do not require proprietary assets.

To compare performance on your Mac:

```sh
git switch feat/incremental-rom-build
time make rom-oot-docker   # First run after switching may create the setup stamp
time make rom-oot-docker   # Cache-hit reference
make stadium-n64           # If using your local Stadium model
time make rom-oot-docker   # Test Pokémon-asset rebuild
```

The Docker image and extracted engine persist under
`build/docker-engine-<arch>-oot/`. Use the same architecture and workspace to
benefit from the caches.
