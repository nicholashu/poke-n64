"""Offline checks for the ROM observer and controller route planner.

These test protocol parsing and failure behavior, not N64 execution.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import opening_e2e as e
from kanto_layout import ORDER, ROOMS, walkable


def packet():
    data=bytearray(32)
    data[:5]=b'PK64\x01'
    data[5:16]=bytes([4,8,0,1,4,2,0,18,12,20,19])
    data[16:20]=bytes.fromhex('06e0 07d0')  # 5.5 and 6.25 cells, quarter units
    data[20:28]=bytes([0x12,0x34,0,1,3,1,0,0])
    data[28:]=zlib.crc32(data[:28]).to_bytes(4,'big')
    return bytes(data)


def image_packet(path,data,scale=1):
    from PIL import Image,ImageDraw
    img=Image.new('RGB',(320,240),(47,68,83)); draw=ImageDraw.Draw(img)
    draw.rectangle((246,4,313,71),fill=(0,255,255))
    for i in range(256):
        x,y=248+i%16*4,6+i//16*4
        v=255 if data[i//8] & (1<<(7-i%8)) else 0
        draw.rectangle((x,y,x+3,y+3),fill=(v,v,v))
    if scale!=1: img=img.resize((320*scale,240*scale),Image.Resampling.NEAREST)
    img.save(path)


class ProtocolTests(unittest.TestCase):
    def test_terminal_enemy_cleanup_cannot_pass_the_damage_assertion(self):
        initial=replace(e.decode_packet(packet()),hp=20,enemy_hp=19)
        self.assertFalse(e.observed_damage(initial,initial))
        self.assertTrue(e.observed_damage(initial,replace(initial,enemy_hp=16)))
        self.assertTrue(e.observed_damage(initial,replace(initial,hp=17)))
        terminal=replace(initial,stage=e.AFTER_BATTLE,trainer=False,enemy_hp=0,enemy_max_hp=0)
        self.assertFalse(e.observed_damage(initial,terminal))

    def test_decode_real_field_order_and_big_endian_coordinates(self):
        state=e.decode_packet(packet())
        self.assertEqual((state.room,state.stage,state.mode),(e.LAB,e.BATTLE,2))
        self.assertEqual((state.starter,state.rival),(1,4))
        self.assertEqual((state.x,state.z,state.frame),(5.5,6.25,0x1234))
        self.assertEqual(state.tile,(5,6))
        self.assertEqual((state.hp,state.enemy_hp,state.max_hp,state.enemy_max_hp),(18,12,20,19))
        self.assertTrue(state.trainer and state.locked)
        self.assertEqual(state.turns,3)

    def test_facing_bits_do_not_mark_a_warp_pending(self):
        data=bytearray(packet());data[26]=4
        data[28:]=zlib.crc32(data[:28]).to_bytes(4,'big')
        state=e.decode_packet(bytes(data))
        self.assertEqual(state.facing,2)
        self.assertFalse(state.warp)

    def test_corruption_or_unknown_protocol_never_passes(self):
        for field in (0,4,5,6,10,16,24,28,31):
            bad=bytearray(packet()); bad[field]^=0x80
            with self.assertRaises(e.TelemetryError): e.decode_packet(bytes(bad))
        with self.assertRaises(e.TelemetryError): e.decode_packet(packet()[:-1])
        bad=bytearray(packet()); bad[5]=9
        bad[28:]=zlib.crc32(bad[:28]).to_bytes(4,'big')
        with self.assertRaises(e.TelemetryError): e.decode_packet(bytes(bad))

    def test_pixel_decoder_native_and_scaled_with_crc_failure(self):
        try: from PIL import Image
        except ImportError: self.skipTest('Pillow unavailable')
        with tempfile.TemporaryDirectory() as work:
            path=Path(work)/'frame.png'
            for scale in (1,2,3):
                image_packet(path,packet(),scale)
                self.assertEqual(e.decode_image(path),e.decode_packet(packet()))
            image_packet(path,packet())
            img=Image.open(path).convert('RGB')
            # Corrupt a data bit without changing the magic or border.
            for dx in range(4):
                for dy in range(4): img.putpixel((248+dx,34+dy),(255,255,255))
            img.save(path)
            with self.assertRaises(e.TelemetryError): e.decode_image(path)
            image_packet(path,packet())
            self.assertFalse(e.world_view_visible(path))
            img=Image.open(path).convert('RGB')
            from PIL import ImageDraw
            ImageDraw.Draw(img).rectangle((40,80,100,110),fill=(185,52,44))
            img.save(path)
            self.assertTrue(e.world_view_visible(path))
            Image.new('RGB',(320,240),'black').save(path)
            with self.assertRaisesRegex(e.TelemetryError,'not visible'): e.decode_image(path)
            Image.new('RGB',(640,360),'white').save(path)
            with self.assertRaisesRegex(e.TelemetryError,'4:3'): e.decode_image(path)

    def test_stopped_frame_counter_fails_even_with_valid_crc(self):
        with tempfile.TemporaryDirectory() as work:
            run=e.OpeningRunner(Path(work)/'test.z64',Path(work),'bulbasaur')
            run.process=Mock();run.process.poll.return_value=None
            run.capture=Mock(return_value=Path(work)/'fake.png')
            run.last_state=e.decode_packet(packet()); run.last_advance=0
            with patch.object(e,'decode_image',return_value=run.last_state), patch.object(e.time,'monotonic',return_value=10):
                with self.assertRaisesRegex(AssertionError,'stopped advancing'): run.observe()

    def test_failed_playthrough_records_failure_and_closes_owned_session(self):
        with tempfile.TemporaryDirectory() as work:
            run=e.OpeningRunner(Path(work)/'test.z64',Path(work),'charmander')
            run.session.mkdir()
            run.play_opening=Mock(side_effect=AssertionError('wrong room'))
            run.close=Mock()
            self.assertFalse(run.run())
            run.close.assert_called_once()
            result=json.loads((run.session/'report.json').read_text())
            self.assertEqual(result['status'],'failed')
            self.assertFalse(result['checkpoints'][-1]['passed'])
            self.assertFalse(result['damage_observed'])


class ControllerRouteTests(unittest.TestCase):
    def test_complete_routes_all_starters(self):
        e.check_routes()
        for name,(_,_,x) in e.STARTERS.items():
            path=e.route(e.LAB,(5,3),(x,4),e.CHOOSE)
            self.assertEqual(path[-1],(x,4),name)
            self.assertNotIn((4,3),path)
            self.assertNotIn((5,2),path)

    def test_routes_avoid_npcs_and_unintended_warps(self):
        cases=[(e.PALLET,(5,6),(10,1)),(e.HOME,(6,1),(3,7)),(e.BLUE_HOUSE,(3,6),(2,4))]
        for room,start,goal in cases:
            path=e.route(room,start,goal,e.EXPLORE)
            excluded=e.occupied(room,e.EXPLORE)|{tuple(w['at']) for w in ROOMS[ORDER[room]]['warps']}
            excluded.discard(goal)
            self.assertFalse(set(path)&excluded)
            previous=start
            for cell in path:
                self.assertTrue(walkable(ORDER[room],*cell))
                self.assertEqual(abs(cell[0]-previous[0])+abs(cell[1]-previous[1]),1)
                previous=cell

    def test_unreachable_and_blocked_targets_fail(self):
        with self.assertRaisesRegex(ValueError,'Blocked'): e.route(e.PALLET,(5,6),(5,4),e.EXPLORE)
        with self.assertRaisesRegex(ValueError,'No controller route'): e.route(e.PALLET,(5,6),(0,0),e.EXPLORE)
        with self.assertRaisesRegex(ValueError,'NPC'): e.route(e.HOME,(6,1),(5,4),e.EXPLORE)

    def test_cardinal_commands_and_center_tolerance(self):
        state=replace(e.decode_packet(packet()),x=5.5,z=6.5)
        for goal,key in [((6,6),'right'),((4,6),'left'),((5,7),'down'),((5,5),'up')]:
            self.assertEqual(e.direction(state,goal),(key,1))
        self.assertEqual(e.direction(state,(5,6)),(None,0))

    def test_session_bindings_do_not_modify_global_config(self):
        with tempfile.TemporaryDirectory() as work:
            run=e.OpeningRunner(Path(work)/'test.z64',Path(work),'squirtle')
            cfg=run.config_overlay(60001,60002)
            self.assertIn('input_player1_up = "i"',cfg)
            self.assertIn('input_player1_b = "space"',cfg)
            self.assertIn('input_enable_hotkey = "f12"',cfg)
            self.assertIn('config_save_on_exit = "false"',cfg)
            self.assertIn(str(run.session/'saves'),cfg)
            self.assertFalse(run.session.exists())


if __name__=='__main__': unittest.main()
