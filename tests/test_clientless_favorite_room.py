"""Regression tests for the permanent Coffee House Clientless Bot favorite.

All tests use isolated configuration files and a fake TCP session; nothing is
sent to Habbo, G-Earth, or an external network.
"""
import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
SOURCE=(ROOT/"Habbo_Companion.pyw").read_text(encoding="utf-8")
TREE=ast.parse(SOURCE)
CLASS=next(x for x in TREE.body if isinstance(x,ast.ClassDef)
           and x.name=="ChatOverlayApp")
NS={"re":re}
constant=next(x for x in TREE.body if isinstance(x,ast.Assign)
              and any(isinstance(n,ast.Name)
                      and n.id=="CLIENTLESS_COFFEE_HOUSE_ROOM_ID"
                      for n in x.targets))
exec(compile(ast.Module(body=[constant],type_ignores=[]),
             "<favorite-constant>","exec"),NS)
for name in ("clientless_saved_room_value","load_config"):
    node=next(x for x in TREE.body if isinstance(x,ast.FunctionDef)
              and x.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),
                 "<favorite-helpers>","exec"),NS)
for name in ("_bot_join_coffee_house","_bot_send_action"):
    node=next(x for x in CLASS.body if isinstance(x,ast.FunctionDef)
              and x.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),
                 "<favorite-methods>","exec"),NS)


class Var:
    def __init__(self,value):self.value=value
    def set(self,value):self.value=value
    def get(self):return self.value


class RoomFavoriteTests(unittest.TestCase):
    def test_fixed_coffee_house_value(self):
        self.assertEqual(NS["CLIENTLESS_COFFEE_HOUSE_ROOM_ID"],69118545)
        self.assertEqual(NS["clientless_saved_room_value"](None),"69118545")

    def test_last_entered_room_may_be_remembered_but_invalid_input_is_rejected(self):
        normalize=NS["clientless_saved_room_value"]
        self.assertEqual(normalize("523512"),"523512")
        self.assertEqual(normalize(69118545),"69118545")
        self.assertEqual(normalize(" 69118545 "),"69118545")
        for value in (None,"",0,-1,False,True,"99999999999",
                      "https://www.habbo.com/room/69118545",
                      "../other","10.5",3.14,object()):
            with self.subTest(value=value):
                self.assertEqual(normalize(value),"69118545")

    def test_room_favorite_is_user_initiated_not_automatic(self):
        sent=[]
        model=SimpleNamespace(
            bot_room_var=Var("999"),
            bot_action_var=Var("Say"),
            _bot_send_action=lambda:sent.append("clicked"),
        )
        self.assertEqual(sent,[])
        NS["_bot_join_coffee_house"](model)
        self.assertEqual(model.bot_room_var.get(),"69118545")
        self.assertEqual(model.bot_action_var.get(),"Join room")
        self.assertEqual(sent,["clicked"])

    def test_loader_preserves_last_room_and_public_header_mappings(self):
        # Before this change, load_config discarded keys not present in DEFAULT.
        # Test the real DEFAULT expression rather than making assumptions.
        default=next(n for n in TREE.body if isinstance(n,ast.Assign)
                     and any(isinstance(t,ast.Name) and t.id=="DEFAULT"
                             for t in n.targets))
        exec(compile(ast.Module(body=[default],type_ignores=[]),
                     "<defaults>","exec"),NS)
        self.assertEqual(NS["DEFAULT"]["clientless_last_room_id"],"69118545")
        self.assertIn("clientless_header_map",NS["DEFAULT"])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"settings.json"
            saved={
                "clientless_last_room_id":"90007001",
                "clientless_header_map":{
                    "release":"WIN63-202611041140-327405090",
                    "outgoing":{"Chat":377,"GetGuestRoom":355},
                    "incoming":{}},
                "gearth_startup_safety_v104":True,
                "gearth_visible_debug_v106":True,
                "gearth_startup_uia_v105":True,
                "gearth_background_v108":True,
                "gearth_network_safety_v114":True,
                "gearth_single_window_v116":True,
            }
            p.write_text(json.dumps(saved),encoding="utf-8")
            NS.update({"CONFIG_PATH":p,"APP_DIR":Path(tmp),"json":json})
            loaded=NS["load_config"]()
            self.assertEqual(loaded["clientless_last_room_id"],"90007001")
            self.assertEqual(
                loaded["clientless_header_map"]["outgoing"]["Chat"],377)
            self.assertEqual(NS["clientless_saved_room_value"](
                loaded["clientless_last_room_id"]),"90007001")

    def test_manual_join_saves_last_valid_room_id_without_network(self):
        import clientless_bot
        import habbo_tcp
        from unittest.mock import patch

        class FakeThread:
            calls=[]
            def __init__(self,**kwargs):
                self.calls.append(kwargs)
            def start(self):pass

        saves=[]
        account={"id":"abcdef","label":"Test"}
        session=SimpleNamespace(
            authenticated=True,
            stop=SimpleNamespace(is_set=lambda:False),
            release=habbo_tcp.TCP_FALLBACK_RELEASE)
        app=SimpleNamespace(
            _bot_selected_profile=lambda:account,
            _tcp_sessions={"abcdef":session},
            _bot_action_inflight=set(),
            _bot_last_action_at={},
            bot_action_var=Var("Join room"),
            bot_room_var=Var("69118545"),
            bot_x_var=Var("0"),bot_y_var=Var("0"),
            bot_message_var=Var(""),bot_recipient_var=Var(""),
            bot_id_var=Var("1"),
            _bot_headers={"release":habbo_tcp.TCP_FALLBACK_RELEASE,
                          "outgoing":{"GetGuestRoom":355},"incoming":{}},
            bot_status_var=Var(""),
            _tcp_generation={"abcdef":1},
            _bot_action_worker=lambda *args:None,
            config={"clientless_last_room_id":"777"},
            save=lambda:saves.append("saved"),
        )
        with patch.dict(NS,{"time":SimpleNamespace(monotonic=lambda:1000),
                            "threading":SimpleNamespace(Thread=FakeThread),
                            "encode_clientless_action":clientless_bot.encode_clientless_action}):
            NS["_bot_send_action"](app)
        self.assertEqual(app.config["clientless_last_room_id"],"69118545")
        self.assertEqual(saves,["saved"])
        self.assertEqual(len(FakeThread.calls),1)
        self.assertEqual(len(FakeThread.calls[0]["args"][-1]),2)
        self.assertEqual(app._bot_action_inflight,{"abcdef"})

    def test_no_room_is_joined_on_program_start(self):
        self.assertIn("command=self._bot_join_coffee_house",SOURCE)
        self.assertIn("text='Join Coffee House'",SOURCE)
        self.assertIn("self.bot_room_var=tk.StringVar(value=clientless_saved_room_value(",SOURCE)
        self.assertNotIn("self._bot_join_coffee_house()\n",SOURCE)


if __name__=="__main__":
    unittest.main()
