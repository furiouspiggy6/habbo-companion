"""Offline regression tests: username -> numeric ID via an exact Habbo profile reply."""
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))
FUNCTIONS={'profile_recipient_from_packet','remove_room_user_by_index',
           'coffee_profile_request_expression','incoming_packet_is','classify_room_packet'}
functions=[node for node in TREE.body if isinstance(node,ast.FunctionDef)
           and node.name in FUNCTIONS]
ns={'json':json,'re':re}
exec(compile(ast.Module(body=functions,type_ignores=[]),str(SOURCE),'exec'),ns)
read_profile=ns['profile_recipient_from_packet']
remove=ns['remove_room_user_by_index']
request=ns['coffee_profile_request_expression']
classify=ns['classify_room_packet']

CLASS=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='ChatOverlayApp')
fn=next(n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name=='_accept_coffee_profile')
methods={}
exec(compile(ast.Module(body=[fn],type_ignores=[]),str(SOURCE),'exec'),methods)
accept=methods['_accept_coffee_profile']

class Value:
    def __init__(self,value=''):
        self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class Packet:
    def __init__(self,id=381423,name='Cheesecake'):
        self.id=id;self.name=name
    def header_id(self):return 2952
    def read_int(self,index):
        if index!=6:raise AssertionError(index)
        return self.id
    def read_string(self,index):
        if index!=10:raise AssertionError(index)
        return self.name

class FakeRoot:
    def __init__(self):self.callbacks=[]
    def after(self,time,fn):
        self.callbacks.append((time,fn))

class ProfileLookupTests(unittest.TestCase):
    def test_profile_response_begins_with_account_id_and_name(self):
        self.assertEqual(read_profile(Packet()),('Cheesecake',381423))
        self.assertIsNone(read_profile(Packet(id=0)))
        self.assertIsNone(read_profile(Packet(name='')))
        self.assertIsNone(read_profile(Packet(name='a\x00b')))

    def test_request_is_escaped_and_not_an_arbitrary_packet(self):
        self.assertEqual(request(' Cheesecake '),
                         '{out:GetExtendedProfileByName}{s:"Cheesecake"}')
        with self.assertRaisesRegex(ValueError,'valid username'):
            request('foo}{i:1}')

    def test_profile_packet_detected_by_actual_header_metadata(self):
        incoming=object()
        ext=SimpleNamespace(packet_infos={incoming:{
            2952:[{'Name':'ExtendedProfile'}]}})
        self.assertEqual(classify(ext,incoming,Packet(),'[0][1]Raw'), 'ExtendedProfile')

    def test_player_leave_never_clears_other_users(self):
        users={'cheesecake':('Cheesecake',381423,None),
               'atuu':('Atuu',68808036,7),'micro':('Micro',68446836,9)}
        after,removed=remove(users,7)
        self.assertEqual(removed,('atuu',))
        self.assertIn('cheesecake',after)
        self.assertIn('micro',after)
        after2,removed2=remove(after,None)
        self.assertEqual(after2,after)
        self.assertEqual(removed2,())

    def fake(self,spoken=True):
        root=FakeRoot()
        record=SimpleNamespace(
            _coffee_profile_pending=('cheesecake',True,12),
            _habbo_session_connected=True,
            coffee_username_var=Value('Cheesecake'),
            coffee_status_var=Value(),
            coffee_users_status_var=Value(),
            _room_chat_names={'cheesecake'} if spoken else set(),
            _room_profile_cache={},
            _room_users={},
            root=root,
            _start_coffee_loop=lambda single_cup: (_ for _ in ()).throw(
                AssertionError('do not start until after user confirmation')),
        )
        return record

    def test_verified_profile_with_current_room_chat_queues_action(self):
        obj=self.fake()
        accept(obj,'Cheesecake',381423)
        self.assertIsNone(obj._coffee_profile_pending)
        self.assertEqual(obj._room_users['cheesecake'],('Cheesecake',381423,None))
        self.assertEqual(len(obj.root.callbacks),1)
        self.assertEqual(obj.root.callbacks[0][0],0)

    def test_profile_without_in_room_chat_does_not_send_coffee(self):
        obj=self.fake(spoken=False)
        accept(obj,'Cheesecake',381423)
        self.assertEqual(obj.root.callbacks,[])
        self.assertEqual(obj._room_users,{})
        self.assertIn('not spoken',obj.coffee_status_var.value)
        self.assertEqual(obj._room_profile_cache['cheesecake'],('Cheesecake',381423))

    def test_wrong_username_or_no_pending_request_cannot_trigger_coffee(self):
        obj=self.fake()
        accept(obj,'SomeoneElse',381423)
        self.assertEqual(obj.root.callbacks,[])
        self.assertEqual(obj._room_users,{})
        self.assertIsNotNone(obj._coffee_profile_pending)
        obj._coffee_profile_pending=None
        accept(obj,'Cheesecake',381423)
        self.assertEqual(obj.root.callbacks,[])

if __name__=='__main__':
    unittest.main()
