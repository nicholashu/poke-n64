"""End-to-end importer checks using a deliberately fictional binary map."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import gen1_rom
import pallet_rom
import pallet_town
from test_gen1_rom import synthetic_rom, offset, checksums


def imported_fixture() -> bytes:
    """Create invented houses and terrain at coordinates unlike retail Pallet.

    All block/warp/text bytes are synthesized here, not copied from a game.
    The fixture traverses the real banked extractor and native scene emitter.
    """
    raw=synthetic_rom()
    cells=[[0x23]*20 for _ in range(18)]
    for y in range(18):
        cells[y][0]=cells[y][-1]=0x3a
    for x in range(20):
        cells[0][x]=cells[-1][x]=0x3a
    cells[0][9]=cells[1][9]=0x52
    for x1,y1,x2,y2,doorx in ((2,2,5,4,3),(13,3,17,6,15)):
        for y in range(y1,y2+1):
            for x in range(x1,x2+1):
                cells[y][x]=0x17
        cells[y2][doorx]=0x1b
    for x in range(5,9):
        cells[8][x]=0x56
    cells[12][4]=0x14
    cells[12][5]=0x55
    cells[13][4]=0x2c
    cells[13][5]=0x39
    # Build a unique blockset by grouping FOUR walking cells, each containing
    # four tiles. This exercises all quadrants and changes the real ROM bytes.
    signatures={}
    blocks=[]
    for by in range(9):
        for bx in range(10):
            block=[]
            for tiley in range(4):
                for tilex in range(4):
                    block.append(cells[by*2+tiley//2][bx*2+tilex//2])
            key=bytes(block)
            if key not in signatures:
                signatures[key]=len(signatures)
            blocks.append(signatures[key])
    for block,index in signatures.items():
        pos=offset(0x19,0x45e0)+index*16
        raw[pos:pos+16]=block
    pos=offset(6,0x42fd)
    raw[pos:pos+90]=bytes(blocks)
    raw[0x1735:0x1735+5]=bytes((0x23,0x1b,0x52,0x39,0xff))
    # The second invented warp now leads to the lab instead of last-map.
    raw[offset(6,0x6000)+9]=0x28
    # Keep the girl's initial cell on ground outside the invented house.
    raw[offset(6,0x6000)+1+1+8+1+12+1+6+2]=12
    checksums(raw)
    return bytes(raw)


def world_fixture() -> dict:
    return gen1_rom.parse_pallet(imported_fixture(),gen1_rom.PROFILES[0])


class SceneCompilerTests(unittest.TestCase):
    def test_actual_bytes_drive_houses_collision_and_warp_bindings(self):
        world=world_fixture()
        result=pallet_rom.compile_world(world)
        info=result['metadata']
        self.assertEqual(info['dimensions_cells'],[20,18])
        self.assertEqual([b['door'] for b in info['buildings']],[[3,4],[15,6]])
        self.assertEqual(info['spawn_cell'],[3,5])
        self.assertEqual(info['spawn'],[-520,0,-280])
        self.assertEqual(info['bounds'],[-800,-720,800,720])
        self.assertIn('{ -800, -30, -720 }, { 800, 365, 720 }',result['scene'])
        self.assertIn('POKE_PALLET_TEXT_GIRL',result['data_source'])
        self.assertIn('.lab_warp_index = 1',result['data_source'])
        self.assertIn('"Oak\'s lab"',result['data_source'])
        self.assertFalse(info['coverage']['interiors'])

    def test_change_to_source_block_changes_real_geometry(self):
        raw=bytearray(imported_fixture())
        before=pallet_rom.compile_world(gen1_rom.parse_pallet(bytes(raw),gen1_rom.PROFILES[0]))
        # Replace an interior ground block with the already-existing outer
        # boundary block by changing one byte of the *ROM*, not a JSON field.
        pos=offset(6,0x42fd)
        raw[pos+65]=raw[pos]
        after=pallet_rom.compile_world(gen1_rom.parse_pallet(bytes(raw),gen1_rom.PROFILES[0]))
        self.assertNotEqual(before['world']['map']['cells'],after['world']['map']['cells'])
        self.assertNotEqual(before['room'],after['room'])
        self.assertNotEqual(before['scene'],after['scene'])
        self.assertLess(after['metadata']['walkable_cells'],before['metadata']['walkable_cells'])

    def test_header_first_segments_and_rsp_vertex_budget(self):
        result=pallet_rom.compile_world(world_fixture())
        for header,body,symbol in (('scene_header','scene','gPalletSceneHeader'),
                                   ('room_header','room','gPalletRoomHeader')):
            self.assertEqual(result[header].count(f'SceneCmd {symbol}[]'),1)
            self.assertNotIn(f'SceneCmd {symbol}[]',result[body])
        for count in re.findall(r'gsSPVertex\(gPalletVertices\d+, (\d+),',result['room']):
            self.assertLessEqual(int(count),32)
        self.assertLess(result['metadata']['triangles'],4096)
        self.assertIn('NA_BGM_DISABLED',result['scene_header'])

    def test_collision_walls_face_walkable_cell_and_doors_remain_accessible(self):
        world=world_fixture()
        geom,info=pallet_rom.make_geometry(world['map'])
        vertices,polygons=pallet_town._collision_data(geom)
        self.assertEqual(polygons[0][1],(0,32767,0))
        self.assertEqual(polygons[1][1],(0,32767,0))
        self.assertEqual(len(polygons),2+2*len(info['blocked_edges']))
        for index,(x,y,dx,dy) in enumerate(info['blocked_edges']):
            for _,normal,_ in polygons[2+index*2:4+index*2]:
                self.assertGreater(normal[0]*(-dx)+normal[2]*(-dy),0)
        for door in world['map']['warps']:
            self.assertNotIn([door['x'],door['y'],0,1],info['blocked_edges'])
        self.assertLess(len(vertices),8192)

    def test_unknown_tiles_bad_doors_and_bad_bounds_fail_explicitly(self):
        world=world_fixture()
        unknown=deepcopy(world)
        unknown['map']['cells'][10][10]['collision_tile']=0x7e
        with self.assertRaisesRegex(ValueError,'No original 3D rule'):
            pallet_rom.compile_world(unknown)
        blocked=deepcopy(world)
        blocked['map']['cells'][4][3]['walkable']=False
        with self.assertRaisesRegex(ValueError,'Door warp'):
            pallet_rom.compile_world(blocked)
        malformed=deepcopy(world)
        malformed['map']['width']=33
        with self.assertRaises(ValueError):
            pallet_rom.compile_world(malformed)
        short=deepcopy(world)
        short['map']['cells'][0].pop()
        with self.assertRaisesRegex(ValueError,'columns'):
            pallet_rom.compile_world(short)

    def test_nonrectangular_or_unbound_building_is_not_guessed(self):
        world=world_fixture()
        cell=world['map']['cells'][2][2]
        cell.update(collision_tile=0x23,tiles=[0x23]*4,walkable=True)
        with self.assertRaisesRegex(ValueError,'nonrectangular'):
            pallet_rom.compile_world(world)

    def test_generation_does_not_mutate_default_scene_or_world(self):
        default=pallet_town.build_segments()
        world=world_fixture()
        snapshot=deepcopy(world)
        a=pallet_rom.compile_world(world)
        b=pallet_rom.compile_world(world)
        self.assertEqual(a,b)
        self.assertEqual(world,snapshot)
        self.assertEqual(default,pallet_town.build_segments())

    def test_native_data_is_valid_portable_c_and_accepted_by_runtime(self):
        result=pallet_rom.compile_world(world_fixture())
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'data.c').write_text(result['data_source'])
            (directory/'check.c').write_text(
                '#include "poke_pallet_import.h"\n'
                'int main(void) { PokePalletState state; '
                'return !poke_pallet_init(&state, &gPokePalletMap); }\n')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',
                            '-I',str(ROOT/'include'),str(directory/'data.c'),
                            str(ROOT/'src/pallet_import.c'),str(directory/'check.c'),
                            '-o',str(directory/'check')],check=True,capture_output=True,text=True)
            subprocess.run([str(directory/'check')],check=True)


class ImportCommandTests(unittest.TestCase):
    def test_unknown_rom_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            rom=directory/'local.gb'; rom.write_bytes(imported_fixture())
            out=directory/'output'
            with patch.object(sys,'argv',['pallet_rom.py','--rom',str(rom),'--output',str(out)]):
                with self.assertRaisesRegex(gen1_rom.RomError,'Unsupported ROM SHA-1'):
                    pallet_rom.main()
            self.assertFalse(out.exists())

    def test_one_command_outputs_deterministic_bundle_and_check_writes_nothing(self):
        data=imported_fixture()
        profile=replace(gen1_rom.PROFILES[0],sha1=hashlib.sha1(data).hexdigest())
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            rom=directory/'source (test).gb';rom.write_bytes(data)
            out=directory/'output'
            argv=['pallet_rom.py','--rom',str(rom),'--output',str(out)]
            with patch.object(gen1_rom,'PROFILES',(profile,)),redirect_stdout(io.StringIO()):
                with patch.object(sys,'argv',argv+['--check']):
                    pallet_rom.main()
                self.assertFalse(out.exists())
                with patch.object(sys,'argv',argv):
                    pallet_rom.main()
                    mtimes={p.name:p.stat().st_mtime_ns for p in out.iterdir()}
                    pallet_rom.main()
                self.assertEqual(mtimes,{p.name:p.stat().st_mtime_ns for p in out.iterdir()})
            manifest=json.loads((out/'manifest.json').read_text())
            for name,digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),digest)
            self.assertEqual(rom.read_bytes(),data)
            self.assertIn('not emulator output',(out/'preview.svg').read_text())
            self.assertEqual(len(list(out.iterdir())),9)

    def test_bundle_refuses_output_symlink_before_replacing_other_files(self):
        result=pallet_rom.compile_world(world_fixture())
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            target=directory/'unrelated';target.write_text('keep')
            (directory/'report.json').symlink_to(target)
            with self.assertRaisesRegex(ValueError,'symlink'):
                pallet_rom.write_bundle(result,directory)
            self.assertEqual(target.read_text(),'keep')
            self.assertFalse((directory/'pallet.json').exists())


if __name__=='__main__':
    unittest.main()
