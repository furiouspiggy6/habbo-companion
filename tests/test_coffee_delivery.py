"""Regression checks for coffee handoff monitoring and steady cursor overlay."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

APP=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=APP.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
names={'carry_object_from_packet','coffee_delivery_text','classify_room_packet','incoming_packet_is'}
funcs=[f for f in TREE.body if isinstance(f,ast.FunctionDef) and f.name in names]
namespace={}
exec(compile(ast.Module(body=funcs,type_ignores=[]),str(APP),'exec'),namespace)

class CarryPacket:
    def __init__(self,index=5,item=1):self.index=index;self.item=item
    def header_id(self):return 150
    def read_int(self,offset):
        return {6:self.index,10:self.item}[offset]

class DeliveryMonitorTests(unittest.TestCase):
    def test_incoming_carry_object_packet_has_room_index_not_account_id(self):
        self.assertEqual(namespace['carry_object_from_packet'](CarryPacket(5,9)),(5,9))
        self.assertIsNone(namespace['carry_object_from_packet'](CarryPacket(-1,9)))
        self.assertIsNone(namespace['carry_object_from_packet'](CarryPacket(5,-1)))

    def test_carry_packets_recognized_by_name_not_numeric_header(self):
        incoming=object()
        extension=SimpleNamespace(packet_infos={incoming:{150:[{'Name':'CarryObject'}]}})
        self.assertEqual(namespace['classify_room_packet'](
            extension,incoming,CarryPacket(),'[raw]'),'CarryObject')

    def test_no_false_delivery_claim_when_room_index_unknown(self):
        result=namespace['coffee_delivery_text'](27,0,None)
        self.assertIn('27',result)
        self.assertIn('cannot verify receipt',result)
        self.assertNotIn('delivered',result.lower())

    def test_observed_carry_updates_not_equated_to_each_delivery(self):
        result=namespace['coffee_delivery_text'](27,1,5)
        self.assertIn('27',result)
        self.assertIn('1',result)
        self.assertIn('not proof each cup arrived',result)

    def test_monitor_filters_by_target_room_index_and_recent_pass(self):
        block=CODE[CODE.index("            if item[0]=='coffee_carry_observed':"):
                   CODE.index("            if item[0]=='room_users_reset':")]
        self.assertIn('room_index==self._coffee_target_room_index',block)
        self.assertIn('item_type>0',block)
        self.assertIn('0<=seen_at-self._coffee_last_pass_at<=4',block)

    def test_fewer_overlay_redraws_and_clickthrough_style_checks(self):
        tick=CODE[CODE.index('    def tick(self):'):CODE.index('    def close(self):')]
        self.assertIn('now-self.last_overlay_draw_at>=0.6',tick)
        self.assertIn('time.monotonic()-self.last_stack_check>0.75',tick)
        self.assertIn('time.monotonic()-self.last_clickthrough_check>6.0',tick)
        self.assertIn('signature!=self.last_overlay_draw_signature',tick)
        self.assertNotIn('self.tracker.SetCursorPos',tick)

if __name__=='__main__':
    unittest.main()
