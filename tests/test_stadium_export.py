"""Regression tests for ROM-free Stadium DSM3/PVDZ to GLB export.

Builds a tiny *original synthetic* model. No Pokémon assets or ROM required.
"""
from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import stadium_export as stadium


def model_pack(species: int = 1) -> bytes:
    p = bytearray(b"DSM3")
    p.extend(struct.pack("<6H", species, 1, 1, 1, 1, 0))
    p.extend(struct.pack("<fBfff", 1.0, 0, 100.0, 0.0, 20.0))
    p.extend(struct.pack("<165H", *([65535] * 165)))
    p.extend(struct.pack("<165h", *([-1] * 165)))
    p.extend(struct.pack("<20H", *([0] + [65535] * 19)))
    p.extend(struct.pack("<h3h3h3i", -1, 0, 0, 0, 0, 0, 0, 65536, 65536, 65536))
    p.extend(struct.pack("<HBBhBHHH", 0, 1, 0, -1, 0, 0, 3, 3))
    for vert in [
        (0, 0, 0, 0, 0, 0, 127, 0, 0),
        (100, 0, 0, 512, 0, 0, 127, 0, 0),
        (0, 100, 0, 0, 512, 0, 127, 0, 0),
    ]:
        p.extend(struct.pack("<5h3bB", *vert))
    p.extend(struct.pack("<3H", 0, 1, 2))
    p.extend(struct.pack("<HHI", 1, 1, 4))
    p.extend(b"\xff\x33\x22\xff")
    p.extend(struct.pack("<B", 4))
    p.extend(b"idle")
    p.extend(struct.pack("<HHhB", 1, 0, -1, 0))
    return bytes(p)


def literal_lz4(data: bytes) -> bytes:
    # Legal literal-only LZ4 raw block.
    n = len(data)
    encoded = bytearray([min(n, 15) << 4])
    if n >= 15:
        extra = n - 15
        while extra >= 255:
            encoded.append(255)
            extra -= 255
        encoded.append(extra)
    encoded.extend(data)
    return b"PVDZ" + struct.pack("<II", n, n) + bytes(encoded)


class StadiumExporterTests(unittest.TestCase):
    def test_reads_static_mesh_textures_and_animation_metadata(self):
        m = stadium.read_dsm(model_pack())
        self.assertEqual(m["species"], 1)
        self.assertEqual(len(m["bones"]), 1)
        self.assertEqual(len(m["primitives"]), 1)
        self.assertEqual(len(m["textures"]), 1)
        self.assertEqual(m["animations"][0]["name"], "idle")
        self.assertEqual(m["contexts"]["idle"], 0)
        self.assertEqual(m["primitives"][0]["indices"], [0, 1, 2])

    def test_lz4_compressed_pack_is_equivalent(self):
        self.assertEqual(stadium.unpack_pack(literal_lz4(model_pack())), model_pack())
        self.assertEqual(stadium.read_dsm(literal_lz4(model_pack()))["species"], 1)

    def test_lz4_rejects_corrupt_and_unbounded_blocks(self):
        for value in [b"PVDZ" + struct.pack("<I", stadium.MAX_PACK + 1),
                      b"PVDZ" + struct.pack("<I", 20) + b"\x00\x00\x00",
                      b"garbage"]:
            with self.subTest(value=value[:8]):
                with self.assertRaises(stadium.StadiumExportError):
                    stadium.unpack_pack(value)

    def test_glb_has_one_textured_mesh_and_png(self):
        glb = stadium.export_glb(stadium.read_dsm(model_pack()))
        magic, version, size = struct.unpack_from("<4sII", glb)
        self.assertEqual(magic, b"glTF")
        self.assertEqual(version, 2)
        self.assertEqual(size, len(glb))
        json_size, chunk = struct.unpack_from("<I4s", glb, 12)
        self.assertEqual(chunk, b"JSON")
        doc = json.loads(glb[20:20 + json_size])
        self.assertEqual(len(doc["meshes"][0]["primitives"]), 1)
        self.assertEqual(len(doc["textures"]), 1)
        self.assertEqual(len(doc["images"]), 1)
        self.assertEqual(doc["materials"][0]["doubleSided"], False)
        self.assertEqual(doc["nodes"][0]["rotation"], [0, 1, 0, 0])
        self.assertEqual(doc["accessors"][0]["count"], 3)
        self.assertEqual(doc["accessors"][3]["count"], 3)
        self.assertEqual(doc["buffers"][0]["byteLength"] % 4, 0)

    def test_output_is_private_and_contains_no_original_rom(self):
        with tempfile.TemporaryDirectory() as td:
            m = stadium.read_dsm(model_pack())
            glb, report = stadium.save_export(m, Path(td), 1.5,
                                               {"normalizedMd5": "synthetic"})
            self.assertTrue(glb.is_file())
            self.assertTrue(report.is_file())
            metadata = json.loads(report.read_text())
            self.assertEqual(metadata["species"], 1)
            self.assertEqual(metadata["triangles"], 1)
            self.assertIn("NO animation", metadata["exportedGlbType"])
            self.assertEqual(len(list(Path(td).iterdir())), 2)

    def test_dsm_rejects_invalid_species_indices_or_truncation(self):
        invalid = bytearray(model_pack())
        invalid[4:6] = struct.pack("<H", 250)
        with self.assertRaises(stadium.StadiumExportError):
            stadium.read_dsm(invalid)
        with self.assertRaises(stadium.StadiumExportError):
            stadium.read_dsm(model_pack()[:-10])
        invalid = bytearray(model_pack())
        # Primitive has an invalid vertex skin index.
        # Locate the first vertex by searching the unique three-vertex header.
        needle = struct.pack("<HBBhBHHH", 0, 1, 0, -1, 0, 0, 3, 3)
        first_vertex = bytes(invalid).index(needle) + len(needle)
        invalid[first_vertex + 13] = 8
        with self.assertRaisesRegex(stadium.StadiumExportError, "missing bone"):
            stadium.read_dsm(invalid)

    def test_rom_revision_is_reported_and_not_mistaken_for_us10(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "Pokemon Stadium (USA) (Rev 2).z64"
            header = bytearray(0x1000)
            header[0:4] = b"\x80\x37\x12\x40"
            header[0x20:0x20 + len("POKEMON STADIUM")] = b"POKEMON STADIUM"
            header[0x3f] = 2
            p.write_bytes(header)
            data, details = stadium.rom_details(p)
            self.assertEqual(data, bytes(header))
            self.assertEqual(details["revision"], 2)
            self.assertNotEqual(details["normalizedMd5"], stadium.US10_MD5)

    def test_bone_cycle_rejected(self):
        bones = [
            {"parent": 1, "t": (0, 0, 0), "r": (0, 0, 0), "s": (1, 1, 1)},
            {"parent": 0, "t": (0, 0, 0), "r": (0, 0, 0), "s": (1, 1, 1)},
        ]
        with self.assertRaisesRegex(stadium.StadiumExportError, "Cyclic"):
            stadium.bind_matrices(bones)


if __name__ == "__main__":
    unittest.main()
