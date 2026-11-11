"""Regression tests for room-user refresh and Habbo packet decoding."""
import ast
from pathlib import Path
import json
import re
import unittest
from types import SimpleNamespace

SRC=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
tree=ast.parse(SRC.read_text(encoding='utf-8'))
func_names={'incoming_packet_is','room_user_ids_from_packet','classify_room_packet',
            'first_room_user_from_raw_packet'}
selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in func_names]
constants=[n for n in tree.body if isinstance(n,ast.Assign) and any(
    isinstance(t,ast.Name) and t.id in ('ROOM_USER_PAIR_RE','ROOM_USER_INDEX_RE')
    for t in n.targets)]
ns={'re':re,'json':json}
exec(compile(ast.Module(body=constants+selected,type_ignores=[]),str(SRC),'exec'),ns)
classify=ns['classify_room_packet']
raw=ns['first_room_user_from_raw_packet']
parse=ns['room_user_ids_from_packet']
class_node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ChatOverlayApp')
fn_node=next(n for n in class_node.body
             if isinstance(n,ast.FunctionDef) and n.name=='_room_refresh_timeout')
scope={}
exec(compile(ast.Module(body=[fn_node],type_ignores=[]),str(SRC),'exec'),scope)
timeout=scope['_room_refresh_timeout']

class Val:
    def __init__(self,value=''):self.value=value
    def set(self,value):self.value=value
class Packet:
    def header_id(self):return 374
    def read_int(self,index):
        if index==6:return 2
        if index==10:return 68808036
        raise AssertionError(index)
    def read_string(self,index):
        if index==14:return 'Atuu'
        raise AssertionError(index)

class Tests(unittest.TestCase):
    def test_named_header_recognized_even_if_legacy_raw_string_has_no_name(self):
        incoming=object()
        ext=SimpleNamespace(packet_infos={incoming:{
            374:[{'Name':'Users'}],200:[{'Name':'UserRemove'}]}})
        self.assertEqual(classify(ext,incoming,Packet(),'[0][0][0]'),'Users')
        self.assertEqual(raw(Packet()),{'atuu':('Atuu',68808036,None)})
        self.assertEqual(classify(ext,object(),Packet(),'[0][0][0]'),None)

    def test_decoded_expression_gets_all_users_not_just_first(self):
        expression=('{in:Users}{i:2}'
                    '{i:68808036}{s:"Atuu"}{s:"motto"}{s:"hd-180-1"}{i:7}'
                    '{i:68446836}{s:"Micro"}{s:"hello"}{s:"hd-185-1"}{i:9}')
        self.assertEqual(parse(expression,trusted_users=True)['micro'][1],68446836)

    def test_raw_decoder_does_not_use_bad_user_id(self):
        packet=Packet()
        packet.read_int=lambda i:{6:2,10:0}[i]
        self.assertEqual(raw(packet),{})

    def fake(self,seen=False,failed=False,connected=True):
        return SimpleNamespace(_room_lookup_pending=True,_room_lookup_generation=7,
            _habbo_session_connected=connected,_room_lookup_parse_failed=failed,
            _room_lookup_seen=seen,coffee_users_status_var=Val())

    def test_timeout_no_reply(self):
        fake=self.fake()
        timeout(fake,7)
        self.assertFalse(fake._room_lookup_pending)
        self.assertIn('No Users packet arrived',fake.coffee_users_status_var.value)
        self.assertIn('re-enter',fake.coffee_users_status_var.value)

    def test_timeout_unparseable_reply(self):
        fake=self.fake(seen=True,failed=True)
        timeout(fake,7)
        self.assertIn('could not be decoded',fake.coffee_users_status_var.value)

    def test_old_timeout_ignored(self):
        fake=self.fake()
        timeout(fake,3)
        self.assertTrue(fake._room_lookup_pending)
        self.assertEqual(fake.coffee_users_status_var.value,'')

if __name__=='__main__':
    unittest.main()
