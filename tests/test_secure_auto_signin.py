"""Offline tests for automatic Habbo website login via Windows credential vault."""
import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)

FUNCTIONS={
    '_account_credential_target','account_submit_saved_login',
    'account_login_input_confirmed','account_login_field_action',
    'account_attempt_auto_play'
}


def scope():
    nodes=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in FUNCTIONS]
    space={'re':re,'json':json}
    for node in TREE.body:
        if (isinstance(node,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id=='HABBO_LOGIN_FIELDS_JS'
            for t in node.targets)):
            space['HABBO_LOGIN_FIELDS_JS']=ast.literal_eval(node.value)
        if (isinstance(node,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id=='HABBO_LOGIN_INPUT_READY_JS'
            for t in node.targets)):
            space['HABBO_LOGIN_INPUT_READY_JS']=ast.literal_eval(node.value)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),space)
    return space


class AutoSigninTests(unittest.TestCase):
    def test_vault_key_is_stable_and_rejects_path_escape(self):
        fn=scope()['_account_credential_target']
        self.assertEqual(fn('AB1234567890'),
                         'HabboCompanion:login:ab1234567890')
        for bad in ('../../bad','foo','ab1234567890/../other'):
            with self.assertRaises(ValueError):
                fn(bad)

    def test_login_form_inspection_stays_within_habbo_and_does_not_read_secrets(self):
        nodes=[n for n in TREE.body if isinstance(n,ast.Assign) and
               any(isinstance(t,ast.Name) and t.id=='HABBO_LOGIN_FIELDS_JS'
                   for t in n.targets)]
        self.assertEqual(len(nodes),1)
        js=ast.literal_eval(nodes[0].value)
        self.assertIn("location.protocol",js)
        self.assertIn(r"/(^|\.)habbo\.com$/i",js)
        self.assertIn("input[type=password]",js)
        self.assertIn("let'?s go",js)
        self.assertNotIn('document.cookie',js)
        self.assertNotIn('localStorage',js)
        self.assertNotIn('sessionStorage',js)
        self.assertNotIn('.value=',js)

    def test_cdp_types_only_into_approved_inspected_fields(self):
        a=scope()
        sent=[]
        clicks=[]
        calls={'n':0}
        def cdp(url,method,params):
            sent.append((url,method,params))
            if method=='Runtime.evaluate':
                expression=params['expression']
                if 'const field=' in expression:
                    field='password' if 'const field="password"' in expression else 'email'
                    return {'result':{'value':{'kind':'populated','field':field}}}
                return {'result':{'value':{
                    'kind':'form','email':{'x':10,'y':30},
                    'password':{'x':20,'y':40},
                    'submit':{'x':80,'y':90}}}}
            return {}
        a['account_cdp_call']=cdp
        a['time']=SimpleNamespace(sleep=lambda _:None)
        a['account_click_play_button']=lambda url,step:clicks.append(step)
        diagnostics=[]
        a['account_submit_with_network_diagnostics']=lambda ws,report:(
            diagnostics.append('DOM submit') or True)
        self.assertTrue(a['account_submit_saved_login'](
            'ws://127.0.0.1:44321/devtools/page/abc','email@example.com',
            'super-secret-password'))
        values=[entry[2]['text'] for entry in sent if entry[1]=='Input.insertText']
        self.assertEqual(values,['email@example.com','super-secret-password'])
        self.assertEqual(clicks,[{'x':10,'y':30},{'x':20,'y':40}])
        self.assertEqual(diagnostics,['DOM submit'])
        self.assertEqual(sent[0][1],'Runtime.evaluate')
        self.assertNotIn('super-secret-password',sent[0][2]['expression'])

    def test_does_not_click_submit_when_field_input_not_confirmed(self):
        a=scope()
        clicks=[]
        inserted=[]
        responses={'n':0}
        def cdp(url,method,params):
            if method=='Runtime.evaluate':
                responses['n']+=1
                if responses['n']==1:
                    return {'result':{'value':{
                        'kind':'form','email':{'x':10,'y':20},
                        'password':{'x':10,'y':50},
                        'submit':{'x':10,'y':90}}}}
                return {'result':{'value':{'kind':'not-focused'}}}
            if method=='Input.insertText':
                inserted.append(params['text'])
            return {}
        a['account_cdp_call']=cdp
        a['time']=SimpleNamespace(sleep=lambda _:None)
        a['account_click_play_button']=lambda ws,step:clicks.append(step)
        self.assertFalse(a['account_submit_saved_login'](
            'ws://127.0.0.1:44321/devtools/page/abc',
            'user@example.com','not-a-real-password'))
        self.assertEqual(inserted,['user@example.com'])
        self.assertNotIn({'x':10,'y':90},clicks)
        self.assertEqual(len(clicks),1)

    def test_input_ready_status_returns_only_boolean(self):
        a=scope()
        events=[]
        def cdp(ws,method,params):
            events.append(params)
            return {'result':{'value':{'kind':'populated','field':'password'}}}
        a['account_cdp_call']=cdp
        self.assertTrue(a['account_login_input_confirmed']('ws','password'))
        self.assertFalse(a['account_login_input_confirmed']('ws','email'))
        self.assertNotIn('super-secret-password',str(events))
        self.assertNotIn('value=',str(events))

    def test_does_not_enter_password_when_form_not_verified(self):
        a=scope()
        methods=[]
        a['account_cdp_call']=lambda url,method,params:(
            methods.append(method) or {'result':{'value':{'kind':'not_habbo'}}})
        a['account_click_play_button']=lambda *_:self.fail('unexpected click')
        self.assertFalse(a['account_submit_saved_login'](
            'ws://127.0.0.1:44321/devtools/page/abc','email@example.com','secret'))
        self.assertEqual(methods,['Runtime.evaluate'])

    def test_saved_login_auto_signin_and_play_continue(self):
        a=scope()
        page={'url':'https://www.habbo.com/',
              'webSocketDebuggerUrl':'ws://127.0.0.1:44321/devtools/page/abc'}
        a['account_habbo_page']=lambda port:page
        steps=iter([
            {'kind':'login'},
            {'kind':'play','label':'Play','x':20,'y':40,'page':'/'},
            {'kind':'launch','label':'Launch and log in','x':30,'y':50,'page':'/'}
        ])
        a['account_inspect_play_page']=lambda url:next(steps)
        typed=[]
        a['account_submit_saved_login']=lambda ws,email,password,report=None:(
            typed.append((email,password)) or True)
        clicked=[]
        a['account_click_play_button']=lambda ws,step:clicked.append(step['kind'])
        a['time']=SimpleNamespace(sleep=lambda _:None)
        reports=[]
        result=a['account_attempt_auto_play'](
            44321,reports.append,('e@example.com','password1'))
        self.assertEqual(result,'launched')
        self.assertEqual(typed,[('e@example.com','password1')])
        self.assertEqual(clicked,['play','launch'])
        self.assertNotIn('password1',' '.join(reports))

    def test_open_login_signs_in_without_clicking_play(self):
        a=scope()
        a['account_habbo_page']=lambda port:{
            'url':'https://www.habbo.com/',
            'webSocketDebuggerUrl':'ws://127.0.0.1:44321/devtools/page/abc'}
        steps=iter([{'kind':'login'},
                    {'kind':'play','x':20,'y':40,'page':'/'}])
        a['account_inspect_play_page']=lambda url:next(steps)
        a['account_submit_saved_login']=lambda *_,**kwargs:True
        a['account_click_play_button']=lambda *_:self.fail('should not click Play')
        a['time']=SimpleNamespace(sleep=lambda _:None)
        reports=[]
        self.assertEqual(a['account_attempt_auto_play'](
            44321,reports.append,('e@example.com','password1'),True),
            'signed_in')

    def test_failed_login_does_not_repeat_password_submission(self):
        a=scope()
        a['account_habbo_page']=lambda port:{
            'url':'https://www.habbo.com/',
            'webSocketDebuggerUrl':'ws://127.0.0.1:44321/devtools/page/abc'}
        a['account_inspect_play_page']=lambda url:{'kind':'login'}
        count=[]
        a['account_submit_saved_login']=lambda *_,**kwargs:(count.append(1) or True)
        a['time']=SimpleNamespace(sleep=lambda _:None)
        a['account_login_diagnostic']=lambda ws:'still-on-form'
        reports=[]
        self.assertEqual(a['account_attempt_auto_play'](
            44321,reports.append,('e@example.com','wrongsecret')),'login')
        self.assertEqual(len(count),1)
        self.assertIn('login form',reports[-1].lower())
        self.assertNotIn('wrongsecret',' '.join(reports))

    def test_plaintext_password_is_not_a_profile_setting(self):
        self.assertIn("api.CredWriteW",TEXT)
        self.assertIn("api.CredReadW",TEXT)
        self.assertIn("api.CredDeleteW",TEXT)
        self.assertIn("record.Persist=2",TEXT)
        settings=TEXT.split('DEFAULT = dict(',1)[1].split('THEMES =',1)[0]
        self.assertNotIn('password=',settings)
        self.assertNotIn('account_email=',settings)
        self.assertIn('self.account_password_var.set',TEXT)


if __name__=='__main__':
    unittest.main()
