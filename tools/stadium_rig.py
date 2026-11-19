#!/usr/bin/env python3
"""Skinned glTF 2.0 export of locally extracted Pokémon Stadium DSM3 packs.

The DSM3 joint hierarchy, per-bone signed-16 angle tracks and 16.16 scale
tracks are preserved. The rendered mesh is transformed to the rest pose and
inverse-bind matrices make animation relative to that pose.

Exports the named Stadium idle and attack_default clips by default.
No Nintendo data is bundled here; the calling tool reads private DSM packs.
"""
from __future__ import annotations

import json
import math
import struct

from stadium_export import StadiumExportError, png_rgba, _rotation

FPS = 30.0
NONE = 0xFFFF


def _matrix_mult(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(sum(a[row * 4 + k] * b[k * 4 + col] for k in range(4))
                 for row in range(4) for col in range(4))


def _transform(m: tuple[float, ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(m[row * 4] * point[0] + m[row * 4 + 1] * point[1] +
                 m[row * 4 + 2] * point[2] + m[row * 4 + 3] for row in range(3))


def _compose(translation: tuple[float, ...], rotation: tuple[int, ...],
             scale: tuple[float, ...]) -> tuple[float, ...]:
    r = _rotation(*rotation)
    return (
        r[0] * scale[0], r[1] * scale[1], r[2] * scale[2], translation[0],
        r[3] * scale[0], r[4] * scale[1], r[5] * scale[2], translation[1],
        r[6] * scale[0], r[7] * scale[1], r[8] * scale[2], translation[2],
        0.0, 0.0, 0.0, 1.0,
    )


def _inverse_affine(m: tuple[float, ...]) -> tuple[float, ...]:
    a, b, c = m[0:3]
    d, e, f = m[4:7]
    g, h, i = m[8:11]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(determinant) or abs(determinant) < 1e-10:
        raise StadiumExportError("A Stadium joint has a singular rest-pose transform")
    q = 1.0 / determinant
    inv = (
        (e * i - f * h) * q, (c * h - b * i) * q, (b * f - c * e) * q,
        (f * g - d * i) * q, (a * i - c * g) * q, (c * d - a * f) * q,
        (d * h - e * g) * q, (b * g - a * h) * q, (a * e - b * d) * q,
    )
    tx, ty, tz = m[3], m[7], m[11]
    return (
        inv[0], inv[1], inv[2], -(inv[0] * tx + inv[1] * ty + inv[2] * tz),
        inv[3], inv[4], inv[5], -(inv[3] * tx + inv[4] * ty + inv[5] * tz),
        inv[6], inv[7], inv[8], -(inv[6] * tx + inv[7] * ty + inv[8] * tz),
        0.0, 0.0, 0.0, 1.0,
    )


def _column_major(m: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(m[row * 4 + col] for col in range(4) for row in range(4))


def _quat(angles: tuple[int | float, ...]) -> tuple[float, float, float, float]:
    x, y, z = (a * math.pi / 65536.0 for a in angles)
    sx, cx = math.sin(x), math.cos(x)
    sy, cy = math.sin(y), math.cos(y)
    sz, cz = math.sin(z), math.cos(z)
    # The source's matrixForBone uses Rz * Ry * Rx.
    result = (
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    )
    length = math.sqrt(sum(q * q for q in result))
    return tuple(v / length for v in result)


def _ensure_floats(values: list | tuple, label: str):
    if not all(math.isfinite(float(v)) for v in values):
        raise StadiumExportError(f"Invalid floating-point {label}")


def _bone_global_matrices(bones: list[dict], factor: float) -> list[tuple[float, ...]]:
    cache: dict[int, tuple[float, ...]] = {}
    visiting: set[int] = set()

    def resolve(index: int):
        if index in cache:
            return cache[index]
        if index in visiting:
            raise StadiumExportError("Cyclic Stadium skeleton")
        visiting.add(index)
        bone = bones[index]
        translation = tuple(float(v) * factor for v in bone["t"])
        local = _compose(translation, bone["r"], bone["s"])
        parent = bone["parent"]
        m = _matrix_mult(resolve(parent), local) if parent >= 0 else local
        _ensure_floats(m, "bind matrix")
        cache[index] = m
        visiting.remove(index)
        return m

    return [resolve(i) for i in range(len(bones))]


def _clip_frames(components, rest, frames, offset: int, count: int, factor: float):
    out = []
    previous = None
    for frame in range(frames):
        group = []
        for j in range(count):
            if components is None:
                value = rest[offset + j]
            else:
                source = components[offset + j]
                value = source[frame] if isinstance(source, list) else source
            group.append(float(value))
        if count == 3 and offset == 0:
            group = [value * factor for value in group]
        elif count == 3 and offset == 3:
            group = list(_quat(tuple(group)))
            # Equivalent quaternions q and -q are not equivalent for linear
            # interpolation; stabilize their hemisphere across keyframes.
            if previous and sum(a * b for a, b in zip(group, previous)) < 0:
                group = [-v for v in group]
        _ensure_floats(group, "animation keyframe")
        out.extend(group)
        previous = group
    return out


def export_skinned_glb(model: dict, target_height: float = 1.5,
                       contexts: tuple[str, ...] = ("idle", "attack_default")) -> bytes:
    """Export a skinned, animated Blender-readable GLB using 30fps Stadium clips."""
    height = model["height"]
    factor = (model["rootScale"] or 1.0) * target_height / height if height > 0 else 0
    if not math.isfinite(factor) or factor <= 0:
        raise StadiumExportError("Invalid source height/rootScale for skin export")
    bones = model["bones"]
    if not (1 <= len(bones) <= 256):
        raise StadiumExportError("Unsupported number of Stadium bones")
    global_bind = _bone_global_matrices(bones, factor)

    root = {"name": f"pokemon_{model['species']:03d}",
            "rotation": [0.0, 1.0, 0.0, 0.0], "children": []}
    nodes = [root]
    for index, bone in enumerate(bones):
        node = {"name": f"bone_{index:03d}",
                "translation": [float(v) * factor for v in bone["t"]],
                "rotation": list(_quat(bone["r"])),
                "scale": list(bone["s"])}
        nodes.append(node)
    for index, bone in enumerate(bones):
        parent = bone["parent"]
        if parent == -1:
            root["children"].append(index + 1)
        else:
            nodes[parent + 1].setdefault("children", []).append(index + 1)
    if not any(bone["parent"] == -1 for bone in bones):
        raise StadiumExportError("Skeleton has no root joint")
    mesh_node = len(nodes)
    nodes.append({"name": f"pokemon_{model['species']:03d}_mesh", "mesh": 0, "skin": 0})
    root["children"].append(mesh_node)

    gltf = {
        "asset": {"version": "2.0", "generator": "poke-n64 Stadium skinned GLB exporter"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
        "meshes": [{"name": "Stadium model", "primitives": []}],
        "skins": [], "animations": [], "materials": [], "textures": [],
        "images": [], "samplers": [{"magFilter": 9728, "minFilter": 9728,
                                  "wrapS": 10497, "wrapT": 10497}],
        "accessors": [], "bufferViews": [], "buffers": [],
    }
    binary = bytearray()

    def make_view(contents: bytes, target=None) -> int:
        binary.extend(b"\0" * ((-len(binary)) % 4))
        offset = len(binary)
        binary.extend(contents)
        item = {"buffer": 0, "byteOffset": offset, "byteLength": len(contents)}
        if target is not None: item["target"] = target
        gltf["bufferViews"].append(item)
        return len(gltf["bufferViews"]) - 1

    def add_accessor(values: list | tuple, component: int, count: int,
                     name: str, target=None, bounds=False) -> int:
        kind = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[name]
        assert len(values) == count * kind
        fmt = "H" if component == 5123 else "f"
        if component not in (5123, 5126):
            raise StadiumExportError("Unsupported glTF accessor component type")
        if component == 5123 and any(not (0 <= v <= 65535) for v in values):
            raise StadiumExportError("Joint or index exceeds 16-bit glTF limit")
        if component == 5126:
            _ensure_floats(values, "glTF accessor")
        contents = struct.pack("<" + fmt * len(values), *values)
        rec = {"bufferView": make_view(contents, target), "componentType": component,
               "count": count, "type": name}
        if bounds:
            rec["min"] = [min(values[i::kind]) for i in range(kind)]
            rec["max"] = [max(values[i::kind]) for i in range(kind)]
        gltf["accessors"].append(rec)
        return len(gltf["accessors"]) - 1

    for w, h, rgba in model["textures"]:
        gltf["images"].append({"bufferView": make_view(png_rgba(w, h, rgba)),
                                "mimeType": "image/png"})
        gltf["textures"].append({"source": len(gltf["images"]) - 1, "sampler": 0})

    matrices = []
    for matrix in global_bind:
        matrices.extend(_column_major(_inverse_affine(matrix)))
    inverse_bind_accessor = add_accessor(matrices, 5126, len(bones), "MAT4")
    gltf["skins"].append({"joints": [i + 1 for i in range(len(bones))],
                           "inverseBindMatrices": inverse_bind_accessor,
                           "skeleton": 1 + next(i for i, b in enumerate(bones) if b["parent"] == -1)})

    for primitive_index, primitive in enumerate(model["primitives"]):
        verts = primitive["vertices"]
        pos_values, normal_values, uv_values, joint_values, weight_values = [], [], [], [], []
        for x, y, z, u, v, nx, ny, nz, bone_idx in verts:
            pos = _transform(global_bind[bone_idx], (x * factor, y * factor, z * factor))
            pos_values.extend(pos)
            # Source normals are stored in the joint's unscaled pivot space.
            # At rest glTF leaves these normals unchanged after skinning.
            rr = _rotation(*bones[bone_idx]["r"])
            norm = (rr[0] * nx + rr[1] * ny + rr[2] * nz,
                    rr[3] * nx + rr[4] * ny + rr[5] * nz,
                    rr[6] * nx + rr[7] * ny + rr[8] * nz)
            mag = math.sqrt(sum(x * x for x in norm))
            normal_values.extend([x / mag for x in norm] if mag > 0 else [0.0, 1.0, 0.0])
            uv_values.extend((u, v))
            joint_values.extend((bone_idx, 0, 0, 0))
            weight_values.extend((1.0, 0.0, 0.0, 0.0))
        count = len(verts)
        indices = primitive["indices"]
        attrs = {
            "POSITION": add_accessor(pos_values, 5126, count, "VEC3", 34962, bounds=True),
            "NORMAL": add_accessor(normal_values, 5126, count, "VEC3", 34962),
            "TEXCOORD_0": add_accessor(uv_values, 5126, count, "VEC2", 34962),
            "JOINTS_0": add_accessor(joint_values, 5123, count, "VEC4", 34962),
            "WEIGHTS_0": add_accessor(weight_values, 5126, count, "VEC4", 34962),
        }
        texture = primitive["texture"]
        material = {
            "name": f"stadium_{primitive_index:03d}",
            "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0},
            "doubleSided": not primitive["cull"],
            "extras": {"stadiumAdditiveBlend": primitive["additive"],
                       "stadiumTextureAnimation": primitive["textureAnimation"]},
        }
        if 0 <= texture < len(model["textures"]):
            material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": texture}
        if primitive["additive"]:
            material["alphaMode"] = "BLEND"
        gltf["materials"].append(material)
        gltf["meshes"][0]["primitives"].append({
            "attributes": attrs,
            "indices": add_accessor(indices, 5123, len(indices), "SCALAR", 34963),
            "material": primitive_index, "mode": 4,
        })

    for context_name in contexts:
        animation_index = model["contexts"].get(context_name, NONE)
        if not isinstance(animation_index, int) or animation_index == NONE:
            continue
        if animation_index < 0 or animation_index >= len(model["animations"]):
            raise StadiumExportError(f"Invalid {context_name} animation index")
        clip = model["animations"][animation_index]
        frames = clip["frames"]
        if frames > 900:
            raise StadiumExportError(f"Animation {context_name} has too many frames")
        sample_times = [index / FPS for index in range(frames)]
        time_accessor = add_accessor(sample_times, 5126, frames, "SCALAR", bounds=True)
        channels = []
        samplers = []
        tracks = clip["tracks"]
        for bone_index, bone in enumerate(bones):
            components = tracks[bone_index]
            if components is None:
                continue
            rest = tuple(bone["t"]) + tuple(bone["r"]) + tuple(bone["s"])
            for label, index, count in [("translation", 0, 3),
                                        ("rotation", 3, 4),
                                        ("scale", 6, 3)]:
                values = _clip_frames(components, rest, frames, index, count, factor)
                # Rotations read three signed-binang angles but generate
                # four-component glTF quaternions.
                output = add_accessor(values, 5126, frames,
                                      "VEC4" if label == "rotation" else "VEC3")
                samplers.append({"input": time_accessor, "output": output,
                                 "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1,
                                 "target": {"node": bone_index + 1, "path": label}})
        gltf["animations"].append({
            "name": f"{context_name}_{clip['name']}",
            "samplers": samplers, "channels": channels,
            "extras": {"stadiumContext": context_name, "frames": frames,
                       "fps": FPS, "loopStart": clip["loopStart"],
                       "sourceAnimationIndex": animation_index},
        })
    if not gltf["animations"]:
        raise StadiumExportError("DSM3 contains no usable idle or attack_default animation")

    binary.extend(b"\0" * ((-len(binary)) % 4))
    gltf["buffers"] = [{"byteLength": len(binary)}]
    j = json.dumps(gltf, separators=(",", ":"), ensure_ascii=True).encode()
    j += b" " * ((-len(j)) % 4)
    length = 12 + 8 + len(j) + 8 + len(binary)
    return (struct.pack("<4sII", b"glTF", 2, length) +
            struct.pack("<I4s", len(j), b"JSON") + j +
            struct.pack("<I4s", len(binary), b"BIN\0") + bytes(binary))
