"""Offline security and behaviour tests for element-based login + CDP monitor."""
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
import urllib.parse

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))
NAMES={'account_login_auth_request','account_login_safe_error_code',
       'AccountLoginNetworkProbe','account_focus_and_submit_login',
       'account_submit_with_network_diagnostics'}


def scope():
    nodes=[n for n in TREE.body if (
        isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in NAMES)]
    values={'json':json,'re':re,'urllib':SimpleNamespace(parse=urllib.parse),
            'time':time,'socket':__import__('socket')}
    for n in TREE.body:
        if (isinstance(n,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id=='HABBO_LOGIN_SUBMIT_FOCUS_JS'
            for t in n.targets)):
            values['HABBO_LOGIN_SUBMIT_FOCUS_JS']=ast.literal_eval(n.value)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),
         values)
    return values


class NetworkClassificationTests(unittest.TestCase):
    def test_observes_only_first_party_login_requests(self):
        fn=scope()['account_login_auth_request']
        self.assertTrue(fn('https://www.habbo.com/api/auth/login','POST'))
        self.assertTrue(fn('https://api.habbo.com/api/public/authentication','POST'))
        self.assertTrue(fn('https://habbo.com/sso/session','POST'))
        self.assertFalse(fn('https://www.habbo.com/api/auth/login','GET'))
        self.assertFalse(fn('https://evil.example/api/auth/login','POST'))
        self.assertFalse(fn('https://habbo.com.evil.example/auth/login','POST'))
        self.assertFalse(fn('http://habbo.com/auth/login','POST'))
        self.assertFalse(fn('https://www.habbo.com/api/news','POST'))

    def test_symbolic_server_error_code_only(self):
        fn=scope()['account_login_safe_error_code']
        self.assertEqual(fn('{"error":{"code":"INVALID_CREDENTIALS"},'
                            '"email":"user@example.com"}'),
                         'INVALID_CREDENTIALS')
        self.assertEqual(fn('{"errorCode":"VERIFY_EMAIL"}'),'VERIFY_EMAIL')
        self.assertIsNone(fn('{"code":"user@example.com"}'))
        self.assertIsNone(fn('{"code":"eyJhbGciOiJIUzI1NiJ9"}'))
        self.assertIsNone(fn('{"message":"password is not right"}'))
        self.assertIsNone(fn('not JSON'))

    def test_monitor_reports_http_without_url_body_headers_or_tokens(self):
        cls=scope()['AccountLoginNetworkProbe']
        probe=cls('ws://127.0.0.1:44000/devtools/page/abc')
        request={
            'method':'Network.requestWillBeSent',
            'params':{'requestId':'req1','request':{
                'method':'POST',
                'url':'https://www.habbo.com/api/auth/login?email=secret@example.com',
                'headers':{'Cookie':'session.id=secret'},
                'postData':'{"password":"TOPSECRET"}'}}}
        probe._event(request)
        probe._event({'method':'Network.responseReceived',
                      'params':{'requestId':'req1',
                                'response':{'status':403,
                                            'mimeType':'application/json'}}})
        probe._event({'method':'Network.loadingFinished',
                      'params':{'requestId':'req1'}})
        probe.error_code='INVALID_CREDENTIALS'
        msg=probe.summary()
        self.assertIn('HTTP 403',msg)
        self.assertIn('INVALID_CREDENTIALS',msg)
        for secret in ('TOPSECRET','secret@example.com','session.id=secret',
                       'api/auth/login'):
            self.assertNotIn(secret,msg)
        self.assertEqual(probe.finished_id,'req1')

    def test_external_login_request_not_observed(self):
        cls=scope()['AccountLoginNetworkProbe']
        probe=cls('ws://127.0.0.1:44000/devtools/page/abc')
        probe._event({'method':'Network.requestWillBeSent',
                      'params':{'requestId':'another',
                                'request':{'method':'POST',
                                           'url':'https://private.example.com/login'}}})
        self.assertFalse(probe.seen)
        self.assertIn('no matching first-party',probe.summary())


class DomSubmissionTests(unittest.TestCase):
    def test_keyboard_enter_on_dom_focused_submit_never_uses_mouse_coords(self):
        ns=scope()
        calls=[]
        def cdp(ws,method,params):
            calls.append((method,params))
            if method=='Runtime.evaluate':
                return {'result':{'value':{'kind':'focused'}}}
            return {}
        ns['account_cdp_call']=cdp
        self.assertTrue(ns['account_focus_and_submit_login']('ws'))
        self.assertEqual([method for method,_ in calls],
                         ['Runtime.evaluate','Input.dispatchKeyEvent',
                          'Input.dispatchKeyEvent'])
        self.assertEqual([p['key'] for m,p in calls if m=='Input.dispatchKeyEvent'],
                         ['Enter','Enter'])
        self.assertNotIn('dispatchMouseEvent',str(calls))

    def test_unverified_submit_never_sends_enter(self):
        ns=scope()
        calls=[]
        ns['account_cdp_call']=lambda ws,method,params:(
            calls.append(method) or {'result':{'value':{'kind':'unverified-page'}}})
        self.assertFalse(ns['account_focus_and_submit_login']('ws'))
        self.assertEqual(calls,['Runtime.evaluate'])

    def test_monitor_is_enabled_before_single_dom_submission(self):
        ns=scope()
        events=[]
        class FakeProbe:
            def __init__(self,ws):
                events.append('open')
            def __enter__(self):
                events.append('enter')
                return self
            def __exit__(self,*args):
                events.append('close')
            def enable(self):
                events.append('enable')
            def observe(self):
                events.append('observe')
            def summary(self):
                return 'Login diagnostic: Habbo authentication HTTP 403.'
        ns['AccountLoginNetworkProbe']=FakeProbe
        ns['account_focus_and_submit_login']=lambda ws:(
            events.append('submit') or True)
        messages=[]
        self.assertTrue(ns['account_submit_with_network_diagnostics'](
            'ws',messages.append))
        self.assertEqual(events,['open','enter','enable','submit','observe','close'])
        self.assertIn('HTTP 403',messages[0])

    def test_monitor_cannot_cause_second_submission_after_click(self):
        ns=scope()
        calls=[]
        class BrokenProbe:
            def __init__(self,ws): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def enable(self): pass
            def observe(self): raise OSError('observer dropped')
        ns['AccountLoginNetworkProbe']=BrokenProbe
        ns['account_focus_and_submit_login']=lambda ws:(
            calls.append('submit') or True)
        messages=[]
        self.assertTrue(ns['account_submit_with_network_diagnostics'](
            'ws',messages.append))
        self.assertEqual(calls,['submit'])
        self.assertTrue(any('interrupted' in m for m in messages))


if __name__=='__main__':
    unittest.main()
