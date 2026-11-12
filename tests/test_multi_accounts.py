"""Multiple independent Habbo browser logins and safe G-Earth port selection."""
import ast
from pathlib import Path
from types import SimpleNamespace
import re
import urllib.parse
import unittest
from unittest import mock

APP=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
SOURCE=APP.read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)
names={'normalize_habbo_accounts','validate_habbo_login_url','account_browser_command'}
nodes=[x for x in TREE.body if isinstance(x,ast.FunctionDef) and x.name in names]
ns={'re':re,'urllib':SimpleNamespace(parse=urllib.parse),'Path':Path}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(APP),'exec'),ns)
norm=ns['normalize_habbo_accounts']
validate=ns['validate_habbo_login_url']
command=ns['account_browser_command']
CLS=next(x for x in TREE.body if isinstance(x,ast.ClassDef)
         and x.name=='ChatOverlayApp')

class Var:
    def __init__(self,value=None):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class Table:
    def __init__(self,ident):self.ident=ident;self.inserted={}
    def selection(self):return (self.ident,)

def method(name):
    node=next(x for x in CLS.body if isinstance(x,ast.FunctionDef) and x.name==name)
    scope={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(APP),'exec'),scope)
    return scope[name]

class MultiAccountTests(unittest.TestCase):
    def test_profiles_are_safe_and_do_not_store_passwords(self):
        profiles=[
            {'id':'ab1234567890','label':'Main','port':9092,
             'url':'https://www.habbo.com/','password':'SECRET'},
            {'id':'cd1234567890','label':'Alt','port':9093,
             'url':'https://www.habbo.com/'},
            {'id':'ef1234567890','label':'Duplicate port','port':9093,
             'url':'https://www.habbo.com/'}]
        result=norm(profiles)
        self.assertEqual(len(result),2)
        self.assertEqual(result[1]['port'],9093)
        self.assertNotIn('SECRET',str(result))
        self.assertEqual(set(result[0]),{'id','label','port','url'})

    def test_unsafe_saved_profiles_cannot_escape_to_disk_or_conflict(self):
        entries=[
            {'id':'../../bad','label':'Invalid path','port':9092,
             'url':'https://www.habbo.com/'},
            {'id':'ab1234567890','label':'Valid','port':9092,
             'url':'https://www.habbo.com/'},
            {'id':'ab1234567890','label':'Duplicate id','port':9094,
             'url':'https://www.habbo.com/'},
            {'id':'cd1234567890','label':'Password URL','port':9095,
             'url':'https://user:secret@www.habbo.com/'},
            {'id':'ed1234567890','label':'Invalid port','port':80,
             'url':'https://www.habbo.com/'}
        ]
        result=norm(entries)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['label'],'Valid')

    def test_https_required_no_userinfo(self):
        for url in ('http://www.habbo.com',
                    'https://name:password@www.habbo.com/',
                    'https://bad domain.com', 'file:///windows',
                    'https://www.habbo.com:0/', 'https://'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate(url)
        self.assertEqual(validate(' https://www.habbo.com/ '),'https://www.habbo.com/')

    def test_browser_profiles_launch_isolated_with_login_only(self):
        cmd=command(Path('C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'),
                    Path('C:/Users/User/AppData/Roaming/HabboViewChat/account_browser_profiles/ab1234567890'),
                    'https://www.habbo.com/')
        self.assertIn('--new-window',cmd)
        self.assertIn('--no-first-run',cmd)
        self.assertEqual(cmd[-1],'https://www.habbo.com/')
        self.assertEqual(sum(a.startswith('--user-data-dir=') for a in cmd),1)
        self.assertNotIn('--incognito',cmd)

    def test_cannot_switch_packet_ports_while_active(self):
        obj=SimpleNamespace(
            account_table=Table('cd1234567890'),
            _account_profiles=[{'id':'cd1234567890','label':'Alt',
                                'port':9093,'url':'https://www.habbo.com/'}],
            _account_active_id='ab1234567890',
            packet_started=True,_account_attached_port=9092,
            account_status_var=Var(''),
            gearth_port_var=Var('9092'),
            config={'gearth_port':9092},
            save=lambda:None)
        obj._account_selected=lambda:obj._account_profiles[0]
        method('_account_use_port')(obj)
        self.assertEqual(obj.gearth_port_var.value,'9092')
        self.assertEqual(obj._account_active_id,'ab1234567890')
        self.assertIn('Restart Companion',obj.account_status_var.value)

    def test_one_account_per_packet_connection_and_no_password_fields(self):
        code=SOURCE
        self.assertIn('self._account_attached_port=port',code)
        self.assertIn("self.notebook.add(accounts,text='  Accounts  ')",code)
        self.assertIn('account_login_browser()',code)
        self.assertIn('account_browser_command(browser,folder,account[\'url\'])',code)
        self.assertIn('one G-Earth',code.lower().replace('ONE G-Earth','one G-Earth'))
        self.assertNotIn('self.account_password_var',code)

if __name__=='__main__':
    unittest.main()
