"""Synthetic, copyright-free Stadium DSM to N64 asset-code regression tests."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
from test_stadium_rig import animated_model
from stadium_export import StadiumExportError
from stadium_n64 import emit_source, _batch_mesh, _tex16, MAX_TEXTURE_PIXELS


class StadiumNativeAssetTests(unittest.TestCase):
    def test_generates_f3dex3_asset_with_idle_attack_and_rgba16(self):
        source, stats = emit_source(animated_model(), height=110, max_frames=3)
        self.assertIn('void PokeStadium_DrawBulbasaur(', source)
        self.assertIn('static const Vtx sStadiumFrames0', source)
        self.assertIn('static const Vtx sStadiumFrames1', source)
        self.assertIn('gDPLoadTextureBlock(', source)
        self.assertIn('G_IM_SIZ_16b', source)
        self.assertIn('gSPVertex(', source)
        self.assertIn('gSP1Triangle(', source)
        self.assertIn('static const u16 sStadiumTexture0', source)
        self.assertEqual(stats['verticesPerFrame'], 3)
        self.assertEqual(stats['triangles'], 1)
        self.assertEqual(stats['frameCounts'], {'idle': 3, 'attack_default': 3})
        self.assertEqual(stats['textureCount'], 1)

    def test_unavailable_attack_is_not_faked(self):
        model = animated_model()
        model["contexts"]["attack_default"] = 65535
        with self.assertRaisesRegex(StadiumExportError, "attack_default"):
            emit_source(model)

    def test_model_is_one_species_and_animation_budget_is_bounded(self):
        model = animated_model()
        model['species'] = 25
        with self.assertRaisesRegex(StadiumExportError, "Bulbasaur"):
            emit_source(model)
        with self.assertRaises(StadiumExportError):
            emit_source(animated_model(), max_frames=50)

    def test_batch_splits_before_rsp_32_vertex_limit(self):
        model = animated_model()
        primitive = model['primitives'][0]
        primitive['vertices'] = [primitive['vertices'][i % 3] for i in range(36)]
        primitive['indices'] = list(range(36))
        batches, flat, tris = _batch_mesh(model)
        self.assertEqual(len(batches), 2)
        self.assertTrue(all(batch[2] <= 32 for batch in batches))
        self.assertEqual(len(tris), 12)
        self.assertEqual(len(flat), 36)

    def test_texture_fits_tmem_and_has_correct_opaque_bit(self):
        width, height = 128, 128
        rgba = (bytes([255, 0, 0, 255]) * (width * height))
        nw, nh, values = _tex16(width, height, rgba)
        self.assertLessEqual(nw * nh, MAX_TEXTURE_PIXELS)
        self.assertEqual(len(values), nw * nh)
        self.assertEqual(values[0], 0xF801)

    def test_private_output_is_never_committed(self):
        ignore = (ROOT / ".gitignore").read_text()
        self.assertIn('/assets/private/', ignore)


if __name__ == "__main__":
    unittest.main()
