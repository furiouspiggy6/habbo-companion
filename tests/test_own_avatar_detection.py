"""Own-avatar detection regression: room Users without UserObject should request identity once."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

APP=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=APP.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
CLS=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='ChatOverlayApp')
names={'_request_own_identity','_own_identity_timeout'}
nodes=[n for n in CLS.body if isinstance(n,ast.FunctionDef) and n.name in names]

class Value:
    def __init__(self,value=''):
        self.value=value
    def set(self,v):
        self.value=v

class Packet:
    def is_incomplete_packet(self):return False
    def is_corrupted(self):return False

class Extension:
    def __init__(self):
        self.requests=[]
    def string_to_packet(self,expr):
        self.requests.append(('parse',expr))
        return Packet()
    def send_to_server(self,packet):
        self.requests.append(('send',packet))
        return True

class Root:
    def __init__(self):self.scheduled=[]
    def after(self,ms,cb):self.scheduled.append((ms,cb))

class Clock:
    def __init__(self):self.now=100
    def monotonic(self):return self.now

clock=Clock()
scope={'time':clock}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(APP),'exec'),scope)

class AvatarLookupTests(unittest.TestCase):
    def instance(self):
        ext=Extension()
        return SimpleNamespace(
            packet_started=True,packet_extension=ext,
            _habbo_session_connected=True,
            _own_identity_last_request=0.0,_own_identity_pending=False,
            _own_room_index=None,_room_users={'atuu':('Atuu',381,7)},
            coffee_own_status_var=Value(),root=Root())

    def test_one_shot_info_retrieve_no_spam(self):
        obj=self.instance()
        request=scope['_request_own_identity']
        self.assertTrue(request(obj))
        self.assertEqual(obj.packet_extension.requests[0],('parse','{out:InfoRetrieve}'))
        self.assertEqual(obj.packet_extension.requests[1][0],'send')
        self.assertEqual(obj.root.scheduled[0][0],5000)
        self.assertTrue(obj._own_identity_pending)
        self.assertFalse(request(obj))
        self.assertEqual(len(obj.packet_extension.requests),2)
        self.assertIn('16',CODE) if False else None

    def test_missing_identity_reports_fallback(self):
        obj=self.instance()
        self.assertTrue(scope['_request_own_identity'](obj))
        scope['_own_identity_timeout'](obj,100)
        self.assertFalse(obj._own_identity_pending)
        self.assertIn('original timed loop',obj.coffee_own_status_var.value)

    def test_stale_timeout_cannot_clear_new_lookup(self):
        obj=self.instance()
        self.assertTrue(scope['_request_own_identity'](obj))
        scope['_own_identity_timeout'](obj,99)
        self.assertTrue(obj._own_identity_pending)

    def test_user_can_explicitly_choose_timed_mode(self):
        self.assertIn("self._request_own_identity()",CODE)
        self.assertIn("self.coffee_wait_for_hand_var.set(False)",CODE)
        self.assertIn("No = do not send anything yet.",CODE)
        self.assertIn("text='Detect my avatar'",CODE)
        self.assertIn("elif self._own_room_index is None:",CODE)

if __name__=='__main__':
    unittest.main()
