"""Finite speed test and optional bookcase/hand-item dispenser regression tests."""
import ast
from pathlib import Path
import re
import unittest
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
FNAMES={'build_coffee_pass_sequence','build_coffee_group_sequence',
        'build_extended_coffee_sequence','parse_extra_furniture_sources',
        'outgoing_furniture_id_from_packet','coffee_speed_test_report'}
FUNCTIONS=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in FNAMES]
namespace={'re':re}
exec(compile(ast.Module(body=FUNCTIONS,type_ignores=[]),str(SOURCE),'exec'),namespace)

parse=namespace['parse_extra_furniture_sources']
build=namespace['build_extended_coffee_sequence']
group=namespace['build_coffee_group_sequence']
report=namespace['coffee_speed_test_report']
capture=namespace['outgoing_furniture_id_from_packet']

class Packet:
    def __init__(self,ident=333):self.ident=ident
    def header_id(self):return 88
    def read_int(self,at):
        if at!=6:raise AssertionError(at)
        return self.ident

class ExtraSourceTests(unittest.TestCase):
    def test_extras_are_optional_numeric_unique_and_bounded(self):
        self.assertEqual(parse('',100,101),())
        self.assertEqual(parse(' 333,  444 ; 555 ',100,101),('333','444','555'))
        for raw in ('100','333,333','333, 101','0','foo','-5',
                    '2147483648','333,444,555,666,777'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse(raw,100,101)
        with self.assertRaises(ValueError):
            parse('333',100,100)

    def test_existing_two_cup_sequence_unmodified(self):
        a=build('100','101',(), '900')
        self.assertEqual(a,(
            '{out:UseFurniture}{i:100}{i:0}',
            '{out:PassCarryItem}{i:900}',
            '{out:UseFurniture}{i:101}{i:0}',
            '{out:PassCarryItem}{i:900}'))

    def test_bookcase_is_third_pickup_followed_by_pass(self):
        x=build('100','101',('333',),'900')
        self.assertEqual(len(x),6)
        self.assertEqual(x[4],'{out:UseFurniture}{i:333}{i:0}')
        self.assertEqual(x[5],'{out:PassCarryItem}{i:900}')
        self.assertEqual(build('100','101',('333',),'900',True),
                         x[:2])

    def test_three_sources_fair_group_rotation(self):
        target=(('A',900),('B',901))
        actions=group(100,101,target,('333',))
        self.assertEqual(len(actions),12)
        self.assertEqual([s for s in actions[::2]],[
            '{out:UseFurniture}{i:100}{i:0}',
            '{out:UseFurniture}{i:101}{i:0}',
            '{out:UseFurniture}{i:101}{i:0}',
            '{out:UseFurniture}{i:333}{i:0}',
            '{out:UseFurniture}{i:333}{i:0}',
            '{out:UseFurniture}{i:100}{i:0}',
        ])
        self.assertEqual([int(s.split('{i:')[1][:-1]) for s in actions[1::2]],
                         [900,901,900,901,900,901])

    def test_capture_requires_use_furniture_header_not_just_some_id(self):
        incoming=object()
        ext=SimpleNamespace(packet_infos={incoming:{
            88:[{'Name':'UseFurniture'}]}})
        self.assertEqual(capture(ext,incoming,Packet()),333)
        self.assertIsNone(capture(ext,object(),Packet()))
        self.assertIsNone(capture(ext,incoming,Packet(0)))
        ext.packet_infos[incoming][88]=[{'Name':'MoveAvatar'}]
        self.assertIsNone(capture(ext,incoming,Packet()))

    def test_benchmark_report_not_recipient_delivery_receipt(self):
        output=report(30.0,4,3,4,{'100':2,'333':2},
                      {'100':2,'333':2},0.1)
        self.assertIn('8.0 confirmed own pickups/min',output)
        self.assertIn('4/4',output)
        self.assertIn('3/4',output)
        self.assertIn('100: 2/2 pickups',output)
        self.assertIn('333: 2/2 pickups',output)
        self.assertIn('Recipient deliveries NOT verified',output)

    def test_speed_test_is_finite_confirmed_and_single_recipient_only(self):
        cls=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and
                 n.name=='ChatOverlayApp')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef)
                and n.name=='_start_coffee_loop')
        body=ast.get_source_segment(CODE,fn)
        self.assertIn('if speed_test:cycles=3',body)
        self.assertIn('if speed_test and group_mode:',body)
        self.assertIn('if speed_test and self._own_room_index is None:',body)
        self.assertIn('self._coffee_wait_for_hand=bool(',body)
        self.assertIn('coffee_extra_furniture=self.coffee_extra_furniture_var',body)
        self.assertIn('build_extended_coffee_sequence(',body)
        self.assertIn('build_coffee_group_sequence(',body)

if __name__=='__main__':
    unittest.main()
