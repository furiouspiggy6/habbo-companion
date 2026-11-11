"""Tests for consenting participant group rotation and exclusions."""
import ast
from pathlib import Path
import re
import unittest

APP=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=APP.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
names={'build_coffee_pass_sequence','parse_coffee_group_names',
       'build_coffee_group_sequence'}
nodes=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in names]
ns={'re':re}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(APP),'exec'),ns)
parse=ns['parse_coffee_group_names']
build=ns['build_coffee_group_sequence']

class GroupTests(unittest.TestCase):
    def test_parse_deduplicates_and_requires_group(self):
        self.assertEqual(parse(' Atuu, Cheesecake, Micro '),
                         ('Atuu','Cheesecake','Micro'))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            parse('Atuu, atuu')
        with self.assertRaisesRegex(ValueError,'2 to 8'):
            parse('Atuu')
        with self.assertRaisesRegex(ValueError,'invalid'):
            parse('Atuu, name}{i:1')
        with self.assertRaisesRegex(ValueError,'2 to 8'):
            parse(','.join('test'+str(i) for i in range(9)))

    def test_two_people_each_receive_both_cups_per_round_trip(self):
        target=(('Atuu',16212392),('Micro',68446836))
        seq=build(476989081,476989024,target)
        self.assertEqual(seq,(
            '{out:UseFurniture}{i:476989081}{i:0}',
            '{out:PassCarryItem}{i:16212392}',
            '{out:UseFurniture}{i:476989024}{i:0}',
            '{out:PassCarryItem}{i:68446836}',
            '{out:UseFurniture}{i:476989024}{i:0}',
            '{out:PassCarryItem}{i:16212392}',
            '{out:UseFurniture}{i:476989081}{i:0}',
            '{out:PassCarryItem}{i:68446836}',
        ))

    def test_three_people_rotate_sequentially(self):
        ids=(('A',111),('B',222),('C',333))
        seq=build(1,2,ids)
        self.assertEqual([int(s.split('{i:')[1].split('}')[0]) for s in seq[1::2]],
                         [111,222,333,111,222,333])
        self.assertEqual(len(seq),12)

    def test_group_rate_limited_and_manual_exclusion_only(self):
        start=CODE[CODE.index('    def _start_coffee_loop(self,single_cup=False):'):
                   CODE.index('    def _check_queued_coffee_start(',CODE.index('    def _start_coffee_loop('))]
        self.assertIn('if group_mode and interval<10',start)
        self.assertIn('self._lookup_coffee_profile(missing,single_cup=False)',start)
        self.assertIn('self._coffee_group_targets=list(targets)',start)
        exclude=CODE[CODE.index('    def _exclude_coffee_group_recipient(self):'):
                     CODE.index('    def _start_coffee_loop(',CODE.index('    def _exclude_coffee_group_recipient'))]
        self.assertIn('self._coffee_group_targets=targets',exclude)
        self.assertIn('No automatic checks or retries',exclude)
        self.assertNotIn('GetExtendedProfileByName',exclude)

    def test_existing_single_cup_sequence_preserved(self):
        seq=ns['build_coffee_pass_sequence']('476989081','', '16212392',single_cup=True)
        self.assertEqual(len(seq),2)
        self.assertIn('16212392',seq[1])

if __name__=='__main__':
    unittest.main()
