"""Offline regression tests for opt-in G-Earth pre-start routing preview.

This stage intentionally does NOT claim interception: G-Earth ON blocks
login until a verified MITM bridge exists, rather than bypassing G-Earth.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/
        "Habbo_Companion.pyw").read_text(encoding="utf-8")
TREE=ast.parse(SOURCE)
APP=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
         and n.name=="ChatOverlayApp")
METHODS={n.name:n for n in APP.body if isinstance(n,ast.FunctionDef)}
SELECTED=("_bot_gearth_changed","_bot_gearth_probe","_bot_run_account",
          "_bot_send_action","_tcp_auto_connect_startup")
SCOPE={"clientless_saved_room_value":lambda n:str(n)}
exec(compile(ast.Module(body=[METHODS[n] for n in SELECTED],
             type_ignores=[]),"clientless-gearth-preview","exec"),SCOPE)


class Var:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


def fixture(connected=False):
    account={"id":"012345abcdef","label":"Test Account"}
    session=SimpleNamespace(authenticated=True,
        stop=SimpleNamespace(is_set=lambda:False))
    calls=[]
    app=SimpleNamespace(
        _account_profiles=[account],
        _tcp_sessions={account["id"]:session} if connected else {},
        _tcp_inflight=set(),_tcp_generation={},_tcp_states={},
        _bot_pending_room={},_bot_walk_plans={},
        bot_room_var=Var("69118545"),bot_account_var=Var(""),
        bot_status_var=Var(""),bot_gearth_var=Var(False),
        bot_gearth_status_var=Var(""),
        gearth_port_var=Var("9092"),
        config={"clientless_gearth_intercept":False},
        _bot_selected_profile=lambda:account,
        _bot_send_action=lambda **kw:calls.append(("send",kw)),
        _tcp_connect_one=lambda *args,**kwargs:calls.append(("connect",kwargs)),
        _gearth_extension_port_responds=lambda port:port==9092,
        save=lambda:calls.append(("save",{})),
        tcp_autostart_var=Var(True),tcp_status_var=Var(""),
        _tcp_connect_all=lambda:calls.append(("connect_all",{})),
        _tcp_render=lambda:None,
    )
    return app,account,calls


class GearthPrestartTests(unittest.TestCase):
    def test_opt_in_stored_and_mode_can_be_switched_off(self):
        app,account,calls=fixture()
        app.bot_gearth_var.set(True)
        SCOPE["_bot_gearth_changed"](app)
        self.assertTrue(app.config["clientless_gearth_intercept"])
        self.assertIn("NOT",app.bot_gearth_status_var.get())
        app.bot_gearth_var.set(False)
        SCOPE["_bot_gearth_changed"](app)
        self.assertFalse(app.config["clientless_gearth_intercept"])
        self.assertIn("Direct TCP",app.bot_gearth_status_var.get())

    def test_on_never_starts_direct_tcp_or_joins_a_room(self):
        app,account,calls=fixture()
        app.bot_gearth_var.set(True)
        app._bot_pending_room["another-account"]=(2,1234)
        SCOPE["_bot_run_account"](app,account)
        self.assertEqual(calls,[])
        self.assertEqual(app._bot_pending_room,{"another-account":(2,1234)})
        self.assertIn("Bot NOT started",app.bot_status_var.get())
        self.assertIn("MITM",app.bot_status_var.get())

    def test_on_does_not_even_send_join_with_existing_connection(self):
        app,account,calls=fixture(connected=True)
        app.bot_gearth_var.set(True)
        SCOPE["_bot_run_account"](app,account)
        self.assertEqual(calls,[])
        self.assertIn("Bot NOT started",app.bot_status_var.get())

    def test_active_session_cannot_switch_routing_midflight(self):
        app,account,calls=fixture(connected=True)
        app.bot_gearth_var.set(True)
        SCOPE["_bot_gearth_changed"](app)
        self.assertFalse(app.bot_gearth_var.get())
        self.assertFalse(app.config["clientless_gearth_intercept"])
        self.assertEqual(calls,[])
        self.assertIn("Disconnect",app.bot_gearth_status_var.get())
        app._tcp_sessions={}
        app._tcp_inflight.add(account["id"])
        app.bot_gearth_var.set(True)
        SCOPE["_bot_gearth_changed"](app)
        self.assertFalse(app.bot_gearth_var.get())
        self.assertEqual(calls,[])

    def test_preview_blocks_manual_sends_and_automatic_tcp_startup(self):
        app,account,calls=fixture(connected=True)
        app.bot_gearth_var.set(True)
        SCOPE["_bot_send_action"](app)
        self.assertIn("actions are blocked",app.bot_status_var.get())
        SCOPE["_tcp_auto_connect_startup"](app)
        self.assertIn("startup skipped",app.tcp_status_var.get())
        self.assertEqual(calls,[])

    def test_off_retains_direct_tcp_launch(self):
        app,account,calls=fixture()
        SCOPE["_bot_run_account"](app,account)
        self.assertEqual(calls,[("connect",{}),("connect",{"auto_capture":True})])

    def test_port_check_is_read_only_and_does_not_claim_proxy(self):
        app,account,calls=fixture()
        SCOPE["_bot_gearth_probe"](app)
        self.assertIn("reachable",app.bot_gearth_status_var.get())
        self.assertIn("does NOT mean",app.bot_gearth_status_var.get())
        self.assertEqual(calls,[])
        app.gearth_port_var.set("0")
        SCOPE["_bot_gearth_probe"](app)
        self.assertIn("Invalid",app.bot_gearth_status_var.get())
        self.assertEqual(calls,[])

    def test_prestart_choice_before_account_profile_autorun(self):
        panel=ast.get_source_segment(SOURCE,METHODS["_make_clientless_bot_panel"])
        self.assertLess(panel.index("PRE-START: G-EARTH INTERCEPTION"),
                        panel.index("Connected account"))
        self.assertIn("command=self._bot_gearth_changed",panel)
        self.assertIn("command=self._bot_gearth_probe",panel)
        self.assertIn("<<ComboboxSelected>>",panel)
        self.assertIn("clientless_gearth_intercept=False",SOURCE)


if __name__=="__main__":
    unittest.main()
