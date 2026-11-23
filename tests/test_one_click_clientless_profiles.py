"""Offline regression tests for user-initiated, one-click AIR-free profile runs.

No live account, browser, G-Earth, server or credentials are accessed.
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
APP=next(x for x in TREE.body if isinstance(x,ast.ClassDef) and x.name=="ChatOverlayApp")
METHODS={x.name:x for x in APP.body if isinstance(x,ast.FunctionDef)}
METHOD_NAMES=("_bot_run_account","_bot_run_selected","_bot_run_from_accounts",
              "_bot_dispatch_pending_room","_bot_standalone_changed")
SCOPE={"clientless_saved_room_value":lambda n: str(n) if str(n).isdigit()
       and 1<=int(n)<=2147483647 else "69118545"}
exec(compile(ast.Module(body=[METHODS[name] for name in METHOD_NAMES],type_ignores=[]),
             "one-click-helpers","exec"),SCOPE)


class Var:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


def fake_app(connected=False):
    account={"id":"abcdef123456","label":"My Profile"}
    existing=SimpleNamespace(authenticated=True,stop=SimpleNamespace(is_set=lambda:False))
    messages=[]
    connect_calls=[]
    app=SimpleNamespace(
        _account_profiles=[account],_tcp_sessions=({account["id"]:existing}
                                                   if connected else {}),
        _tcp_inflight=set(),_tcp_generation={},_tcp_states={},
        _bot_pending_room={},_bot_walk_plans={},
        _bot_run_room_targets={},_bot_multi_direct_ids=set(),
        bot_room_var=Var("69118545"),
        bot_status_var=Var(""),bot_account_var=Var(""),
        bot_gearth_var=Var(False),bot_gearth_status_var=Var(""),
        gearth_port_var=Var("9092"),
        config={"clientless_gearth_intercept":False},
        save=lambda:None,
        _tcp_render=lambda:None,
        _bot_send_action=lambda **kwargs:messages.append(kwargs),
        _bot_anti_afk_load_selected=lambda:None,
        _bot_load_walk_preset=lambda:None,
    )
    def connect(account,auto_capture=False):
        connect_calls.append(auto_capture)
        # No saved cookies in this fake app. Auto-import is the second attempt.
        if auto_capture:
            app._tcp_inflight.add(account["id"])
            app._tcp_generation[account["id"]]=3
    app._tcp_connect_one=connect
    return app,account,messages,connect_calls


class AirFreeMappingTests(unittest.TestCase):
    def test_source_pinned_build_and_core_actions(self):
        self.assertEqual(bot.BUNDLED_AIR_RELEASE,tcp.TCP_FALLBACK_RELEASE)
        self.assertEqual(bot.bundled_air_headers(tcp.TCP_FALLBACK_RELEASE)["outgoing"]["Chat"],3463)
        # No G-Earth mapping supplied: known build may use its bundled table.
        join=bot.encode_clientless_action(None,tcp.TCP_FALLBACK_RELEASE,
                                          "Join room",room=69118545)
        self.assertEqual([i[0] for i in join],[216,216])
        say=bot.encode_clientless_action(None,tcp.TCP_FALLBACK_RELEASE,
                                         "Say",text="test123")
        self.assertEqual(say[0],(3463,struct.pack(">H",7)+b"test123"
                                 +struct.pack(">ii",0,-1),"Chat"))
        payload=struct.pack(">iH",42,2)+b"hi"
        self.assertEqual(bot.decode_clientless_chat(
            None,tcp.TCP_FALLBACK_RELEASE,3477,payload),("Chat",42,"hi"))

    def test_new_release_and_unmapped_commands_fail_closed(self):
        release="WIN63-202611201617-120873662"
        with self.assertRaisesRegex(bot.ClientlessBotError,"No bundled"):
            bot.encode_clientless_action(None,release,"Say",text="hi")
        with self.assertRaisesRegex(bot.ClientlessBotError,"missing Quit"):
            bot.encode_clientless_action(None,tcp.TCP_FALLBACK_RELEASE,"Leave room")
        self.assertNotIn("Quit",bot.bundled_air_headers(tcp.TCP_FALLBACK_RELEASE)["outgoing"])
        # Explicit G-Earth maps still work and aren't modified in-place.
        mapping={"release":release,"outgoing":{"Chat":540},"incoming":{}}
        old=dict(mapping["outgoing"])
        self.assertEqual(bot.encode_clientless_action(
            mapping,release,"Say",text="hi")[0][0],540)
        self.assertEqual(mapping["outgoing"],old)


class OneClickLaunchTests(unittest.TestCase):
    def test_choose_profile_then_auto_import_and_auto_join_only_after_auth(self):
        app,account,sent,calls=fake_app()
        SCOPE["_bot_run_account"](app,account)
        self.assertEqual(calls,[False,True])
        self.assertEqual(sent,[])
        self.assertEqual(app._bot_pending_room[account["id"]],(3,69118545))
        self.assertIn("Connecting",app.bot_status_var.get())
        app._tcp_sessions[account["id"]]=SimpleNamespace(
            authenticated=True,stop=SimpleNamespace(is_set=lambda:False))
        SCOPE["_bot_dispatch_pending_room"](app,account["id"],3)
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0]["account_override"],account)
        self.assertEqual(sent[0]["action_override"],"Join room")
        self.assertEqual(sent[0]["room_override"],69118545)
        self.assertNotIn(account["id"],app._bot_pending_room)

    def test_existing_authenticated_profile_does_not_log_in_again(self):
        app,account,sent,calls=fake_app(connected=True)
        SCOPE["_bot_run_account"](app,account)
        self.assertEqual(calls,[])
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0]["room_override"],69118545)

    def test_stale_generation_or_profile_selection_does_not_join(self):
        app,account,sent,calls=fake_app()
        SCOPE["_bot_run_account"](app,account)
        app._tcp_sessions[account["id"]]=SimpleNamespace(
            authenticated=True,stop=SimpleNamespace(is_set=lambda:False))
        SCOPE["_bot_dispatch_pending_room"](app,account["id"],2)
        self.assertEqual(sent,[])
        # The generation mismatch consumed the old pending request.
        SCOPE["_bot_dispatch_pending_room"](app,account["id"],3)
        self.assertEqual(sent,[])
        SCOPE["_bot_run_account"](app,account)
        self.assertEqual(len(sent),1)
        self.assertFalse(app._bot_pending_room)

    def test_one_click_is_exposed_in_both_pages_and_no_auto_join_on_startup(self):
        ui=ast.get_source_segment(SOURCE,METHODS["_make_clientless_bot_panel"])
        accounts=ast.get_source_segment(SOURCE,METHODS["_make_accounts_panel"])
        self.assertIn("<<ComboboxSelected>>",ui)
        self.assertIn("command=self._bot_run_selected",ui)
        self.assertIn("command=self._bot_run_from_accounts",accounts)
        self.assertIn("clientless_standalone=True",SOURCE)
        self.assertIn("clientless-only mode",SOURCE)
        init=ast.get_source_segment(SOURCE,METHODS["__init__"])
        self.assertNotIn("self._bot_run_selected()",init)

    def test_do_not_auto_start_gearth_and_preserve_manual_opt_in(self):
        code=ast.get_source_segment(SOURCE,METHODS["_auto_prepare_gearth"])
        self.assertIn("bot_standalone_var",code)
        self.assertIn("clientless-only mode",code)
        app=SimpleNamespace(bot_standalone_var=Var(True),config={},
                            save=lambda:None,bot_status_var=Var(""))
        SCOPE["_bot_standalone_changed"](app)
        self.assertIs(app.config["clientless_standalone"],True)
        app.bot_standalone_var.set(False)
        SCOPE["_bot_standalone_changed"](app)
        self.assertIs(app.config["clientless_standalone"],False)


if __name__=="__main__":
    unittest.main()
