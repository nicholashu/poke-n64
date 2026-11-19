#!/usr/bin/env python3
"""Convert a private Stadium DSM3 model to C source for native N64 F3DEX3.

This is a first-species battle-actor prototype. Animation is pre-baked from the
real Stadium skeleton to a bounded number of vertex frames, not evaluated on
the N64 CPU. Textures are nearest-neighbour downscaled to fit the N64's 4 KiB
TMEM limit (RGBA5551). The generated .c contains Nintendo-derived assets and
MUST stay under ignored assets/private/.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

from stadium_export import StadiumExportError, read_dsm
from stadium_rig import _bone_global_matrices, _transform

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "assets/private/stadium/001/source.dsm"
OUTPUT_PATH = ROOT / "assets/private/stadium/001/stadium_bulbasaur_n64.c"
MAX_VERTEX_PER_BATCH = 32
MAX_VERTICES_PER_FRAME = 12000
MAX_TEXTURE_PIXELS = 2048
MAX_FRAMES = 12
MAX_BAKED_VERTEX_BYTES = 1_310_720  # 1.25 MiB of vertex frames across two clips
MAX_TEXTURE_BYTES = 524_288
NONE = 65535


def _source_frames(model: dict, context: str, max_frames: int):
    number = model["contexts"].get(context, NONE)
    if not isinstance(number, int) or not 0 <= number < len(model["animations"]):
        raise StadiumExportError(f"No usable Stadium '{context}' animation")
    animation = model["animations"][number]
    length = animation["frames"]
    if not (1 <= length <= 900):
        raise StadiumExportError(f"Unexpected {context} animation length {length}")
    count = min(max_frames, length)
    indices = ([0] if count == 1 else
               [int(round(i * (length - 1) / (count - 1))) for i in range(count)])
    return animation, indices


def _pose_bones(model: dict, animation: dict, frame: int):
    result = []
    for bone, channel in zip(model["bones"], animation["tracks"]):
        if channel is None:
            result.append(bone)
            continue
        values = []
        for prop in channel:
            values.append(prop[frame] if isinstance(prop, list) else prop)
        result.append({
            "parent": bone["parent"],
            "t": values[0:3],
            "r": values[3:6],
            "s": values[6:9],
        })
    return result


def _batch_mesh(model: dict):
    """Greedy triangle batching, every batch uses <=32 vertices (N64 RSP limit)."""
    batches = []
    flat_vertices = []
    triangles = []
    for primitive_index, primitive in enumerate(model["primitives"]):
        mapping = {}
        unique = []
        faces = []

        def flush():
            nonlocal mapping, unique, faces
            if not faces:
                return
            start = len(flat_vertices)
            tri_start = len(triangles)
            flat_vertices.extend((primitive_index, index) for index in unique)
            triangles.extend(faces)
            batches.append((primitive_index, start, len(unique), tri_start, len(faces)))
            unique = []
            faces = []
            mapping = {}

        source = primitive["indices"]
        for at in range(0, len(source), 3):
            face = source[at:at+3]
            required = sum(index not in mapping for index in set(face))
            if len(unique) + required > MAX_VERTEX_PER_BATCH:
                flush()
            local_face = []
            for source_index in face:
                if source_index not in mapping:
                    mapping[source_index] = len(unique)
                    unique.append(source_index)
                local_face.append(mapping[source_index])
            faces.append(tuple(local_face))
        flush()
    if not batches or len(flat_vertices) > MAX_VERTICES_PER_FRAME:
        raise StadiumExportError(
            f"Mesh requires {len(flat_vertices)} batched vertices per frame; "
            f"limit is {MAX_VERTICES_PER_FRAME}"
        )
    return batches, flat_vertices, triangles


def _tex16(w: int, h: int, rgba: bytes):
    # Resize nearest neighbour, retaining power-of-two dimensions where present.
    # This first-pass importer preserves RGB and one-bit alpha (RGBA5551).
    target_w = w
    target_h = h
    while target_w * target_h > MAX_TEXTURE_PIXELS:
        if target_w >= target_h and target_w > 1:
            target_w = (target_w + 1) // 2
        elif target_h > 1:
            target_h = (target_h + 1) // 2
        else:
            raise StadiumExportError("Texture cannot fit into N64 TMEM")
    packed = []
    for y in range(target_h):
        source_y = min(h - 1, (y * h) // target_h)
        for x in range(target_w):
            source_x = min(w - 1, (x * w) // target_w)
            i = 4 * (source_y * w + source_x)
            r, g, b, a = rgba[i:i+4]
            packed.append(((r >> 3) << 11) | ((g >> 3) << 6) |
                          ((b >> 3) << 1) | (1 if a >= 128 else 0))
    return target_w, target_h, packed


def _primitive_texture(primitive: dict, texture_count: int) -> int:
    """Choose a valid texture, or preserve a geometry-only Stadium primitive.

    Real Stadium meshes contain untextured display-list primitives, commonly
    with a 0xFFFF texture index. Animated materials may have alternate valid
    textures in their map. Never discard polygons because no texture exists.
    """
    index = primitive["texture"]
    if 0 <= index < texture_count:
        return index
    for key in sorted(primitive.get("maps", {})):
        candidate = primitive["maps"][key]
        if 0 <= candidate < texture_count:
            return candidate
    return NONE


def _quantized_vertex(vertex, pose_matrices, factor: float, floor: float,
                      texture_dims: tuple[int, int], untextured: bool = False):
    x, y, z, u, v, nx, ny, nz, bone = vertex
    px, py, pz = _transform(pose_matrices[bone],
                             (x * factor, y * factor, z * factor))
    py -= floor * factor
    if not all(math.isfinite(a) and -32768 <= a <= 32767 for a in (px, py, pz)):
        raise StadiumExportError("Model vertex outside signed 16-bit N64 coordinate range")
    width, height = texture_dims
    # Untextured geometry can carry arbitrary unused UV coordinates.
    s = 0 if untextured else int(round(u * width * 32))
    t = 0 if untextured else int(round(v * height * 32))
    if not -32768 <= s <= 32767 or not -32768 <= t <= 32767:
        raise StadiumExportError("Model texture coordinates exceed signed 16-bit N64 range")
    # RSP uses RGB vertex shading. Keep side and bottom faces legible with a
    # modest diffuse factor; this does not reproduce Stadium's full lighting.
    shade = max(120, min(255, int(210 + 45 * ny)))
    return (round(px), round(py), round(pz), s, t, shade)


def emit_source(model: dict, height: float = 110.0, max_frames: int = MAX_FRAMES):
    if model["species"] != 1:
        raise StadiumExportError("First native actor only supports Bulbasaur (#001)")
    if not (10 <= height <= 1000 and 1 <= max_frames <= 24):
        raise StadiumExportError("Invalid N64 height/frame budget")
    if model["height"] <= 0:
        raise StadiumExportError("Model requires valid Stadium dimensions")

    factor = (model["rootScale"] or 1.0) * height / model["height"]
    batches, flat_vertices, faces = _batch_mesh(model)
    tex = [_tex16(*t) for t in model["textures"]]
    textures_for_primitive = [
        _primitive_texture(primitive, len(tex)) for primitive in model["primitives"]
    ]
    untextured_count = sum(index == NONE for index in textures_for_primitive)
    count = len(flat_vertices)
    total_texture_bytes = sum(len(pixels) * 2 for _, _, pixels in tex)
    if total_texture_bytes > MAX_TEXTURE_BYTES:
        raise StadiumExportError(
            f"Textures require {total_texture_bytes} bytes; N64 budget is {MAX_TEXTURE_BYTES}"
        )
    # Resident OoT code, graphics buffers and Zelda scene assets also need RAM.
    # Keep Bulbasaur's two baked clips within a predictable 1.25 MiB budget.
    budget_frames = MAX_BAKED_VERTEX_BYTES // (count * 16 * 2)
    if budget_frames < 2:
        raise StadiumExportError(
            "Model geometry is too large for two animated clips; simplify it first"
        )
    sample_limit = min(max_frames, budget_frames)
    per_clip = []
    for clip_name in ("idle", "attack_default"):
        animation, sample_indices = _source_frames(model, clip_name, sample_limit)
        frames = []
        for sampled in sample_indices:
            matrices = _bone_global_matrices(_pose_bones(model, animation, sampled), factor)
            verts = []
            for primitive_index, vertex_index in flat_vertices:
                primitive = model["primitives"][primitive_index]
                texture_id = textures_for_primitive[primitive_index]
                texture_dims = ((1, 1) if texture_id == NONE else
                                (tex[texture_id][0], tex[texture_id][1]))
                verts.append(_quantized_vertex(
                    primitive["vertices"][vertex_index], matrices, factor,
                    model["floor"], texture_dims, untextured=texture_id == NONE))
            frames.append(verts)
        per_clip.append((clip_name, frames, sample_indices))

    def vtx_initializer(v):
        x, y, z, s, t, shade = v
        return ("{ .v = { .ob = {" + f"{x}, {y}, {z}" + "}, .flag = 0,"
                + " .tc = {" + f"{s}, {t}" + "}, .cn = {" +
                f"{shade}, {shade}, {shade}, 255" + "} } }")

    parts = [
        "/* GENERATED FROM THE USER'S LOCAL STADIUM ROM: DO NOT COMMIT OR REDISTRIBUTE. */",
        "#include \"stadium_asset.h\"",
        "#include \"gfx.h\"",
        "#include \"ultra64.h\"",
        "",
        f"#define STADIUM_BULBA_VERTS {count}",
    ]
    for ci, (label, frames, samples) in enumerate(per_clip):
        parts.extend([
            f"#define STADIUM_FRAMES_{ci} {len(frames)}",
            f"/* {label}; sampled source frames: {', '.join(map(str, samples))} */",
            f"static const Vtx sStadiumFrames{ci}[STADIUM_FRAMES_{ci}][STADIUM_BULBA_VERTS] __attribute__((aligned(16))) = {{",
        ])
        for frame in frames:
            parts.append("    {")
            for vertex in frame:
                parts.append("        " + vtx_initializer(vertex) + ",")
            parts.append("    },")
        parts.append("};")
        parts.append("")

    for i, (w, h, pixels) in enumerate(tex):
        parts.append(f"static const u16 sStadiumTexture{i}[{len(pixels)}] __attribute__((aligned(8))) = {{")
        for j in range(0, len(pixels), 12):
            parts.append("    " + ", ".join(f"0x{v:04X}" for v in pixels[j:j+12]) + ",")
        parts.append("};")

    parts.extend([
        "typedef struct { u16 texture; u16 first; u8 vertices; u16 faceStart; u16 faceCount; } StadiumBatch;",
        f"static const StadiumBatch sBatches[{len(batches)}] = {{",
    ])
    for primitive_index, first, verts, tri_start, tri_count in batches:
        texture = textures_for_primitive[primitive_index]
        parts.append(f"    {{ {texture}, {first}, {verts}, {tri_start}, {tri_count} }},")
    parts.append("};")
    parts.append(f"static const u8 sFaces[{len(faces)}][3] = {{")
    for a, b, c in faces:
        parts.append(f"    {{{a}, {b}, {c}}},")
    parts.append("};")
    parts.extend([
        "",
        "s32 PokeStadium_AssetAvailable(void) { return true; }",
        "void PokeStadium_DrawBulbasaur(GraphicsContext* gfx, s32 attack, u32 ticks) {",
        "    const Vtx* vtx;",
        "    s32 batch, face;",
        "    s32 currentTexture = -1;",
        "    if (attack) {",
        "        u32 frame = (ticks / 2) % STADIUM_FRAMES_1;",
        "        vtx = sStadiumFrames1[frame];",
        "    } else {",
        "        u32 frame = (ticks / 3) % STADIUM_FRAMES_0;",
        "        vtx = sStadiumFrames0[frame];",
        "    }",
        "    OPEN_DISPS(gfx);",
        "    gDPPipeSync(POLY_OPA_DISP++);",
        "    gSPClearGeometryMode(POLY_OPA_DISP++, G_LIGHTING | G_TEXTURE_GEN | G_TEXTURE_GEN_LINEAR | G_CULL_BOTH | G_FOG);",
        "    gSPSetGeometryMode(POLY_OPA_DISP++, G_SHADE | G_SHADING_SMOOTH | G_ZBUFFER);",
        "    gDPSetCycleType(POLY_OPA_DISP++, G_CYC_1CYCLE);",
        "    gDPSetCombineMode(POLY_OPA_DISP++, G_CC_MODULATERGBA, G_CC_MODULATERGBA);",
        "    gDPSetRenderMode(POLY_OPA_DISP++, G_RM_AA_ZB_OPA_SURF, G_RM_AA_ZB_OPA_SURF2);",
        "    gDPSetTextureLUT(POLY_OPA_DISP++, G_TT_NONE);",
        "    gSPTexture(POLY_OPA_DISP++, 0, 0, 0, G_TX_RENDERTILE, G_OFF);",
        f"    for (batch = 0; batch < {len(batches)}; batch++) {{",
        "        const StadiumBatch* b = &sBatches[batch];",
        "        if (currentTexture != b->texture) {",
        "            currentTexture = b->texture;",
        "            if (currentTexture == 65535) {",
        "                /* Geometry-only Stadium primitive; shade without texturing. */",
        "                gDPPipeSync(POLY_OPA_DISP++);",
        "                gSPTexture(POLY_OPA_DISP++, 0, 0, 0, G_TX_RENDERTILE, G_OFF);",
        "                gDPSetCombineMode(POLY_OPA_DISP++, G_CC_SHADE, G_CC_SHADE);",
        "            } else {",
        "                gDPPipeSync(POLY_OPA_DISP++);",
        "                gDPSetCombineMode(POLY_OPA_DISP++, G_CC_MODULATERGBA, G_CC_MODULATERGBA);",
        "                gSPTexture(POLY_OPA_DISP++, 0xFFFF, 0xFFFF, 0, G_TX_RENDERTILE, G_ON);",
        "                switch (currentTexture) {",
    ])
    for i, (w, h, _) in enumerate(tex):
        parts.extend([
            f"                case {i}:",
            "                    gDPLoadTextureBlock(POLY_OPA_DISP++, "
            f"sStadiumTexture{i}, G_IM_FMT_RGBA, G_IM_SIZ_16b, {w}, {h}, 0,",
            "                        G_TX_NOMIRROR | G_TX_WRAP, G_TX_NOMIRROR | G_TX_WRAP,",
            "                        G_TX_NOMASK, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOLOD);",
            "                    break;",
        ])
    parts.extend([
        "                    default: break;",
        "                }",
        "            }",
        "        }",
        "        gSPVertex(POLY_OPA_DISP++, vtx + b->first, b->vertices, 0);",
        "        for (face = b->faceStart; face + 1 < b->faceStart + b->faceCount; face += 2) {",
        "            gSP2Triangles(POLY_OPA_DISP++, sFaces[face][0], sFaces[face][1], sFaces[face][2], 0,",
        "                         sFaces[face+1][0], sFaces[face+1][1], sFaces[face+1][2], 0);",
        "        }",
        "        if (face < b->faceStart + b->faceCount) {",
        "            gSP1Triangle(POLY_OPA_DISP++, sFaces[face][0], sFaces[face][1], sFaces[face][2], 0);",
        "        }",
        "    }",
        "    gSPTexture(POLY_OPA_DISP++, 0, 0, 0, G_TX_RENDERTILE, G_OFF);",
        "    CLOSE_DISPS(gfx);",
        "}",
        "",
    ])
    return "\n".join(parts), {
        "species": 1, "verticesPerFrame": count, "batches": len(batches),
        "triangles": len(faces), "textureCount": len(tex),
        "untexturedPrimitives": untextured_count,
        "frameCounts": {label: len(frames) for label, frames, _ in per_clip},
        "sampleFrames": {label: samples for label, _, samples in per_clip},
        "bakedVertexBytes": count * 16 * sum(len(frames) for _, frames, _ in per_clip),
        "textureBytes": total_texture_bytes,
        "note": "private generated C, skeleton animation baked into per-frame N64 Vtx arrays",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=MODEL_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--height", type=float, default=110.0)
    parser.add_argument("--frames", type=int, default=MAX_FRAMES)
    args = parser.parse_args()
    try:
        model = read_dsm(args.pack.read_bytes())
        result, stats = emit_source(model, args.height, args.frames)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
        print(f"Generated private native N64 model: {args.output}")
        print(f"Frames: {stats['frameCounts']} | "
              f"Meshes: {stats['batches']} batches | "
              f"Triangles: {stats['triangles']} | "
              f"Untextured primitives: {stats['untexturedPrimitives']}")
        print("Next: make rom-oot-docker (build adapter picks up this asset automatically)")
    except (OSError, StadiumExportError) as e:
        sys.exit(f"Stadium native export failed: {e}")


if __name__ == "__main__":
    main()
