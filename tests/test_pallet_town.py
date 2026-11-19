"""Original Pallet Town scene / collision generator tests. No ROM files needed."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pallet_town


class PalletTownTests(unittest.TestCase):
    def test_pallet_geometry_contains_major_landmarks(self):
        scene, room, info = pallet_town.build()
        self.assertEqual(info["landmarks"], [
            "Red's house", "Rival's house", "Professor Oak's laboratory"
        ])
        self.assertEqual(info["spawn"], (0, 0, 690))
        self.assertGreater(info["triangles"], 200)
        self.assertGreater(info["collisionPolygons"], 10)
        self.assertIn("SCENE_CMD_ROOM_LIST(1, gPalletRoomList)", scene)
        self.assertIn("SCENE_CMD_PLAYER_ENTRY_LIST(1, gPalletPlayerSpawns)", scene)
        self.assertIn("SCENE_CMD_COL_HEADER(&gPalletCollision)", scene)
        self.assertIn("CAM_SET_NORMAL0", scene)
        self.assertIn("OBJECT_GAMEPLAY_FIELD_KEEP", scene)
        self.assertIn("G_CC_SHADE", room)
        self.assertIn("ROOM_SHAPE_TYPE_NORMAL", room)
        self.assertIn("gsSPVertex", room)

    def test_ground_collision_is_walkable_and_bounds_are_complete(self):
        geom = pallet_town.Geometry().make()
        vertices, polygons = pallet_town._collision_data(geom)
        self.assertLess(len(vertices), 8192)
        floors = [(ids, normal) for ids, normal, _ in polygons if normal == (0,32767,0)]
        self.assertTrue(floors, "OoT must have walkable ground")
        corner_set = set(vertices)
        for corner in ((-1100,0,-1300),(-1100,0,1150),
                       (1100,0,-1300),(1100,0,1150)):
            self.assertIn(corner,corner_set)
        self.assertTrue(any(normal[0] != 0 for _,normal,_ in polygons))
        self.assertTrue(any(normal[2] != 0 for _,normal,_ in polygons))

    def test_rig_safe_vertex_buffers_and_collision_indices(self):
        geom = pallet_town.Geometry().make()
        vertices, polygons = pallet_town._collision_data(geom)
        for tri,normal,distance in polygons:
            self.assertEqual(len(tri),3)
            self.assertTrue(all(0<=i<len(vertices) for i in tri))
            self.assertTrue(all(-32767<=n<=32767 for n in normal))
            self.assertTrue(-32768<=distance<=32767)
        room = pallet_town.room_source(geom)
        # Every generated batch has at most 30 vertices, below RSP 32 limit.
        for line in room.splitlines():
            if "gsSPVertex(gPalletVertices" in line:
                count = int(line.split(",")[1].strip())
                self.assertLessEqual(count, 32)

    def test_scene_is_original_and_independent_of_kokiri_meshes(self):
        scene, room, _ = pallet_town.build()
        self.assertIn("_spot04_room_0SegmentRomStart", scene)
        self.assertNotIn("example_scene", scene+room)
        self.assertNotIn("gKokiriForest", scene+room)
        # Only the ROM slot keeps a legacy Zelda identifier. No forest
        # assets, actors or Kokiri geometry appear in the payload.
        self.assertNotIn("spot04_room_1", scene+room)
        self.assertNotIn("spot04_scenePathList", scene+room)

    def test_legacy_room_dma_slots_are_minimal_self_contained_rooms(self):
        for index in (1, 2):
            source = pallet_town.unused_room_source(index)
            self.assertIn(f"gPalletEmptyRoom{index}Header", source)
            self.assertIn("SCENE_CMD_ROOM_SHAPE", source)
            self.assertIn("SCENE_CMD_END()", source)
            self.assertIn("ROOM_SHAPE_TYPE_NORMAL, 0, NULL, NULL", source)
            self.assertNotIn("spot04_scene_", source)
        with self.assertRaises(ValueError):
            pallet_town.unused_room_source(0)

    def test_unreachable_kokiri_cutscene_link_symbols_use_empty_scripts(self):
        scene, _, _ = pallet_town.build()
        for symbol in ("gKokiriForestDekuSproutPart3Cs",
                       "gKokiriForestSariaGreetingCs"):
            self.assertIn(f"CutsceneData {symbol}[]", scene)
        self.assertEqual(scene.count("CS_HEADER(0, 1), CS_END_OF_SCRIPT()"), 2)

    def test_deterministic_generation(self):
        a=pallet_town.build()
        b=pallet_town.build()
        self.assertEqual(a,b)


if __name__ == "__main__":
    unittest.main()
