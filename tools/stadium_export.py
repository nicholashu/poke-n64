#!/usr/bin/env python3
"""Export a locally extracted Pokémon Stadium DSM3/PVDZ model as Blender-ready GLB.

Uses only Python's standard library for conversion. With --rom, invokes a
pinned, separately cloned third-party extractor on the user's machine.
No Stadium ROM, source model or derived binary is committed to this repository.
This currently exports one static bind-pose mesh plus texture images and
animation *metadata*, NOT animated/skeletal GLB tracks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "assets/private/stadium"
INSPECTOR = ROOT / "build/stadium-animation-inspector"
INSPECTOR_URL = "https://github.com/Nexhas28/stadium-animation-inspector.git"
INSPECTOR_REV = "035494cceb74d63d72251cdc66fd42d1abfb76f3"
US10_MD5 = "ed1378bc12115f71209a77844965ba50"
CONTEXTS = (
    "idle", "attack_default", "faint", "entrance", "reaction_169",
    "reaction_170", "reaction_171", "reaction_172", "reaction_173",
    "reaction_174", "struggle", "idle_alt", "faint_alt", "flinch",
    "reaction_179", "reaction_180", "reaction_181", "reaction_182",
    "entrance_alt", "idle_return",
)
MAGICS = {b"\x80\x37\x12\x40", b"\x37\x80\x40\x12", b"\x40\x12\x37\x80"}
MAX_PACK = 64 * 1024 * 1024


class StadiumExportError(ValueError):
    pass


class Reader:
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.offset = offset

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise StadiumExportError(f"Truncated model at 0x{self.offset:X} (need {size} bytes)")
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def unpack(self, code: str):
        fmt = "<" + code
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def u8(self): return self.unpack("B")[0]
    def i8(self): return self.unpack("b")[0]
    def u16(self): return self.unpack("H")[0]
    def i16(self): return self.unpack("h")[0]
    def u32(self): return self.unpack("I")[0]
    def f32(self): return self.unpack("f")[0]
    def fixed(self): return self.unpack("i")[0] / 65536.0


def lz4_block(encoded: bytes, expected: int) -> bytes:
    """Bounded raw LZ4 block decoder for PVDZ, including overlapping matches."""
    if not (0 < expected <= MAX_PACK):
        raise StadiumExportError(f"Invalid PVDZ decoded length: {expected}")
    result = bytearray()
    at = 0

    def length_with_extension(base: int) -> int:
        nonlocal at
        while base >= 15:
            if at >= len(encoded):
                raise StadiumExportError("Truncated LZ4 length")
            extra = encoded[at]
            at += 1
            base += extra
            if extra != 255:
                break
        return base

    while at < len(encoded):
        token = encoded[at]
        at += 1
        literals = length_with_extension(token >> 4)
        if at + literals > len(encoded) or len(result) + literals > expected:
            raise StadiumExportError("LZ4 literals extend beyond input or output")
        result.extend(encoded[at:at + literals])
        at += literals
        if at == len(encoded):
            break
        if at + 2 > len(encoded):
            raise StadiumExportError("Missing LZ4 match offset")
        distance = encoded[at] | (encoded[at + 1] << 8)
        at += 2
        if distance == 0 or distance > len(result):
            raise StadiumExportError("Invalid LZ4 back-reference offset")
        match_length = length_with_extension(token & 15) + 4
        if len(result) + match_length > expected:
            raise StadiumExportError("LZ4 match exceeds decoded output")
        for _ in range(match_length):
            result.append(result[-distance])
    if len(result) != expected:
        raise StadiumExportError(f"LZ4 decoded {len(result)} bytes, expected {expected}")
    return bytes(result)


def unpack_pack(data: bytes) -> bytes:
    if data[:4] == b"DSM3":
        return data
    if data[:4] != b"PVDZ" or len(data) < 9:
        raise StadiumExportError("Expected DSM3 model or PVDZ compressed model")
    expected = struct.unpack_from("<I", data, 4)[0]
    if expected > MAX_PACK:
        raise StadiumExportError("PVDZ output exceeds size limit")
    start = 12 if len(data) >= 12 and struct.unpack_from("<I", data, 8)[0] == expected else 8
    decoded = lz4_block(data[start:], expected)
    if decoded[:4] != b"DSM3":
        raise StadiumExportError("PVDZ did not contain DSM3 model data")
    return decoded


def read_dsm(data: bytes) -> dict:
    data = unpack_pack(data)
    if len(data) > MAX_PACK:
        raise StadiumExportError("Model pack exceeds 64 MiB limit")
    r = Reader(data, 4)
    species, bone_count, prim_count, tex_count, anim_count, aux_count = r.unpack("6H")
    if not (1 <= species <= 151 and 1 <= bone_count <= 256 and
            0 < prim_count <= 1024 and tex_count <= 2048 and
            anim_count <= 2048 and aux_count <= 2048):
        raise StadiumExportError("Invalid DSM3 species/rig/mesh/animation counts")
    root_scale = r.f32()
    static_pose = bool(r.u8())
    height, floor, radius = r.unpack("3f")
    if not all(math.isfinite(x) for x in (root_scale, height, floor, radius)):
        raise StadiumExportError("Invalid model scale/bounds")
    move_anim = [r.u16() for _ in range(165)]
    move_aux = [r.i16() for _ in range(165)]
    contexts = [r.u16() for _ in CONTEXTS]
    bones = []
    for i in range(bone_count):
        parent = r.i16()
        t = r.unpack("3h")
        rot = r.unpack("3h")
        scale = tuple(r.fixed() for _ in range(3))
        if parent != -1 and not (0 <= parent < bone_count and parent != i):
            raise StadiumExportError(f"Invalid bone parent {parent} at bone {i}")
        bones.append({"parent": parent, "t": t, "r": rot, "s": scale})
    prims = []
    for _ in range(prim_count):
        texture = r.u16()
        cull = bool(r.u8())
        additive = bool(r.u8())
        tex_anim = r.i16()
        maps = {r.u8(): r.u16() for _ in range(r.u8())}
        fx_count = r.u16()
        if fx_count > 10000:
            raise StadiumExportError("Unreasonable texture effect frame count")
        r.take(2 * fx_count)
        vert_count, index_count = r.unpack("2H")
        if vert_count == 0 or index_count == 0 or index_count % 3:
            raise StadiumExportError("Empty mesh or index count not divisible by 3")
        vertices = []
        for _ in range(vert_count):
            x, y, z, u, v, nx, ny, nz, bone = r.unpack("5h3bB")
            if bone >= bone_count:
                raise StadiumExportError(f"Vertex references missing bone {bone}")
            vertices.append((x, y, z, u / 512.0, v / 512.0,
                             nx / 127.0, ny / 127.0, nz / 127.0, bone))
        indices = [r.u16() for _ in range(index_count)]
        if max(indices) >= vert_count:
            raise StadiumExportError("Mesh contains invalid vertex index")
        prims.append({"texture": texture, "cull": cull, "additive": additive,
                      "textureAnimation": tex_anim, "maps": maps,
                      "vertices": vertices, "indices": indices})
    textures = []
    for _ in range(tex_count):
        w, h = r.unpack("2H")
        n = r.u32()
        if not (0 < w <= 4096 and 0 < h <= 4096 and w * h * 4 == n):
            raise StadiumExportError("Bad RGBA texture dimensions or data length")
        textures.append((w, h, r.take(n)))
    animations = []
    for _ in range(anim_count):
        name_len = r.u8()
        name = r.take(name_len).decode("ascii", "replace")
        frames, loop_start = r.unpack("2H")
        aux = r.i16()
        if frames == 0 or frames > 10000:
            raise StadiumExportError(f"Invalid animation duration for {name}")
        for _ in range(bone_count):
            if not r.u8():
                continue
            for j in range(9):
                kind = r.u8()
                if kind not in (0, 1):
                    raise StadiumExportError("Unrecognized DSM3 animation track type")
                r.take((4 if j >= 6 else 2) * (1 if kind == 0 else frames))
        animations.append({"name": name, "frames": frames,
                           "loopStart": loop_start, "aux": aux})
    for _ in range(aux_count):
        frames, loop_start, channels = r.unpack("3H")
        for _ in range(channels):
            r.take(2 * r.u16())
    if r.offset != len(data):
        raise StadiumExportError(f"Unexpected {len(data) - r.offset} trailing DSM3 bytes")
    return {"species": species, "bones": bones, "primitives": prims,
            "textures": textures, "animations": animations,
            "contexts": dict(zip(CONTEXTS, contexts)),
            "moveAnimations": move_anim, "moveAux": move_aux,
            "rootScale": root_scale, "staticPose": static_pose,
            "height": height, "floor": floor, "radius": radius}


def _mul(a, b):
    return tuple(sum(a[3 * row + k] * b[3 * k + col] for k in range(3))
                 for row in range(3) for col in range(3))


def _mv(m, v):
    return tuple(sum(m[3 * row + k] * v[k] for k in range(3)) for row in range(3))


def _rotation(rx, ry, rz):
    """Stadium skeleton uses signed 16-bit XYZ Euler angles."""
    ax, ay, az = (v * math.pi / 32768.0 for v in (rx, ry, rz))
    sx, cx = math.sin(ax), math.cos(ax)
    sy, cy = math.sin(ay), math.cos(ay)
    sz, cz = math.sin(az), math.cos(az)
    return (
        cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz,
        cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz,
        -sy, sx * cy, cx * cy,
    )


def bind_matrices(bones: list[dict]) -> list[tuple]:
    """Return each bone's world position, pure rotation and inherited scale."""
    cache = {}
    visiting = set()
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

    def one(index: int):
        if index in cache:
            return cache[index]
        if index in visiting:
            raise StadiumExportError("Cyclic DSM3 bone hierarchy")
        visiting.add(index)
        b = bones[index]
        local_rot = _rotation(*b["r"])
        parent = b["parent"]
        if parent < 0:
            pos = tuple(float(v) for v in b["t"])
            rot = local_rot
            scale = b["s"]
        else:
            pp, pr, ps = one(parent)
            scaled_translation = tuple(b["t"][i] * ps[i] for i in range(3))
            translated = _mv(pr, scaled_translation)
            pos = tuple(pp[i] + translated[i] for i in range(3))
            rot = _mul(pr, local_rot)
            scale = tuple(ps[i] * b["s"][i] for i in range(3))
        visiting.remove(index)
        cache[index] = (pos, rot, scale)
        return cache[index]
    return [one(i) for i in range(len(bones))]


def png_rgba(w: int, h: int, rgba: bytes) -> bytes:
    rows = b"".join(b"\x00" + rgba[row * w * 4:(row + 1) * w * 4] for row in range(h))
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body +
                struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def export_glb(model: dict, target_height: float = 1.5) -> bytes:
    if not (math.isfinite(target_height) and 0.05 <= target_height <= 100):
        raise StadiumExportError("Requested model height must be 0.05 to 100 units")
    if model["height"] <= 0:
        raise StadiumExportError("Model lacks a valid bounding height")
    # Matches the source inspector's rootScale/height normalization.
    factor = (model["rootScale"] or 1.0) * target_height / model["height"]
    if not math.isfinite(factor) or factor <= 0:
        raise StadiumExportError("Invalid model scaling factor")
    transforms = bind_matrices(model["bones"])
    gltf = {"asset": {"version": "2.0", "generator": "poke-n64 Stadium DSM3 exporter"},
            "scene": 0, "scenes": [{"nodes": [0]}],
            "nodes": [{"name": f"pokemon_{model['species']:03d}", "mesh": 0,
                       "rotation": [0, 1, 0, 0]}],
            "meshes": [{"primitives": []}], "materials": [], "accessors": [],
            "bufferViews": [], "buffers": [], "images": [], "textures": [],
            "samplers": [{"magFilter": 9728, "minFilter": 9728, "wrapS": 10497, "wrapT": 10497}]}
    binary = bytearray()

    def view(data: bytes, target: int | None = None) -> int:
        while len(binary) % 4: binary.append(0)
        offset = len(binary)
        binary.extend(data)
        record = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            record["target"] = target
        gltf["bufferViews"].append(record)
        return len(gltf["bufferViews"]) - 1

    def accessor(data: bytes, code: int, count: int, kind: str,
                 target: int, minimum=None, maximum=None) -> int:
        record = {"bufferView": view(data, target), "componentType": code,
                  "count": count, "type": kind}
        if minimum is not None: record["min"] = minimum
        if maximum is not None: record["max"] = maximum
        gltf["accessors"].append(record)
        return len(gltf["accessors"]) - 1

    for w, h, raw in model["textures"]:
        buffer_view = view(png_rgba(w, h, raw))
        gltf["images"].append({"bufferView": buffer_view, "mimeType": "image/png"})
        gltf["textures"].append({"sampler": 0, "source": len(gltf["images"]) - 1})

    for pi, primitive in enumerate(model["primitives"]):
        pvalues, nvalues, uvalues = [], [], []
        for x, y, z, u, v, nx, ny, nz, bone_index in primitive["vertices"]:
            pos, rot, scale = transforms[bone_index]
            baked = _mv(rot, (x * scale[0], y * scale[1], z * scale[2]))
            pvalues.extend((pos[i] + baked[i]) * factor for i in range(3))
            norm = _mv(rot, (nx, ny, nz))
            length = math.sqrt(sum(v * v for v in norm))
            nvalues.extend(v / length for v in norm) if length else nvalues.extend((0, 1, 0))
            uvalues.extend((u, v))
        if not all(math.isfinite(v) for v in pvalues + nvalues + uvalues):
            raise StadiumExportError(f"Non-finite geometry in primitive {pi}")
        vcount = len(primitive["vertices"])
        positions = list(zip(*(iter(pvalues),) * 3))
        minimum = [min(row[i] for row in positions) for i in range(3)]
        maximum = [max(row[i] for row in positions) for i in range(3)]
        attributes = {
            "POSITION": accessor(struct.pack("<" + "f" * len(pvalues), *pvalues),
                                 5126, vcount, "VEC3", 34962, minimum, maximum),
            "NORMAL": accessor(struct.pack("<" + "f" * len(nvalues), *nvalues),
                               5126, vcount, "VEC3", 34962),
            "TEXCOORD_0": accessor(struct.pack("<" + "f" * len(uvalues), *uvalues),
                                  5126, vcount, "VEC2", 34962),
        }
        indices = primitive["indices"]
        index_accessor = accessor(struct.pack("<" + "H" * len(indices), *indices),
                                  5123, len(indices), "SCALAR", 34963)
        texture = primitive["texture"]
        material = {"name": f"stadium_prim_{pi:03d}",
                    "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0},
                    "doubleSided": not primitive["cull"],
                    "extras": {"stadiumAdditiveBlend": primitive["additive"],
                               "stadiumTextureAnimation": primitive["textureAnimation"]}}
        if 0 <= texture < len(gltf["textures"]):
            material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": texture}
        if primitive["additive"]: material["alphaMode"] = "BLEND"
        gltf["materials"].append(material)
        gltf["meshes"][0]["primitives"].append({
            "mode": 4, "attributes": attributes, "indices": index_accessor,
            "material": pi,
        })
    while len(binary) % 4: binary.append(0)
    gltf["buffers"] = [{"byteLength": len(binary)}]
    json_payload = json.dumps(gltf, separators=(",", ":"), ensure_ascii=True).encode()
    json_payload += b" " * ((-len(json_payload)) % 4)
    total = 12 + 8 + len(json_payload) + 8 + len(binary)
    return (struct.pack("<4sII", b"glTF", 2, total) +
            struct.pack("<I4s", len(json_payload), b"JSON") + json_payload +
            struct.pack("<I4s", len(binary), b"BIN\x00") + binary)


def normalize_rom(data: bytes) -> bytes:
    if len(data) < 0x40:
        raise StadiumExportError("ROM header is truncated")
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40": return data
    if magic == b"\x37\x80\x40\x12":
        result = bytearray(data)
        result[0::2], result[1::2] = data[1::2], data[0::2]
        return bytes(result)
    if magic == b"\x40\x12\x37\x80":
        result = bytearray(data)
        for i in range(4): result[i::4] = data[3-i::4]
        return bytes(result)
    raise StadiumExportError("Not an N64 ROM (.z64/.n64/.v64)")


def rom_details(path: Path) -> tuple[bytes, dict]:
    if path.stat().st_size > 128 * 1024 * 1024:
        raise StadiumExportError("ROM exceeds 128 MiB safety limit")
    data = normalize_rom(path.read_bytes())
    title = data[0x20:0x34].decode("ascii", "replace").strip("\x00 ")
    details = {"name": title, "revision": data[0x3f],
               "gameId": data[0x3c:0x3e].decode("ascii", "replace"),
               "normalizedMd5": hashlib.md5(data).hexdigest()}
    if "STADIUM" not in title.upper() or "STADIUM 2" in title.upper():
        raise StadiumExportError(f"Not a Pokémon Stadium 1 ROM: {title!r}")
    return data, details


def find_rom(directory: Path) -> Path:
    if not directory.is_dir():
        raise StadiumExportError(f"No roms directory: {directory}")
    matches = sorted(p for p in directory.iterdir() if p.is_file() and
                     p.suffix.lower() in {".z64", ".n64", ".v64"} and
                     "pokemon stadium" in p.name.lower() and
                     "stadium 2" not in p.name.lower())
    if not matches:
        raise StadiumExportError("No Pokémon Stadium ROM found. Set STADIUM_ROM=/path/to/your.z64")
    if len(matches) > 1:
        raise StadiumExportError("Multiple Stadium ROMs found. Set STADIUM_ROM to select one: " +
                                 ", ".join(p.name for p in matches))
    return matches[0]


def inspector_checkout(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], check=True)
        subprocess.run(["git", "remote", "add", "origin", INSPECTOR_URL], cwd=path, check=True)
        subprocess.run(["git", "fetch", "--depth", "1", "origin", INSPECTOR_REV], cwd=path, check=True)
        subprocess.run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=path, check=True)
    if not (path / ".git").is_dir():
        raise StadiumExportError(f"Not an inspector Git checkout: {path}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()
    if head != INSPECTOR_REV:
        raise StadiumExportError(f"Unexpected inspector revision {head}; expected {INSPECTOR_REV}")
    if not any((path / "dist/assets").glob("romWorker-*.js")) if (path / "dist/assets").exists() else True:
        subprocess.run(["npm", "ci"], cwd=path, check=True)
        subprocess.run(["npm", "run", "build"], cwd=path, check=True)


def extract_pack(rom_path: Path, species: int, output: Path) -> bytes:
    inspector_checkout(INSPECTOR)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["node", str(ROOT / "tools/stadium_extract.mjs"),
                    str(INSPECTOR), str(rom_path.resolve()),
                    str(species), str(output.resolve())], check=True)
    return output.read_bytes()


def save_export(model: dict, directory: Path, target_height: float, rom: dict | None) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    tag = f"{model['species']:03d}"
    glb_file = directory / f"stadium-{tag}.glb"
    report_file = directory / f"stadium-{tag}.json"
    glb_file.write_bytes(export_glb(model, target_height))
    report = {
        "species": model["species"], "sourceRom": rom,
        "bones": len(model["bones"]), "primitives": len(model["primitives"]),
        "vertices": sum(len(p["vertices"]) for p in model["primitives"]),
        "triangles": sum(len(p["indices"]) // 3 for p in model["primitives"]),
        "textures": [{"width": w, "height": h} for w, h, _ in model["textures"]],
        "animations": model["animations"], "contexts": model["contexts"],
        "moveAnimations": model["moveAnimations"],
        "staticPose": model["staticPose"],
        "exportedGlbType": "bind-pose rigid-baked mesh; NO animation clips or skin",
        "targetHeight": target_height,
    }
    report_file.write_text(json.dumps(report, indent=2) + "\n")
    return glb_file, report_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--rom", type=Path, help="User-supplied Stadium 1 ROM")
    group.add_argument("--pack", type=Path, help="Previously extracted DSM3/PVDZ pack")
    parser.add_argument("--roms-dir", type=Path, default=ROOT / "roms")
    parser.add_argument("--species", type=int, default=1, help="National Pokédex number 1-151")
    parser.add_argument("--output", type=Path, default=OUT_ROOT)
    parser.add_argument("--height", type=float, default=1.5, help="Blender model height in scene units")
    parser.add_argument("--inspect-only", action="store_true",
                        help="Print Stadium ROM fingerprint without installing extractor")
    args = parser.parse_args()
    try:
        if not 1 <= args.species <= 151:
            raise StadiumExportError("--species must be 1..151")
        rom_info = None
        if args.pack:
            model_bytes = args.pack.read_bytes()
        else:
            rom_path = args.rom or find_rom(args.roms_dir)
            rom_data, rom_info = rom_details(rom_path)
            print(f"Stadium ROM: {rom_info['name']} (Rev {rom_info['revision']})", flush=True)
            print(f"Normalized MD5: {rom_info['normalizedMd5']}", flush=True)
            if rom_info["normalizedMd5"] != US10_MD5:
                print("WARNING: Extractor was developed for Stadium US 1.0. " +
                      "This ROM revision is EXPERIMENTAL; output will be parsed and validated.",
                      file=sys.stderr, flush=True)
            if args.inspect_only:
                return
            if len(rom_data) < 0x920000 + 64:
                raise StadiumExportError("ROM too small to contain expected Stadium model archive")
            pack_path = args.output / f"{args.species:03d}" / "source.dsm"
            model_bytes = extract_pack(rom_path, args.species, pack_path)
        if args.inspect_only:
            raise StadiumExportError("--inspect-only requires an N64 Stadium ROM")
        model = read_dsm(model_bytes)
        if model["species"] != args.species:
            raise StadiumExportError(
                f"Extractor returned species {model['species']} instead of {args.species}")
        glb, report = save_export(model, args.output / f"{args.species:03d}", args.height, rom_info)
        print(f"Exported Stadium model: {glb}\nMetadata: {report}")
        print("Open the .glb in Blender; convert materials and export via Fast64 for OoT.")
        print("This is STATIC bind-pose geometry. Animations are indexed in metadata, not yet exported.")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Stadium export failed: {exc}\n")


if __name__ == "__main__":
    main()
