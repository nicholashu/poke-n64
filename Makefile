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
STADIUM_SPECIES ?= 1
export STADIUM_SPECIES
export STADIUM_ROM

.PHONY: all play test sanitize check-native check-native-docker check-native-oot-docker check-rom engine rom rom-docker rom-oot-docker rom-oot-play play-oot rom-control-docker stadium-inspect stadium-export stadium-animated stadium-n64 clean help
all: $(HOST)

build:
	mkdir -p build

$(HOST): $(CORE) host/main.c $(HEADERS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) $(CORE) host/main.c -o $@

build/test-core: $(CORE) tests/test_core.c $(HEADERS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) $(CORE) tests/test_core.c -o $@

build/test-save: $(CORE) tests/test_save.c $(HEADERS) | build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) $(CORE) tests/test_save.c -o $@

play: $(HOST)
	./$(HOST) $(ARGS)

test: $(HOST) build/test-core build/test-save
	./build/test-core
	./build/test-save
	$(PYTHON) host/test_cli.py $(HOST)
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

sanitize: | build
	$(CC) $(CPPFLAGS) $(WARNINGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) tests/test_core.c -o build/test-core-sanitize
	$(CC) $(CPPFLAGS) $(WARNINGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) tests/test_save.c -o build/test-save-sanitize
	./build/test-core-sanitize
	./build/test-save-sanitize

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

# Always launch with unique, empty cartridge-save and savestate directories.
play-oot:
	$(PYTHON) tools/play_oot.py

# One command to rebuild and play, with clean emulator state.
rom-oot-play: rom-oot-docker
	$(PYTHON) tools/play_oot.py

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
	rm -f build/poke-n64 build/test-core build/test-save build/test-core-sanitize build/test-save-sanitize

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
	@echo 'make play-oot              Launch built OoT ROM with fresh SRAM/savestate dirs'
	@echo 'make rom-oot-play          Build then clean-launch Pokémon in ParaLLEl N64'
	@echo 'make check-native-oot-docker Check native OoT integration without a ROM'
	@echo 'make rom-control-docker    Build stock-boot diagnostic ROM'
	@echo 'make stadium-inspect        Fingerprint local Stadium ROM'
	@echo 'make stadium-export         Export static textured Stadium GLB'
	@echo 'make stadium-animated       Export rigged Stadium GLB with idle and attack clips'
	@echo 'make stadium-n64            Bake private Bulbasaur frames/textures into N64-compatible C'
