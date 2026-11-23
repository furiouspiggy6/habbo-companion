"""Offline tests: per-room primary/fallback walking with server confirmations.

No real TCP sockets, Habbo users, browser data, or G-Earth are accessed.
"""
import ast
import struct
import time
from pathlib import Path
from types import SimpleNamespace
import unittest

import clientless_bot as bot
import habbo_tcp

SOURCE=(Path(__file__).resolve().parents[1]/"Habbo_Companion.pyw").read_text(encoding="utf-8")
TREE=ast.parse(SOURCE)
APP=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=="ChatOverlayApp")
METHODS={n.name:n for n in APP.body if isinstance(n,ast.FunctionDef)}
NAMES=("_bot_load_walk_preset","_bot_save_walk_preset","_bot_arm_walk",
       "_bot_walk_maybe_start","_bot_receive_walk_observation","_bot_walk_next",
       "_bot_walk_send","_bot_walk_tick")
now=[1000.0]
spawned=[]


class FakeThread:
    def __init__(self,**kwargs):
        spawned.append(kwargs)
    def start(self):
        pass


SCOPE={"clientless_walk_positions":bot.clientless_walk_positions,
       "clientless_saved_room_value":lambda n: str(n) if str(n).isdigit()
       and 1<=int(n)<=2147483647 else "69118545",
       "encode_clientless_action":bot.encode_clientless_action,
       "ClientlessBotError":bot.ClientlessBotError,
       "time":SimpleNamespace(monotonic=lambda:now[0]),
       "threading":SimpleNamespace(Thread=FakeThread)}
exec(compile(ast.Module(body=[METHODS[name] for name in NAMES],type_ignores=[]),
             "auto-walk-methods","exec"),SCOPE)


def bind(app):
    for key in NAMES:
        setattr(app,key,SCOPE[key].__get__(app))


class Var:
    def __init__(self,x):self.x=x
    def get(self):return self.x
    def set(self,x):self.x=x


class Root:
    def __init__(self):self.callbacks=[]
    def after(self,ms,cb):self.callbacks.append((ms,cb))


def fake_app():
    account_id="abcdef123456"
    session=SimpleNamespace(
        authenticated=True,release=habbo_tcp.TCP_FALLBACK_RELEASE,
        stop=SimpleNamespace(is_set=lambda:False))
    app=SimpleNamespace(
        config={"clientless_walk_presets":{"69118545":[[10,15],[11,15],[12,15]]},
                "clientless_auto_walk":True},
        bot_room_var=Var("69118545"),
        bot_walk_primary_var=Var(""),bot_walk_backups_var=Var(""),
        bot_auto_walk_var=Var(True),bot_walk_status_var=Var(""),
        bot_status_var=Var(""),_bot_walk_plans={},_bot_self_ids={},
        _bot_user_roster={},_bot_headers=None,_bot_action_inflight=set(),
        _bot_last_action_at={},_tcp_sessions={account_id:session},
        _tcp_generation={account_id:3},root=Root(),
        _bot_action_worker=lambda *args:None,
        save=lambda:None)
    bind(app)
    return app,account_id,session


def string(s):
    b=s.encode("utf-8")
    return struct.pack(">H",len(b))+b


class WalkPresetTests(unittest.TestCase):
    def test_coordinate_validation(self):
        self.assertEqual(bot.clientless_walk_positions("10,15","11,15; 12,15; 13,15"),
                         ((10,15),(11,15),(12,15),(13,15)))
        self.assertEqual(bot.clientless_walk_positions("",""),())
        for primary,backups in (
            ("","10,15"),("10,15","10,15"),("-1,2",""),
            ("1024,1",""),("1,1","2,2;3,3;4,4;5,5"),
            ("1,1","2,2;;3,3"),("1,1","hello")):
            with self.subTest(primary=primary,backups=backups):
                with self.assertRaises(bot.ClientlessBotError):
                    bot.clientless_walk_positions(primary,backups)

    def test_stores_room_only_and_disables_without_coordinates(self):
        app,ident,session=fake_app()
        app._bot_load_walk_preset()
        self.assertEqual(app.bot_walk_primary_var.get(),"10,15")
        self.assertEqual(app.bot_walk_backups_var.get(),"11,15;12,15")
        app.bot_room_var.set("1234")
        app.bot_walk_primary_var.set("6,7")
        app.bot_walk_backups_var.set("7,7")
        app._bot_save_walk_preset()
        self.assertEqual(app.config["clientless_walk_presets"]["1234"],[[6,7],[7,7]])
        self.assertEqual(app.config["clientless_walk_presets"]["69118545"][0],[10,15])
        app.bot_room_var.set("4321")
        app.bot_walk_primary_var.set("")
        app.bot_walk_backups_var.set("")
        app._bot_save_walk_preset()
        self.assertFalse(app.bot_auto_walk_var.get())


class RoomPacketTests(unittest.TestCase):
    def test_parses_expected_read_only_observations(self):
        release=habbo_tcp.TCP_FALLBACK_RELEASE
        self.assertEqual(bot.decode_clientless_room_observation(
            release,2833,struct.pack(">i",69118545)),("ready",69118545))
        self.assertEqual(bot.decode_clientless_room_observation(
            release,1168,struct.pack(">i",4567)+string("MyAccount")),
            ("identity",4567))
        avatar=(struct.pack(">i",4567)+string("MyAccount")+string("")+
                string("hd-180-1")+struct.pack(">iii",42,2,3)+string("0.0")+
                struct.pack(">ii",0,1)+string("M")+struct.pack(">ii",0,0)+
                string("")+string("")+struct.pack(">i",1)+b"\x00"+
                struct.pack(">i",0))
        packet=struct.pack(">i",1)+avatar
        self.assertEqual(bot.decode_clientless_room_observation(
            release,3357,packet),("users",{4567:(42,2,3)}))
        movement=(struct.pack(">iiii",1,42,9,15)+string("0.0")+
                  struct.pack(">iii",0,0,0)+string("mv 10,15,0.0"))
        self.assertEqual(bot.decode_clientless_room_observation(
            release,996,movement),("status",((42,9,15,(10,15)),)))
        self.assertIsNone(bot.decode_clientless_room_observation(
            "WIN63-202611201617-120873662",2833,struct.pack(">i",69118545)))
        self.assertIsNone(bot.decode_clientless_room_observation(
            release,3357,packet[:-1]))


class MovementLifecycleTests(unittest.TestCase):
    def setUp(self):
        spawned.clear()
        now[0]=1000.0

    def enter(self,app,ident,session):
        app._bot_arm_walk(ident,3,session,69118545)
        app._bot_receive_walk_observation(ident,3,("identity",4567))
        app._bot_receive_walk_observation(ident,3,("ready",69118545))
        app._bot_receive_walk_observation(ident,3,("users",{4567:(42,1,2)}))

    def test_waits_for_room_ready_and_self_identity(self):
        app,ident,session=fake_app()
        app._bot_arm_walk(ident,3,session,69118545)
        app._bot_receive_walk_observation(ident,3,("identity",4567))
        app._bot_receive_walk_observation(ident,3,("users",{4567:(42,1,2)}))
        self.assertEqual(len(spawned),0)
        app._bot_receive_walk_observation(ident,3,("ready",12345))
        self.assertEqual(len(spawned),0)
        app._bot_receive_walk_observation(ident,3,("ready",69118545))
        self.assertEqual(len(spawned),1)
        self.assertEqual(app._bot_walk_plans[ident]["requested"],(10,15))

    def test_primary_success_never_attempts_backup(self):
        app,ident,session=fake_app()
        self.enter(app,ident,session)
        app._bot_receive_walk_observation(ident,3,
            ("status",((42,10,15,None),)))
        self.assertNotIn(ident,app._bot_walk_plans)
        self.assertEqual(len(spawned),1)
        self.assertIn("Arrived",app.bot_walk_status_var.get())

    def test_tries_backups_in_order_on_timeout_then_stops(self):
        app,ident,session=fake_app()
        self.enter(app,ident,session)
        self.assertEqual(len(spawned),1)
        app._bot_action_inflight.clear()  # Fake the successful socket send.
        now[0]+=15
        app._bot_walk_tick(ident,3)
        self.assertEqual(app._bot_walk_plans[ident]["requested"],(11,15))
        self.assertEqual(len(spawned),2)
        app._bot_action_inflight.clear()
        now[0]+=15
        app._bot_walk_tick(ident,3)
        self.assertEqual(app._bot_walk_plans[ident]["requested"],(12,15))
        app._bot_action_inflight.clear()
        now[0]+=15
        app._bot_walk_tick(ident,3)
        self.assertNotIn(ident,app._bot_walk_plans)
        self.assertEqual(len(spawned),3)

    def test_no_room_or_no_self_identity_never_walks(self):
        app,ident,session=fake_app()
        app._bot_arm_walk(ident,3,session,69118545)
        now[0]+=19
        app._bot_walk_tick(ident,3)
        self.assertEqual(len(spawned),0)
        self.assertNotIn(ident,app._bot_walk_plans)
        app._bot_arm_walk(ident,3,session,69118545)
        app._bot_receive_walk_observation(ident,3,("ready",69118545))
        now[0]+=16
        app._bot_walk_tick(ident,3)
        self.assertEqual(len(spawned),0)
        self.assertNotIn(ident,app._bot_walk_plans)

    def test_no_preset_or_release_mismatch_does_nothing(self):
        app,ident,session=fake_app()
        app.bot_auto_walk_var.set(False)
        app._bot_arm_walk(ident,3,session,69118545)
        self.assertEqual(app._bot_walk_plans,{})
        app.bot_auto_walk_var.set(True)
        session.release="WIN63-202611201617-120873662"
        app._bot_arm_walk(ident,3,session,69118545)
        self.assertEqual(app._bot_walk_plans,{})
        self.assertEqual(len(spawned),0)

    def test_stale_generation_does_not_move(self):
        app,ident,session=fake_app()
        app._bot_arm_walk(ident,3,session,69118545)
        app._tcp_generation[ident]=4
        app._bot_walk_tick(ident,3)
        self.assertNotIn(ident,app._bot_walk_plans)
        self.assertEqual(len(spawned),0)


if __name__=="__main__":
    unittest.main()
