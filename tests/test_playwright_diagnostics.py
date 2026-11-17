"""Offline tests for safe, high-detail Playwright login diagnostics."""
import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
import urllib.parse

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))


def load(*names):
    nodes=[n for n in TREE.body if isinstance(n,(ast.ClassDef,ast.FunctionDef))
           and n.name in names]
    if len(nodes)!=len(names):
        raise AssertionError('Missing monitored function')
    ns={'json':json,'re':re,'urllib':SimpleNamespace(parse=urllib.parse)}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),ns)
    return ns


def make_monitor():
    ns=load('AccountPlaywrightMonitor','account_playwright_safe_result_flag',
            'account_playwright_safe_service','account_playwright_is_official',
            'account_login_safe_endpoint_path','account_login_safe_error_code',
            'account_login_safe_server_message','account_login_safe_browser_error')
    ns['HABBO_SAFE_URL_PARTS']=frozenset((
        'api','auth','login','session','signin','identity','oauth','verify'))
    events={}
    class Emitter:
        def __init__(self,label):
            self.label=label
        def on(self,name,callback):
            events[(self.label,name)]=callback
        def remove_listener(self,*args):
            pass
    ctx=Emitter('context')
    ctx.cookies=lambda urls:[]
    page=Emitter('page')
    page.context=ctx
    messages=[]
    monitor=ns['AccountPlaywrightMonitor'](page,messages.append)
    monitor.start()
    return monitor,events,messages


def request(url,method='POST',kind='xhr',failure=None):
    return SimpleNamespace(url=url,method=method,resource_type=kind,
                           failure=failure)


def respond(events,req,status=200,body='{}',content_type='application/json'):
    res=SimpleNamespace(request=req,status=status,
        headers={'content-type':content_type,
                 'content-length':str(len(body))},text=lambda:body)
    events[('context','response')](res)
    return res


class PlaywrightDetailedMonitorTests(unittest.TestCase):
    def test_http_200_with_json_denial_is_observed_without_leaking_secrets(self):
        monitor,events,lines=make_monitor()
        req=request('https://www.habbo.com/api/auth/login?email=myuser@example.com')
        events[('context','request')](req)
        respond(events,req,200,'{"success":false,"code":"INVALID_CREDENTIALS",'
                '"message":"Invalid email or password.",'
                '"email":"myuser@example.com","token":"HIDDEN_TOKEN"}')
        events[('context','requestfinished')](req)
        monitor.finish()
        output='\n'.join(lines)
        self.assertIn('HTTP 200',output)
        self.assertIn('success=false',output)
        self.assertIn('INVALID_CREDENTIALS',output)
        self.assertIn('Invalid email or password',output)
        self.assertNotIn('myuser@example.com',output)
        self.assertNotIn('HIDDEN_TOKEN',output)

    def test_response_then_aborted_request_is_not_no_http_response(self):
        monitor,events,lines=make_monitor()
        req=request('https://www.habbo.com/api/auth/login',
                    failure='net::ERR_ABORTED')
        events[('context','request')](req)
        respond(events,req,200,body='{"success":true}')
        events[('context','requestfailed')](req)
        monitor.finish()
        output='\n'.join(lines)
        self.assertIn('transfer interrupted after HTTP 200 (net::ERR_ABORTED)',
                      output)
        self.assertNotIn('request failed before an HTTP response',output)
        self.assertEqual(monitor.failed_after_response,1)

    def test_genuine_network_failure_reports_safe_chromium_reason(self):
        monitor,events,lines=make_monitor()
        req=request('https://www.habbo.com/api/auth/login',
                    failure='net::ERR_CONNECTION_RESET secret=MYTOKEN')
        events[('context','request')](req)
        events[('context','requestfailed')](req)
        monitor.finish()
        output='\n'.join(lines)
        self.assertIn('request failed before an HTTP response',output)
        self.assertIn('net::ERR_CONNECTION_RESET',output)
        self.assertNotIn('MYTOKEN',output)

    def test_external_identity_response_never_reads_body(self):
        monitor,events,lines=make_monitor()
        req=request('https://unknown.example.com/abc/password?code=SECRET')
        events[('context','request')](req)
        res=respond(events,req,403,body='{"code":"PRIVATE_TOKEN"}')
        res.text=lambda: self.fail('External identity response body was read')
        monitor.finish()
        output='\n'.join(lines)
        self.assertIn('HTTP 403',output)
        self.assertIn('external HTTPS',output)
        self.assertNotIn('unknown.example.com',output)
        self.assertNotIn('SECRET',output)
        self.assertNotIn('PRIVATE_TOKEN',output)

    def test_event_budget_preserves_important_login_and_errors(self):
        monitor,events,lines=make_monitor()
        for i in range(140):
            req=request('https://www.habbo.com/api/news/'+str(i),
                        'GET','fetch')
            events[('context','request')](req)
        req=request('https://www.habbo.com/api/auth/login')
        events[('context','request')](req)
        respond(events,req,429,body='{"message":"Too many requests"}')
        monitor.finish()
        output='\n'.join(lines)
        self.assertIn('HTTP 429',output)
        self.assertIn('Too many requests',output)
        self.assertIn('diagnostics omitted',output)

    def test_only_allowlisted_response_outcomes_are_exposed(self):
        fn=load('account_playwright_safe_result_flag')[
            'account_playwright_safe_result_flag']
        self.assertEqual(fn('{"authenticated":false,"token":"SECRET"}'),
                         'authenticated=false')
        self.assertEqual(fn('{"data":{"success":true}}'),'success=true')
        self.assertEqual(fn('{"status":"error","email":"private@site.com"}'),
                         'status=error')
        self.assertIsNone(fn('{"status":"PERSONAL_ACCOUNT_SECRET"}'))
        self.assertIsNone(fn('not json'))

    def test_safe_labels_and_paths_do_not_expose_identity_tokens(self):
        ns=load('account_playwright_safe_service',
                'account_playwright_is_official')
        classify=ns['account_playwright_safe_service']
        self.assertEqual(classify('https://accounts.google.com/login'),
                         'Google identity')
        self.assertEqual(classify('https://unknown.private.example.com/'),
                         'external HTTPS')
        self.assertIsNone(classify('http://accounts.google.com/login'))
        self.assertEqual(classify('https://www.habbo.com/'),'Habbo')


if __name__=='__main__':
    unittest.main()
