"""Semantic Gen 1 opening-area coordinates shared by geometry and native code.

The JSON contains functional layout facts, not Game Boy graphics or ROM data.
Its pinned reference lets tests compare every static passability cell.
"""
from __future__ import annotations
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "assets/maps/pallet_opening.json"
DATA = json.loads(SOURCE.read_text())
ROOMS = DATA["rooms"]
ORDER = ("PalletTown", "RedsHouse2F", "RedsHouse1F", "BluesHouse", "OaksLab")
CELL = DATA["cell_units"]


def bounds(name):
    w, h = ROOMS[name]["dimensions"]
    return (-w*CELL//2, -h*CELL//2, w*CELL//2, h*CELL//2)


def point(name, x, z):
    left, north, _, _ = bounds(name)
    return (round(left+(x+0.5)*CELL), round(north+(z+0.5)*CELL))


def walkable(name, x, z):
    room = ROOMS[name]
    w, h = room["dimensions"]
    return 0 <= x < w and 0 <= z < h and room["static_walkable_rows"][z][x] == "."


def validate():
    for name in ORDER:
        room = ROOMS[name]
        w, h = room["dimensions"]
        for key in ("semantic_rows", "static_walkable_rows"):
            rows = room[key]
            if len(rows) != h or any(len(row) != w for row in rows):
                raise ValueError(f"{name}: malformed {key}")
        for x, z, _ in room["spawns"]:
            if not walkable(name, x, z):
                raise ValueError(f"{name}: blocked spawn {(x,z)}")
        for warp in room["warps"]:
            if not walkable(name, *warp["at"]):
                raise ValueError(f"{name}: blocked warp")
            if not 0 <= warp["spawn"] < len(ROOMS[warp["destination"]]["spawns"]):
                raise ValueError(f"{name}: invalid destination spawn")


def core_source():
    validate()
    lines = ['/* Generated semantic map coordinates; no graphic assets. */', '#include "poke_intro.h"']
    for i, name in enumerate(ORDER):
        rows = ROOMS[name]["static_walkable_rows"]
        lines += [f'static const char* const sMap{i}[] = {{']
        lines += [f'    "{row}",' for row in rows]
        lines += ['};']
    lines += ['const PokeIntroMap gPokeIntroMaps[INTRO_ROOM_COUNT] = {']
    for i, name in enumerate(ORDER):
        room = ROOMS[name]; w,h = room["dimensions"]
        lines.append(f'    {{ {w}, {h}, "{room["title"]}", sMap{i} }},')
    lines += ['};', 'const PokeIntroWarp gPokeIntroWarps[] = {']
    for i, name in enumerate(ORDER):
        for warp in ROOMS[name]["warps"]:
            x,z = warp["at"]
            lines.append(f'    {{ {i}, {x}, {z}, {ORDER.index(warp["destination"])}, {warp["spawn"]} }},')
    lines += ['};', 'const unsigned gPokeIntroWarpCount = sizeof(gPokeIntroWarps)/sizeof(gPokeIntroWarps[0]);', '']
    return '\n'.join(lines)


def native_header():
    lines = ['#ifndef POKE_WORLD_NATIVE_H', '#define POKE_WORLD_NATIVE_H', '#include "scene.h"', '#include "poke_intro.h"',
             f'#define POKE_WORLD_CELL {CELL}',
             'static const s16 sPokeSceneIds[INTRO_ROOM_COUNT] = {']
    lines += [f'    {ROOMS[n]["scene"]},' for n in ORDER]
    lines += ['};', 'static const s16 sPokeEntrances[INTRO_ROOM_COUNT] = {']
    lines += [f'    {ROOMS[n]["entrance"]},' for n in ORDER]
    lines += ['};', '#endif', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(core_source())
