"""Offline regression for optional stationary clientless anti-AFK.

This exercises Tk scheduling, saved per-profile preferences, room position
confirmation, pacing and no-movement LookTo frames without a real Habbo
account, G-Earth connection or credentials.
"""
import ast
import struct
from pathlib import Path
from types import SimpleNamespace
import unittest

import clientless_bot as bot
import habbo_tcp as tcp

SOURCE=(Path(__file__).resolve().parents[1]/"Habbo_Companion.pyw").read_text(encoding="utf-8")
TREE=ast.parse(SOURCE)
APP=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
         and n.name=="ChatOverlayApp")
METHODS={n.name:n for n in APP.body if isinstance(n,ast.FunctionDef)}
NAMES=("_bot_anti_afk_is_enabled","_bot_anti_afk_load_selected",
       "_bot_anti_afk_changed","_bot_anti_afk_tick",
       "_bot_receive_walk_observation")
NOW=[1000.0]
THREADS=[]

class FakeThread:
    def __init__(self,**kwargs):THREADS.append(kwargs)
    def start(self):pass

SCOPE={
    "time":SimpleNamespace(monotonic=lambda:NOW[0]),
    "tk":SimpleNamespace(TclError=RuntimeError),
    "threading":SimpleNamespace(Thread=FakeThread),
    "encode_clientless_action":bot.encode_clientless_action,
    "ClientlessBotError":bot.ClientlessBotError,
}
exec(compile(ast.Module(body=[METHODS[name] for name in NAMES],
       type_ignores=[]),"stationary-anti-afk","exec"),SCOPE)

class Var:
    def __init__(self,v):self.v=v
    def get(self):return self.v
    def set(self,v):self.v=v

class Root:
    def __init__(self):self.calls=[]
    def after(self,ms,callback):self.calls.append((ms,callback))

def fixture():
    ident="abcdef123456"
    session=SimpleNamespace(
        authenticated=True,release=tcp.TCP_FALLBACK_RELEASE,
        stop=SimpleNamespace(is_set=lambda:False))
    app=SimpleNamespace(
        config={"clientless_anti_afk_profiles":{}},
        _tcp_sessions={ident:session},_tcp_inflight=set(),
        _tcp_generation={ident:1},_bot_action_inflight=set(),
        _bot_walk_plans={},
        _bot_last_action_at={},_bot_anti_afk_rooms={},
        _bot_anti_afk_positions={},_bot_anti_afk_last={},
        _bot_self_ids={},_bot_user_roster={},
        _bot_headers=None,bot_anti_afk_var=Var(False),
        bot_anti_afk_status_var=Var(""),
        save=lambda:None,root=Root(),
        _bot_action_worker=lambda *args:None,
        _bot_walk_maybe_start=lambda *args:None)
    for name in NAMES:
        setattr(app,name,SCOPE[name].__get__(app))
    account={"id":ident,"label":"One saved account"}
    app._bot_selected_profile=lambda:account
    return app,ident,session

class StationaryAntiAfkTests(unittest.TestCase):
    def setUp(self):
        NOW[0]=1000.0
        THREADS.clear()

    def ready_avatar(self,app,ident,x=21,y=11):
        app._bot_receive_walk_observation(ident,1,("ready",69118545))
        app._bot_receive_walk_observation(ident,1,("identity",4567))
        app._bot_receive_walk_observation(ident,1,
            ("users",{4567:(42,x,y),5:(43,2,3)}))

    def test_preference_is_per_profile_and_off_by_default(self):
        app,ident,session=fixture()
        app._bot_anti_afk_load_selected()
        self.assertFalse(app.bot_anti_afk_var.get())
        app.bot_anti_afk_var.set(True)
        app._bot_anti_afk_changed()
        self.assertEqual(app.config["clientless_anti_afk_profiles"],{ident:True})
        self.assertEqual(app._bot_anti_afk_last[ident],1000.0)
        app._bot_anti_afk_load_selected()
        self.assertTrue(app.bot_anti_afk_var.get())
        app.bot_anti_afk_var.set(False)
        app._bot_anti_afk_changed()
        self.assertEqual(app.config["clientless_anti_afk_profiles"],{})

    def test_after_four_minutes_stays_in_place_and_uses_lookto(self):
        app,ident,session=fixture()
        app.bot_anti_afk_var.set(True)
        app._bot_anti_afk_changed()
        self.ready_avatar(app,ident)
        NOW[0]+=239
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])
        NOW[0]+=11
        app._bot_anti_afk_tick()
        self.assertEqual(len(THREADS),1)
        self.assertEqual(THREADS[0]["args"][3],"Anti-AFK")
        packets=THREADS[0]["args"][4]
        self.assertEqual([(i,b) for i,b,_ in packets],
             [(2574,struct.pack(">ii",21,11))])
        self.assertIn(ident,app._bot_action_inflight)
        self.assertEqual(app._bot_walk_plans,{})
        self.assertEqual(len(app.root.calls),2)
        self.assertIn("server idle reset not verified",
                      app.bot_anti_afk_status_var.get())

    def test_current_tile_updates_without_autowalk(self):
        app,ident,session=fixture()
        app.bot_anti_afk_var.set(True)
        app._bot_anti_afk_changed()
        self.ready_avatar(app,ident)
        app._bot_receive_walk_observation(ident,1,
            ("status",((42,22,12,None),(43,44,45,None))))
        NOW[0]+=241
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS[0]["args"][4][0][:2],
                         (2574,struct.pack(">ii",22,12)))

    def test_no_identity_or_no_room_avoids_guessing_tile(self):
        app,ident,session=fixture()
        app.bot_anti_afk_var.set(True)
        app._bot_anti_afk_changed()
        NOW[0]+=260
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])
        app._bot_receive_walk_observation(ident,1,("ready",69118545))
        app._bot_receive_walk_observation(ident,1,("identity",100))
        app._bot_receive_walk_observation(ident,1,("users",{200:(42,10,10)}))
        NOW[0]+=260
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])

    def test_room_switch_discards_previous_tile_and_resets_timer(self):
        app,ident,session=fixture()
        app.bot_anti_afk_var.set(True)
        app._bot_anti_afk_changed()
        self.ready_avatar(app,ident)
        NOW[0]+=220
        app._bot_receive_walk_observation(ident,1,("ready",9999))
        self.assertNotIn(ident,app._bot_anti_afk_positions)
        NOW[0]+=40
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])

    def test_avoids_auto_walk_inflight_and_disconnected_sessions(self):
        app,ident,session=fixture()
        app.bot_anti_afk_var.set(True)
        app._bot_anti_afk_changed()
        self.ready_avatar(app,ident)
        NOW[0]+=241
        app._bot_walk_plans[ident]={"phase":"walking"}
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])
        app._bot_walk_plans.clear()
        app._bot_action_inflight.add(ident)
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])
        app._bot_action_inflight.clear()
        session.authenticated=False
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])

    def test_no_stationary_packet_without_known_header(self):
        app,ident,session=fixture()
        app.bot_anti_afk_var.set(True)
        app._bot_anti_afk_changed()
        self.ready_avatar(app,ident)
        session.release="WIN63-202611201617-120873662"
        NOW[0]+=241
        app._bot_anti_afk_tick()
        self.assertEqual(THREADS,[])
        self.assertIn("unavailable",app.bot_anti_afk_status_var.get())

if __name__=="__main__":
    unittest.main()
