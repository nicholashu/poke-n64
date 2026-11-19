"""ROM-free, synthetic validation of Stadium skeletal animation GLB export."""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
from test_stadium_export import model_pack
from stadium_export import StadiumExportError, read_dsm
from stadium_rig import export_skinned_glb, _quat, _inverse_affine, _matrix_mult


def animated_model():
    model = read_dsm(model_pack())
    model["contexts"]["idle"] = 0
    model["contexts"]["attack_default"] = 1
    model["animations"] = [
        {
            "name": "idle", "frames": 3, "loopStart": 0, "aux": None,
            "tracks": [[
                [0, 0, 0], 0, 0,
                0, [0, 800, 0], 0,
                1.0, 1.0, 1.0,
            ]],
        },
        {
            "name": "attack", "frames": 3, "loopStart": 0, "aux": None,
            "tracks": [[
                [0, 10, 0], 0, 0,
                0, [0, 8192, 16384], 0,
                1.0, 1.0, 1.0,
            ]],
        },
    ]
    return model


def unpack_glb(blob: bytes):
    magic, version, size = struct.unpack_from("<4sII", blob)
    assert (magic, version, size) == (b"glTF", 2, len(blob))
    json_size, json_magic = struct.unpack_from("<I4s", blob, 12)
    assert json_magic == b"JSON"
    doc = json.loads(blob[20:20 + json_size])
    bin_start = 20 + json_size
    bin_len, bin_magic = struct.unpack_from("<I4s", blob, bin_start)
    assert bin_magic == b"BIN\0"
    return doc, blob[bin_start + 8:bin_start + 8 + bin_len]


def accessor(doc, binary: bytes, index: int):
    a = doc["accessors"][index]
    v = doc["bufferViews"][a["bufferView"]]
    component_size = 2 if a["componentType"] == 5123 else 4
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
    fmt = "H" if a["componentType"] == 5123 else "f"
    n = a["count"] * width
    start = v["byteOffset"] + a.get("byteOffset", 0)
    assert component_size * n <= v["byteLength"]
    return struct.unpack_from("<" + fmt * n, binary, start)


class StadiumRigTests(unittest.TestCase):
    def test_two_clips_skin_weights_inverse_bind_and_motion(self):
        doc, binary = unpack_glb(export_skinned_glb(animated_model()))
        self.assertEqual(len(doc["skins"]), 1)
        self.assertEqual(doc["skins"][0]["joints"], [1])
        self.assertEqual(len(doc["animations"]), 2)
        self.assertEqual([a["extras"]["stadiumContext"] for a in doc["animations"]],
                         ["idle", "attack_default"])
        self.assertEqual(doc["nodes"][0]["rotation"], [0.0, 1.0, 0.0, 0.0])
        mesh = doc["meshes"][0]["primitives"][0]
        positions = accessor(doc, binary, mesh["attributes"]["POSITION"])
        self.assertEqual(positions[3], 1.5)  # Source 100 units -> target height 1.5
        joints = accessor(doc, binary, mesh["attributes"]["JOINTS_0"])
        weights = accessor(doc, binary, mesh["attributes"]["WEIGHTS_0"])
        self.assertEqual(joints[:4], (0, 0, 0, 0))
        self.assertEqual(weights[:4], (1.0, 0.0, 0.0, 0.0))
        bind = accessor(doc, binary, doc["skins"][0]["inverseBindMatrices"])
        self.assertEqual(len(bind), 16)
        for clip in doc["animations"]:
            self.assertEqual(len(clip["channels"]), 3)
            self.assertEqual({c["target"]["path"] for c in clip["channels"]},
                             {"translation", "rotation", "scale"})
            for c in clip["channels"]:
                output = accessor(doc, binary, clip["samplers"][c["sampler"]]["output"])
                self.assertTrue(all(math.isfinite(x) for x in output))
            self.assertEqual(clip["extras"]["fps"], 30.0)

    def test_quaternion_matches_y_rotation_and_stays_normalized(self):
        q = _quat((0, 16384, 0))
        self.assertAlmostEqual(q[1], 0.70710678, places=5)
        self.assertAlmostEqual(q[3], 0.70710678, places=5)
        self.assertAlmostEqual(sum(x*x for x in q), 1.0, places=6)

    def test_inverse_bind_round_trip(self):
        m = (2, 0, 0, 12, 0, 3, 0, -5, 0, 0, 4, 8, 0, 0, 0, 1)
        identity = _matrix_mult(m, _inverse_affine(m))
        for row in range(4):
            for col in range(4):
                self.assertAlmostEqual(identity[row*4 + col],
                                       1 if row == col else 0, places=5)

    def test_missing_animations_and_singular_rest_matrix_are_explicit_errors(self):
        model = animated_model()
        model["contexts"]["idle"] = 65535
        model["contexts"]["attack_default"] = 65535
        with self.assertRaisesRegex(StadiumExportError, "no usable"):
            export_skinned_glb(model)
        model = animated_model()
        model["bones"][0]["s"] = (0.0, 1.0, 1.0)
        with self.assertRaisesRegex(StadiumExportError, "singular"):
            export_skinned_glb(model)

    def test_real_dsm_no_tracks_does_not_fake_animation(self):
        with self.assertRaisesRegex(StadiumExportError, "no usable"):
            export_skinned_glb(read_dsm(model_pack()))


if __name__ == "__main__":
    unittest.main()
