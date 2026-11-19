"""Original character geometry fits N64 buffers; stats count drawn limbs."""
import math
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import character_models as m


class CharacterModelTests(unittest.TestCase):
    def test_meshes_are_nondegenerate_with_s16_positions(self):
        meshes=[part for kind in range(8) for part in m.human(kind).values()]
        meshes += [m.pokemon(species) for species in (1,4,7,19)]
        for mesh in meshes:
            self.assertTrue(mesh.faces)
            for tri,color in mesh.faces:
                self.assertEqual(len(tri),3)
                self.assertTrue(all(math.isfinite(v) and abs(round(v*100))<=32767 for p in tri for v in p))
                self.assertTrue(all(0<=v<=255 for v in color))
                ab=[tri[1][i]-tri[0][i] for i in range(3)]
                ac=[tri[2][i]-tri[0][i] for i in range(3)]
                cross=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
                self.assertGreater(sum(v*v for v in cross),1e-10)

    def test_rsp_vertex_batches_and_actual_draw_budgets(self):
        stats=m.statistics()
        self.assertEqual(stats['humans']['Red'],490)
        self.assertTrue(all(n<600 for n in stats['humans'].values()))
        self.assertTrue(all(n<300 for n in stats['starters'].values()))
        src=m.source()
        counts=re.findall(r'gsSPVertex\([^,]+,\s*(\d+),',src)
        self.assertTrue(counts)
        self.assertTrue(all(int(n)<=32 for n in counts))
        self.assertIn('species==19 ? sMon19',src)
        self.assertIn('#include "sys_math.h"',src)
        self.assertEqual(src,m.source())


if __name__=='__main__': unittest.main()
