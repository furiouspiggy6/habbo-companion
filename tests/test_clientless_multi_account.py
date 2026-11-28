"""Multi-account clientless smoke tests without network, SSO, AIR, or G-Earth.

Assertions cover simultaneous independent pending room joins and walking state,
explicit Direct TCP routing when a separate G-Earth session exists, selecting
and disconnecting only highlighted accounts, and canceled queued launches.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/"Habbo_Companion.pyw").read_text(encoding="utf-8")
TREE=ast.parse(SOURCE)
APP=next(n for n in TREE.body if isinstance(n,ast.ClassDef)
         and n.name=="ChatOverlayApp")
METHODS={n.name:n for n in APP.body if isinstance(n,ast.FunctionDef)}
NAMES=("_bot_multi_refresh","_bot_multi_tick","_bot_multi_selected",
       "_bot_multi_select_all","_bot_multi_run_selected","_bot_multi_run_one",
       "_bot_multi_disconnect_selected","_bot_run_account",
       "_bot_dispatch_pending_room")
SCOPE={"clientless_saved_room_value":
       lambda val:str(val) if str(val).isdigit() and 1<=int(val)<=2147483647
       else "69118545"}
exec(compile(ast.Module(body=[METHODS[n] for n in NAMES],
        type_ignores=[]),"clientless-multi-account","exec"),SCOPE)

IDS=("abcdef111111","abcdef222222","abcdef333333")
LABELS=("First","Second","Third")

class Var:
    def __init__(self,value):self.value=value
    def set(self,value):self.value=value
    def get(self):return self.value

class Root:
    def __init__(self):self.callbacks=[]
    def after(self,millis,callback):
        self.callbacks.append((millis,callback))

class Tree:
    def __init__(self):
        self.rows={}
        self.highlight=()
        self.exists=True
    def winfo_exists(self):return self.exists
    def selection(self):return self.highlight
    def get_children(self,path=""):return tuple(self.rows)
    def delete(self,key):self.rows.pop(key,None)
    def insert(self,parent,where,iid=None,text="",values=()):
        self.rows[iid]=(text,values)
    def selection_set(self,keys):
        if isinstance(keys,str):keys=(keys,)
        self.highlight=tuple(keys)

def fixture():
    accounts=[{"id":ident,"label":name} for ident,name in zip(IDS,LABELS)]
    calls=[]
    app=SimpleNamespace(
        _account_profiles=accounts,
        _tcp_sessions={},
        _tcp_inflight=set(),
        _tcp_generation={},
        _tcp_states={},
        _bot_pending_room={},
        _bot_walk_plans={},
        _bot_gearth_bridges={},
        _bot_multi_direct_ids=set(),
        _bot_run_room_targets={},
        _bot_multi_start_generation=0,
        _bot_multi_ui_generation=1,
        bot_room_var=Var("69118545"),
        bot_status_var=Var(""),
        bot_multi_status_var=Var(""),
        bot_gearth_var=Var(False),
        bot_gearth_status_var=Var(""),
        bot_multi_tree=Tree(),
        root=Root(),
        _tcp_render=lambda:None,
        _bot_send_action=lambda **kwargs:calls.append(("action",kwargs)),
        _bot_start_gearth_bridge=lambda ident:calls.append(
            ("unexpected-G-Earth",ident)),
    )
    def connect(account,auto_capture=False):
        calls.append(("connect",account["id"],auto_capture))
        if auto_capture:
            app._tcp_inflight.add(account["id"])
            app._tcp_generation[account["id"]]=(
                app._tcp_generation.get(account["id"],0)+1)
    def disconnect(ident):
        calls.append(("disconnect",ident))
        app._tcp_sessions.pop(ident,None)
        app._tcp_inflight.discard(ident)
        app._bot_pending_room.pop(ident,None)
        app._bot_walk_plans.pop(ident,None)
        app._bot_multi_direct_ids.discard(ident)
    app._tcp_connect_one=connect
    app._tcp_disconnect_one=disconnect
    for name in NAMES:
        setattr(app,name,SCOPE[name].__get__(app))
    app._bot_multi_refresh()
    return app,accounts,calls

def execute_pending(root):
    scheduled=root.callbacks[:]
    root.callbacks.clear()
    for _,callback in scheduled:
        callback()
    return scheduled

class MultiRunnerTests(unittest.TestCase):
    def test_select_all_is_selection_only_not_autorun(self):
        app,accounts,calls=fixture()
        app._bot_multi_select_all()
        self.assertEqual(set(app.bot_multi_tree.selection()),set(IDS))
        self.assertEqual(calls,[])
        self.assertEqual(len(app.bot_multi_tree.rows),3)
        self.assertIn("3 profiles",app.bot_multi_status_var.get())

    def test_two_accounts_start_with_independent_generation_and_room(self):
        app,accounts,calls=fixture()
        app.bot_multi_tree.selection_set((IDS[0],IDS[1]))
        app._bot_multi_run_selected()
        scheduled=execute_pending(app.root)
        self.assertEqual([ms for ms,_ in scheduled],[0,1200])
        self.assertEqual(set(app._bot_pending_room),set(IDS[:2]))
        self.assertEqual(app._bot_pending_room[IDS[0]],(1,69118545))
        self.assertEqual(app._bot_pending_room[IDS[1]],(1,69118545))
        self.assertEqual(app._bot_multi_direct_ids,set(IDS[:2]))
        self.assertEqual(
            [(v[1],v[2]) for v in calls if v[0]=="connect"],
            [(IDS[0],False),(IDS[0],True),
             (IDS[1],False),(IDS[1],True)])
        self.assertEqual([v for v in calls if v[0]=="unexpected-G-Earth"],[])

    def test_starting_second_does_not_cancel_first_walk_or_join(self):
        app,accounts,calls=fixture()
        app._bot_walk_plans[IDS[0]]={"phase":"walking","room":69118545}
        app._bot_pending_room[IDS[0]]=(3,69118545)
        app.bot_multi_tree.selection_set((IDS[1],))
        app._bot_multi_run_selected()
        execute_pending(app.root)
        self.assertEqual(app._bot_walk_plans[IDS[0]]["phase"],"walking")
        self.assertEqual(app._bot_pending_room[IDS[0]],(3,69118545))
        self.assertIn(IDS[1],app._bot_pending_room)

    def test_typed_room_captured_before_staggered_start(self):
        app,accounts,calls=fixture()
        app.bot_multi_tree.selection_set((IDS[0],IDS[1]))
        app.bot_room_var.set("12345")
        app._bot_multi_run_selected()
        app.bot_room_var.set("69118545")
        execute_pending(app.root)
        self.assertEqual(app._bot_run_room_targets[IDS[0]],12345)
        self.assertEqual(app._bot_run_room_targets[IDS[1]],12345)

    def test_one_gearth_session_can_coexist_with_bulk_direct(self):
        app,accounts,calls=fixture()
        session=SimpleNamespace(authenticated=True,
            stop=SimpleNamespace(is_set=lambda:False))
        app._tcp_sessions[IDS[0]]=session
        app._bot_gearth_bridges[IDS[0]]=SimpleNamespace(ready=True)
        app.bot_gearth_var.set(True)
        app.bot_multi_tree.selection_set(IDS)
        app._bot_multi_run_selected()
        execute_pending(app.root)
        self.assertEqual(set(app._bot_multi_direct_ids),set(IDS[1:]))
        self.assertNotIn(IDS[0],app._bot_multi_direct_ids)
        self.assertEqual(set(app._bot_pending_room),set(IDS[1:]))
        self.assertEqual([x for x in calls if x[0]=="unexpected-G-Earth"],[])
        self.assertIn("G-Earth",app.bot_multi_tree.rows[IDS[0]][1][0])

    def test_existing_sessions_not_rejoined_or_replaced(self):
        app,accounts,calls=fixture()
        app._tcp_sessions[IDS[0]]=SimpleNamespace(
            authenticated=True,stop=SimpleNamespace(is_set=lambda:False))
        app.bot_multi_tree.selection_set(IDS[:2])
        app._bot_multi_run_selected()
        execute_pending(app.root)
        self.assertEqual(set(app._bot_pending_room),{IDS[1]})
        self.assertEqual([x for x in calls if x[0]=="action"],[])
        self.assertEqual([x for x in calls if x[0]=="connect" and x[1]==IDS[0]],[])

    def test_selective_disconnect_cancels_queued_launches(self):
        app,accounts,calls=fixture()
        app.bot_multi_tree.selection_set(IDS)
        app._bot_multi_run_selected()
        original=app.root.callbacks[:]
        app.bot_multi_tree.selection_set((IDS[0],))
        app._bot_multi_disconnect_selected()
        for _,callback in original:callback()
        self.assertEqual([x for x in calls if x[0]=="connect"],[])
        self.assertEqual([x for x in calls if x[0]=="disconnect"],[("disconnect",IDS[0])])
        self.assertIn("other accounts remain",app.bot_multi_status_var.get())

    def test_invalid_or_empty_selection_does_not_launch(self):
        app,accounts,calls=fixture()
        app._bot_multi_run_selected()
        self.assertEqual(app.root.callbacks,[])
        app.bot_multi_tree.selection_set(IDS[:2])
        app.bot_room_var.set("bad-room")
        app._bot_multi_run_selected()
        self.assertEqual(app.root.callbacks,[])
        self.assertIn("valid numeric Room ID",app.bot_multi_status_var.get())

    def test_ui_routes_bulk_commands_only_on_explicit_click(self):
        ui=ast.get_source_segment(SOURCE,METHODS["_make_clientless_bot_panel"])
        accounts=ast.get_source_segment(SOURCE,METHODS["_make_accounts_panel"])
        self.assertIn("selectmode='extended'",accounts)
        self.assertIn("command=self._bot_multi_run_selected",accounts)
        self.assertIn("command=self._bot_multi_disconnect_selected",accounts)
        self.assertNotIn("command=self._bot_multi_run_selected",ui)
        self.assertNotIn("command=self._bot_run_selected",ui)
        self.assertIn("Save positions for current account",ui)

if __name__=="__main__":
    unittest.main()
