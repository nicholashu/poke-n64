"""Game Boy cell fidelity, native collision and segment-layout regressions."""
from collections import Counter
import hashlib
import math
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pallet_town
from kanto_layout import CELL, ORDER, ROOMS, bounds, point, walkable

# SHA256 of newline-joined passability rows independently compared to the
# pinned pret/pokered ba9c0568 map/block/collision data. No graphic data here.
REFERENCE = {
    "PalletTown": (20,18,221,"f2f9abbb9627f161fdee4eeeb18becc0246e00449c120bf7ada9e36ab0f164fe"),
    "RedsHouse2F": (8,8,47,"7337f62f6ac346bfb2b1a0dc0d940a9b99eff173c12fe9ddb84902b2451ec871"),
    "RedsHouse1F": (8,8,49,"3a7e74762331d4e651fe618a990b89a937cf6730b6628dd3dc475def72e37cbd"),
    "BluesHouse": (8,8,45,"3e8ed24aec90ed5a282fbc3ee4c7e8ed43ddcf90f75229fc85296a20f79bb5ff"),
    "OaksLab": (10,12,83,"12a7f75110107f606cb07c839e502150d306a7f0e9cabb82d72823caa467b69c"),
}


class PalletTownTests(unittest.TestCase):
    def test_all_five_maps_match_pinned_reference_cell_for_cell(self):
        for name,(w,h,count,digest) in REFERENCE.items():
            with self.subTest(room=name):
                rows=ROOMS[name]["static_walkable_rows"]
                self.assertEqual(ROOMS[name]["dimensions"],[w,h])
                self.assertEqual(sum(r.count('.') for r in rows),count)
                self.assertEqual(hashlib.sha256('\n'.join(rows).encode()).hexdigest(),digest)

    def test_original_landmark_coordinates_and_passable_details(self):
        town=ROOMS['PalletTown']
        self.assertEqual([b['door'] for b in town['buildings']],[[5,5],[13,5],[12,11]])
        self.assertEqual([s['at'] for s in town['signs']],[[3,5],[11,5],[7,9],[13,13]])
        self.assertEqual([(b['x'],b['y'],b['width'],b['height']) for b in town['buildings']],
                         [(4,3,4,3),(12,3,4,3),(10,8,6,4)])
        for x1,z1,x2,z2 in [(4,10,7,11),(10,14,13,15)]:
            for z in range(z1,z2+1):
                for x in range(x1,x2+1): self.assertTrue(walkable('PalletTown',x,z))
        for z in range(14,18):
            for x in range(4,8): self.assertFalse(walkable('PalletTown',x,z))
        for x in (2,5):
            for z in (4,5): self.assertTrue(walkable('RedsHouse1F',x,z))
        self.assertEqual(pallet_town.TREES,())

    def test_collision_has_floor_only_on_original_walkable_cells(self):
        for name in ORDER:
            with self.subTest(room=name):
                geom=pallet_town.Geometry().make(name)
                vertices,polys=pallet_town._collision_data(geom)
                left,north,_,_=bounds(name)
                floors=Counter()
                for ids,normal,_ in polys:
                    if normal!=(0,32767,0): continue
                    pts=[vertices[i] for i in ids]
                    self.assertTrue(all(p[1]==0 for p in pts))
                    x=math.floor((sum(p[0] for p in pts)/3-left)/CELL)
                    z=math.floor((sum(p[2] for p in pts)/3-north)/CELL)
                    floors[x,z]+=1
                w,h=ROOMS[name]['dimensions']
                expected={(x,z) for z in range(h) for x in range(w) if walkable(name,x,z)}
                self.assertEqual(set(floors),expected)
                self.assertTrue(all(count==2 for count in floors.values()))

    def test_collision_edges_face_into_walkable_cells_and_leave_corridors_open(self):
        for name in ORDER:
            geom=pallet_town.Geometry().make(name)
            vertices,polys=pallet_town._collision_data(geom)
            left,north,_,_=bounds(name)
            walls=[(ids,n) for ids,n,_ in polys if n[1]==0]
            self.assertEqual(len(walls),2*len(geom.blocking_edges))
            self.assertEqual(len(geom.blocking_edges),len(set(geom.blocking_edges)))
            for ids,n in walls:
                pts=[vertices[i] for i in ids]
                # Just inside the face must be walkable; just outside must not.
                cx=sum(p[0] for p in pts)/3; cz=sum(p[2] for p in pts)/3
                inside=(math.floor((cx+n[0]/32767-left)/CELL),math.floor((cz+n[2]/32767-north)/CELL))
                outside=(math.floor((cx-n[0]/32767-left)/CELL),math.floor((cz-n[2]/32767-north)/CELL))
                self.assertTrue(walkable(name,*inside),(name,inside))
                self.assertFalse(walkable(name,*outside),(name,outside))

    def test_rsp_and_collision_limits_all_rooms(self):
        for name in ORDER:
            geom=pallet_town.Geometry().make(name)
            vertices,polys=pallet_town._collision_data(geom)
            self.assertLess(len(vertices),8192)
            for ids,normal,distance in polys:
                self.assertTrue(all(0<=i<len(vertices) for i in ids))
                self.assertTrue(all(-32767<=v<=32767 for v in normal))
                self.assertTrue(-32768<=distance<=32767)
            for tri,_ in geom.faces:
                self.assertTrue(all(-32768<=v<=32767 for p in tri for v in p))
            source=pallet_town.room_source(geom)
            counts=re.findall(r'gsSPVertex\([^,]+,\s*(\d+),',source)
            self.assertTrue(counts)
            self.assertTrue(all(int(n)<=32 for n in counts))
            self.assertLess(len(geom.faces),6500 if name=='PalletTown' else 3000)

    def test_all_scene_and_room_headers_are_separate_first_objects(self):
        for name in ORDER:
            scene_header,scene,room_header,room,meta=pallet_town.build_segments(name)
            prefix='gPallet' if name=='PalletTown' else 'g'+name
            for header,body,suffix in ((scene_header,scene,'SceneHeader'),(room_header,room,'RoomHeader')):
                self.assertEqual(header.count(f'SceneCmd {prefix}{suffix}[] ='),1)
                self.assertNotIn(f'SceneCmd {prefix}{suffix}[] =',body)
                self.assertIn('SCENE_CMD_END()',header)
            self.assertLess(scene_header.index('SCENE_CMD_SPAWN_LIST'),scene_header.index('SCENE_CMD_PLAYER_ENTRY_LIST'))
            self.assertIn('PLAYER_START_MODE_IDLE',scene)
            self.assertIn('SCENE_CMD_COL_HEADER',scene_header)
            self.assertIn('SCENE_CMD_ROOM_SHAPE',room_header)
            self.assertIn('G_CC_SHADE',room)
            self.assertEqual(meta['spawn'],point(name,*ROOMS[name]['spawns'][0][:2]))
            if name=='PalletTown':
                self.assertEqual(scene.count('CutsceneData gKokiriForest'),2)
            else:
                self.assertNotIn('gKokiriForest',scene)
                self.assertIn('_'+ROOMS[name]['segment']+'_room_0SegmentRomStart',scene)
            self.assertNotIn('spot04_scene_000',scene+room)

    def test_wake_spawn_does_not_replace_reference_metadata(self):
        room=ROOMS['RedsHouse2F']
        self.assertEqual(room['new_game_spawn'],[3,6])
        self.assertEqual(room['spawns'][0],[1,6,180])
        self.assertTrue(walkable('RedsHouse2F',1,6))
        self.assertFalse(walkable('RedsHouse2F',0,6))

    def test_header_split_rejects_absent_or_duplicate_headers(self):
        for source in ('int a=0;','SceneCmd x[] = {};\nSceneCmd x[] = {};'):
            with self.assertRaisesRegex(ValueError,'Expected one'):
                pallet_town.split_segment_header(source,'x')

    def test_legacy_dma_slots_are_self_contained_and_deterministic(self):
        for i in (1,2):
            source=pallet_town.unused_room_source(i)
            self.assertIn(f'gPalletEmptyRoom{i}Header',source)
            self.assertIn('ROOM_SHAPE_TYPE_NORMAL, 0, NULL, NULL',source)
            self.assertNotIn('spot04_scene_',source)
        with self.assertRaises(ValueError): pallet_town.unused_room_source(0)
        self.assertEqual(pallet_town.build('OaksLab'),pallet_town.build('OaksLab'))


if __name__=='__main__': unittest.main()
