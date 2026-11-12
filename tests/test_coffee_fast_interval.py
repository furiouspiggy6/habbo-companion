"""Sub-100ms coffee spacing with an unlimited number of ordinary loop cycles."""
import ast
import math
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
names={'validate_replay_interval','validate_coffee_interval','coffee_delay_ms'}
nodes=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in names]
scope={'math':math}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
coffee=scope['validate_coffee_interval']
ms=scope['coffee_delay_ms']
replay=scope['validate_replay_interval']

class FastCoffeeIntervalTests(unittest.TestCase):
    def test_sub_hundred_milliseconds_is_accepted(self):
        for sec,milliseconds in [('0.01',10),('0.02',20),('0.05',50),
                                 ('0.075',75),('0.099',99),('0.1',100)]:
            with self.subTest(sec=sec):
                self.assertAlmostEqual(coffee(sec),float(sec))
                self.assertEqual(ms(sec),milliseconds)

    def test_invalid_and_zero_delay_rejected_without_flooding_ui(self):
        for value in ('0','0.0','0.001','-1','inf','nan','foo','',None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    coffee(value)
        self.assertEqual(ms('0.0101'),10)
        self.assertEqual(ms('120'),120000)

    def test_packet_repeater_is_not_changed_by_coffee_setting(self):
        with self.assertRaises(ValueError):
            replay('0.05')
        self.assertEqual(replay('0.1'),0.1)

    def test_coffee_actions_use_new_spacing_and_cannot_go_zero_ms(self):
        app=next(n for n in TREE.body
                 if isinstance(n,ast.ClassDef) and n.name=='ChatOverlayApp')
        start=next(n for n in app.body if isinstance(n,ast.FunctionDef)
                   and n.name=='_start_coffee_loop')
        start_code=ast.get_source_segment(CODE,start)
        self.assertIn('validate_coffee_interval(self.coffee_interval_var.get())',start_code)
        self.assertIn('if group_mode and interval<10:',start_code)
        self.assertIn('cycles=int(cycles_text)',start_code)
        self.assertIn('if cycles>10000:',start_code)
        self.assertIn("'continuously until STOP' if cycles==0",start_code)
        tick=next(n for n in app.body if isinstance(n,ast.FunctionDef)
                  and n.name=='_coffee_loop_tick')
        tick_code=ast.get_source_segment(CODE,tick)
        self.assertIn('coffee_delay_ms(self._coffee_interval)',tick_code)
        self.assertIn('self._coffee_limit and self._coffee_completed>=self._coffee_limit',
                      tick_code)
        self.assertIn('if self._coffee_wait_for_hand:',tick_code)
        self.assertIn("0 = unlimited cycles until STOP",CODE)

if __name__=='__main__':
    unittest.main()
