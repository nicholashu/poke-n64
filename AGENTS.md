# Pokémon N64 development

- This is a native Nintendo 64 project based on pinned HackerOoT. The host console is a development frontend using the same C rules, not a replacement target.
- Use C11 with fixed-width integers in `src/`. Keep platform I/O and engine types out of the gameplay core.
- Run `make test` after gameplay changes and `make sanitize` when memory handling changes. Run `make check-native` after native adapter or shared API changes.
- Check actual pinned upstream APIs before changing native integration. Link new resident objects explicitly in the engine spec.
- Never commit ROMs, extracted proprietary assets, generated engine files, saves or credentials. Keep user-supplied inputs local.
- Save bytes are a versioned contract. Validate into a temporary state before committing a load. Keep host/N64 endianness independent.
- Preserve the explicit distinction between host tests, native object compilation, a linked ROM, emulator testing and real-hardware testing in status reports.
- Keep unfinished functionality visible in the README. Do not claim Stadium models or full Gen 1 accuracy until implemented and verified.
- Work directly in this repository. Do not route work through T3 unless Nick explicitly requests it.
