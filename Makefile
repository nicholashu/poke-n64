CC ?= cc
PYTHON ?= python3
CFLAGS ?= -O2 -g
WARNINGS = -std=c11 -Wall -Wextra -Werror -pedantic
CPPFLAGS += -Iinclude
CORE = src/core.c src/save.c
HEADERS = include/poke.h
HOST = build/poke-n64
# Export paths verbatim rather than interpolating filenames into a shell command.
export POKE_N64_ROM := $(ROM)
export POKE_POKEMON_ROM := $(POKEMON_ROM)
STADIUM_SPECIES ?= 1
export STADIUM_SPECIES
export STADIUM_ROM

.PHONY: play-pallet rom-pallet-e2e test-pallet-opening all play test sanitize check-native check-native-docker check-native-oot-docker check-rom engine rom rom-docker rom-oot-docker rom-oot-play import-pallet rom-pallet-docker play-oot test-rom test-battle rom-oot-e2e rom-control-docker stadium-inspect stadium-export stadium-animated stadium-n64 clean help test-opening test-scripted-rom rom-opening-e2e
all: $(HOST)

build:
	mkdir -p build

$(HOST): $(CORE) host/main.c $(HEADERS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) $(CORE) host/main.c -o $@

build/test-core: $(CORE) tests/test_core.c $(HEADERS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) $(CORE) tests/test_core.c -o $@

build/test-save: $(CORE) tests/test_save.c $(HEADERS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) $(CORE) tests/test_save.c -o $@

build/test-pallet-import: src/pallet_import.c tests/test_pallet_import.c include/poke_pallet_import.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) src/pallet_import.c tests/test_pallet_import.c -o $@

build/poke_world.c: tools/kanto_layout.py assets/maps/pallet_opening.json | build
	$(PYTHON) tools/kanto_layout.py --output $@

build/test-intro: $(CORE) src/intro.c native/pallet_import_stub.c tests/test_intro.c include/poke_intro.h $(HEADERS) build/poke_world.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) $(CORE) src/intro.c native/pallet_import_stub.c build/poke_world.c tests/test_intro.c -o $@

play: $(HOST)
	./$(HOST) $(ARGS)

test: $(HOST) build/test-core build/test-save build/test-pallet-import build/test-intro
	./build/test-core
	./build/test-save
	./build/test-pallet-import
	./build/test-intro
	$(PYTHON) host/test_cli.py $(HOST)
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

sanitize: build/poke_world.c | build
	$(CC) $(CPPFLAGS) $(WARNINGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) tests/test_core.c -o build/test-core-sanitize
	$(CC) $(CPPFLAGS) $(WARNINGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) tests/test_save.c -o build/test-save-sanitize
	./build/test-core-sanitize
	./build/test-save-sanitize
	$(CC) $(CPPFLAGS) $(WARNINGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer src/pallet_import.c tests/test_pallet_import.c -o build/test-pallet-import-sanitize
	./build/test-pallet-import-sanitize
	$(CC) $(CPPFLAGS) $(WARNINGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) src/intro.c native/pallet_import_stub.c build/poke_world.c tests/test_intro.c -o build/test-intro-sanitize
	./build/test-intro-sanitize

engine:
	$(PYTHON) tools/bootstrap.py

check-native:
	$(PYTHON) tools/check_native.py

check-native-docker:
	$(PYTHON) tools/docker_rom.py --check-tools

check-native-oot-docker:
	$(PYTHON) tools/docker_rom.py --check-tools --oot-conversion

check-rom:
	$(PYTHON) tools/build_rom.py --check

rom:
	$(PYTHON) tools/build_rom.py

rom-docker:
	$(PYTHON) tools/docker_rom.py

rom-oot-docker:
	$(PYTHON) tools/docker_rom.py --oot-conversion

import-pallet:
	$(PYTHON) tools/pallet_rom.py

rom-pallet-docker:
	$(PYTHON) tools/docker_rom.py --oot-conversion --require-pokemon-rom

# ROM-extracted Pallet exterior plus the entire five-room opening.
# Uses private GB data only in the local build, never committed to Git.
play-pallet:
	$(PYTHON) tools/play_oot.py --rom build/poke-n64-pallet.z64

test-pallet-opening:
	$(PYTHON) tools/opening_e2e.py --rom build/poke-n64-pallet.z64 --starter $(STARTER) $(OPENING_ARGS)

rom-pallet-e2e: rom-pallet-docker
	$(PYTHON) tools/opening_e2e.py --rom build/poke-n64-pallet.z64 --starter $(STARTER) $(OPENING_ARGS)

# Always launch with unique, empty cartridge-save and savestate directories.
play-oot:
	$(PYTHON) tools/play_oot.py

# One command to rebuild and play, with clean emulator state.
rom-oot-play: rom-oot-docker
	$(PYTHON) tools/play_oot.py

# Full native opening, using ordinary input plus CRC-checked screen telemetry.
STARTER ?= bulbasaur
OPENING_ARGS ?=
test-opening:
	$(PYTHON) tools/opening_e2e.py --starter $(STARTER) $(OPENING_ARGS)

# Existing commands now exercise the actual opening, including the rival fight.
test-rom test-battle: test-opening

# JSON runner remains available for diagnostic/custom controller sequences.
ROM_SCENARIO ?= tests/rom_scenarios/pallet_smoke.json
test-scripted-rom:
	$(PYTHON) tools/retroarch_e2e.py $(ROM_SCENARIO)

rom-oot-e2e rom-opening-e2e: rom-oot-docker
	$(PYTHON) tools/opening_e2e.py --starter $(STARTER) $(OPENING_ARGS)

rom-control-docker:
	$(PYTHON) tools/docker_rom.py --control-boot

stadium-inspect:
	$(PYTHON) tools/stadium_export.py --inspect-only

stadium-export:
	$(PYTHON) tools/stadium_export.py

stadium-animated:
	$(PYTHON) tools/stadium_export.py --animated

stadium-n64:
	$(PYTHON) tools/stadium_n64.py

clean:
	rm -f build/poke-n64 build/test-core build/test-save build/test-core-sanitize build/test-save-sanitize build/test-pallet-import build/test-pallet-import-sanitize build/test-intro build/test-intro-sanitize build/poke_world.c

help:
	@echo 'make play                  Play the shared-core development console'
	@echo 'make test                  Gameplay, persistence and end-to-end checks'
	@echo 'make sanitize              Core tests with ASan and UBSan'
	@echo 'make check-native          Compile-check against pinned HackerOoT headers'
	@echo 'make check-native-docker   Check the Linux container toolchain without a ROM'
	@echo 'make check-rom             Validate the Zelda image in roms/ without building'
	@echo 'make rom                   Detect the matching Zelda image in roms/ and build'
	@echo 'make rom ROM=/path/oot.z64  Build native ROM using your OoT NTSC 1.2 dump'
	@echo 'make rom-docker            Build original standalone Pokémon prototype'
	@echo 'make rom-oot-docker        Build Pokémon total conversion on native OoT PlayState'
	@echo 'make import-pallet         Extract/compile Pallet from POKEMON_ROM=/path/red.gb'
	@echo 'make rom-pallet-docker     Build converted Red/Blue ROM with full opening'
	@echo 'make play-pallet           Play converted Red/Blue N64 ROM with clean saves'
	@echo 'make test-pallet-opening   Run bedroom-to-rival E2E on converted ROM'
	@echo 'make rom-pallet-e2e        Build converted ROM and test the entire opening'
	@echo 'make play-oot              Launch built OoT ROM with fresh SRAM/savestate dirs'
	@echo 'make rom-oot-play          Build then clean-launch Pokémon in ParaLLEl N64'
	@echo 'make test-opening          Bedroom to rival battle and back outside (STARTER=bulbasaur)'
	@echo 'make test-scripted-rom     Run a diagnostic JSON controller scenario'
	@echo 'make test-rom              Alias for the full first-area controller playthrough'
	@echo 'make test-battle           Alias for the opening, including the rival battle'
	@echo 'make rom-oot-e2e           Build ROM then play through the entire opening'
	@echo 'make check-native-oot-docker Check native OoT integration without a ROM'
	@echo 'make rom-control-docker    Build stock-boot diagnostic ROM'
	@echo 'make stadium-inspect        Fingerprint local Stadium ROM'
	@echo 'make stadium-export         Export static textured Stadium GLB'
	@echo 'make stadium-animated       Export rigged Stadium GLB with idle and attack clips'
	@echo 'make stadium-n64            Bake private Bulbasaur frames/textures into N64-compatible C'
