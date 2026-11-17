"""Playwright controller tests using a fake browser (never contact Habbo)."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
import urllib.parse

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)


def scope(*names):
    nodes=[n for n in TREE.body if (
        isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names)]
    found={n.name for n in nodes}
    if found!=set(names):
        raise AssertionError('Playwright source function missing')
    variables={'re':re,'urllib':SimpleNamespace(parse=urllib.parse)}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),
         variables)
    return variables


class FakeElement:
    def __init__(self,logs,role,clicked=None,blocked=False):
        self.logs=logs
        self.role=role
        self.clicked=clicked
        self.blocked=blocked
    def fill(self,value,timeout):
        self.logs.append(('fill',self.role,value,timeout))
    def evaluate(self,js):
        return True
    def click(self,timeout):
        self.logs.append(('click',self.role,timeout))
        if self.blocked:
            raise RuntimeError('intercepts pointer events')
        if self.clicked:
            self.clicked()
    def wait_for(self,state,timeout):
        self.logs.append(('wait',self.role,state,timeout))
    @property
    def first(self):
        return self


class FakePage:
    def __init__(self,logs):
        self.url='https://www.habbo.com/'
        self.logs=logs
        self.context=SimpleNamespace()
        self.password_visible=True
        self.signed_in=False
    def locator(self,selector):
        return FakeElement(self.logs,'password-wait')


class FakeManager:
    def __init__(self,logs):
        self.logs=logs
    def __enter__(self):
        self.logs.append(('start-playwright',))
        chromium=SimpleNamespace(connect_over_cdp=self.connect)
        return SimpleNamespace(chromium=chromium)
    def connect(self,url,timeout):
        self.logs.append(('connect',url,timeout))
        return SimpleNamespace()
    def __exit__(self,*args):
        self.logs.append(('stop-playwright',))


class FakeMonitor:
    def __init__(self,page,report):
        self.report=report
    def start(self): pass
    def finish(self):
        self.report('Login network: 0 request(s), 0 HTTP response(s), 0 failures.')
    def stop(self): pass


def simulated_controller(blocked=False,no_credentials=False):
    ns=scope('account_playwright_auto_play',
             'account_playwright_is_official',
             'account_playwright_safe_error')
    calls=[]
    page=FakePage(calls)
    email=FakeElement(calls,'email')
    password=FakeElement(calls,'password')
    def after_click():
        page.password_visible=False
        page.signed_in=True
    submit=FakeElement(calls,'submit',after_click,blocked)
    messages=[]
    ns.update({
        'account_playwright_engine':lambda report:lambda:FakeManager(calls),
        'account_playwright_select_page':lambda browser:page,
        'account_playwright_login_form':lambda p:(
            (email,password,submit) if page.password_visible else None),
        'account_playwright_control':lambda p,kind:(
            FakeElement(calls,'play') if page.signed_in and kind=='play' else None),
        'account_playwright_session_hint':lambda ctx:False,
        'account_playwright_visible':lambda loc:page.password_visible,
        'AccountPlaywrightMonitor':FakeMonitor,
    })
    creds=None if no_credentials else ('user@example.com','PRIVATE_PASSWORD')
    result=ns['account_playwright_auto_play'](
        43111,messages.append,credentials=creds,login_only=True)
    return result,calls,messages


class PlaywrightRoutingTests(unittest.TestCase):
    def test_runtime_account_browser_flow_is_playwright_not_legacy(self):
        self.assertIn('account_attempt_auto_play=account_playwright_auto_play',
                      TEXT)
        self.assertIn('chromium.connect_over_cdp(',TEXT)
        self.assertIn('submit.click(timeout=10000)',TEXT)
        self.assertNotIn('submit.click(force=True)',TEXT)
        self.assertIn('--target',TEXT)
        self.assertIn("playwright=='+_ACCOUNT_PLAYWRIGHT_VERSION",TEXT)
        self.assertIn("1.65.2",TEXT)

    def test_browser_uses_saved_local_profile_port_and_locator_fill(self):
        result,calls,messages=simulated_controller()
        self.assertEqual(result,'signed_in')
        self.assertIn(('connect','http://127.0.0.1:43111',12000),calls)
        self.assertEqual([step[1] for step in calls if step[0]=='fill'],
                         ['email','password'])
        self.assertEqual([step[1] for step in calls if step[0]=='click'],
                         ['submit'])
        self.assertIn('Login button clicked', ' '.join(messages))
        self.assertNotIn('PRIVATE_PASSWORD',' '.join(messages))
        self.assertNotIn('user@example.com',' '.join(messages))

    def test_blocked_click_never_force_clicks_or_retries_password(self):
        result,calls,messages=simulated_controller(blocked=True)
        self.assertEqual(result,'login')
        self.assertEqual(len([x for x in calls if x[0]=='click']),1)
        self.assertIn('intercepts', ' '.join(messages))
        self.assertNotIn('PRIVATE_PASSWORD',' '.join(messages))
        self.assertNotIn('user@example.com',' '.join(messages))

    def test_unsaved_credentials_do_not_touch_fields(self):
        result,calls,messages=simulated_controller(no_credentials=True)
        self.assertEqual(result,'login')
        self.assertFalse([step for step in calls if step[0] in ('fill','click')])
        self.assertIn('Save an email/password',' '.join(messages))

    def test_official_origin_lock_rejects_lookalikes(self):
        ns=scope('account_playwright_is_official')
        official=ns['account_playwright_is_official']
        self.assertTrue(official('https://www.habbo.com/'))
        self.assertTrue(official('https://habbo.com/login'))
        self.assertFalse(official('http://www.habbo.com/'))
        self.assertFalse(official('https://habbo.com.attacker.example/login'))
        self.assertFalse(official('https://www.habbo.com:8443/login'))
        self.assertFalse(official('https://evil.example/'))

    def test_generic_browser_error_never_includes_page_html(self):
        ns=scope('account_playwright_safe_error')
        safe=ns['account_playwright_safe_error']
        error=RuntimeError(
            'Timeout while password=PRIVATE_SECRET: <div>intercepts pointer events</div>')
        self.assertIn('intercepts',safe(error))
        self.assertNotIn('PRIVATE_SECRET',safe(error))


class BrowserMonitoringTests(unittest.TestCase):
    def test_request_status_and_allowed_server_error_are_redacted(self):
        ns=scope('AccountPlaywrightMonitor')
        ns['account_playwright_is_official']=lambda url:url.startswith(
            'https://www.habbo.com/')
        ns['account_login_safe_endpoint_path']=lambda url:'/api/auth/login'
        ns['account_login_safe_error_code']=lambda body:'INVALID_CREDENTIALS'
        ns['account_login_safe_server_message']=lambda body:'Invalid credentials'
        ns['account_login_safe_browser_error']=lambda text:'TypeError'
        calls={}
        class EventSource:
            def on(self,name,func):
                calls[name]=func
            def remove_listener(self,name,func):pass
        context=EventSource()
        page=EventSource()
        page.context=context
        messages=[]
        mon=ns['AccountPlaywrightMonitor'](page,messages.append)
        mon.start()
        class Req:
            url='https://www.habbo.com/api/auth/login?email=PRIVATE@example.com'
            method='POST'
            resource_type='xhr'
        req=Req()
        calls['request'](req)
        response=SimpleNamespace(
            request=req,status=401,
            headers={'content-type':'application/json','content-length':'99'},
            text=lambda:'{"password":"PRIVATE_PASSWORD","code":"INVALID_CREDENTIALS"}')
        calls['response'](response)
        mon.finish()
        mon.stop()
        output=' '.join(messages)
        self.assertIn('HTTP 401',output)
        self.assertIn('INVALID_CREDENTIALS',output)
        self.assertNotIn('PRIVATE_PASSWORD',output)
        self.assertNotIn('PRIVATE@example.com',output)


if __name__=='__main__':
    unittest.main()
