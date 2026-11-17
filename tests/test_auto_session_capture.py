"""Direct TCP browser-session import tests. No network, browser or Windows vault."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock
import tempfile
import urllib.parse
import urllib.error
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)
WANTED={'account_capture_habbo_session_cookies',
        'account_import_session_automatically'}
NODES=[node for node in TREE.body
       if isinstance(node,ast.FunctionDef) and node.name in WANTED]
assert len(NODES)==2
CODE=compile(ast.Module(body=NODES,type_ignores=[]),str(SOURCE),'exec')


def execute(**values):
    space={
        'urllib':SimpleNamespace(parse=urllib.parse,error=urllib.error),
        'subprocess':SimpleNamespace(DEVNULL=-3),
        'time':SimpleNamespace(sleep=lambda _:None),
        'APP_DIR':Path('/not-used'),
    }
    space.update(values)
    exec(CODE,space)
    return space


def account():
    return {'id':'abcdef123456','url':'https://www.habbo.com/',
            'label':'Private account'}


def signed_in_page(port=43111):
    return {'url':'https://www.habbo.com/',
            'webSocketDebuggerUrl':
                f'ws://127.0.0.1:{port}/devtools/page/independent',
            '_preflight_step':{'kind':'play'}}


class SessionCookieCapture(TestCase):
    def test_extracts_only_two_secure_official_cookies_including_httponly(self):
        page=signed_in_page()
        calls=[]
        ns=execute(
            account_habbo_page=lambda port:page,
            account_cdp_call=lambda ws,method,params:(
                calls.append((ws,method,params))
                or {'cookies':[
                    {'name':'unrelated','domain':'.habbo.com',
                     'secure':True,'value':'do-not-save'},
                    {'name':'session.id','domain':'.habbo.com','secure':True,
                     'httpOnly':True,'value':'opaque-session'},
                    {'name':'browser_token','domain':'www.habbo.com',
                     'secure':True,'value':'opaque-browser'},
                    {'name':'browser_token','domain':'evil.example',
                     'secure':True,'value':'trap-value'},
                    ]}))
        self.assertEqual(
            ns['account_capture_habbo_session_cookies'](43111),
            ('opaque-session','opaque-browser'))
        self.assertEqual(calls,[(page['webSocketDebuggerUrl'],
                                  'Network.getCookies',
                                  {'urls':['https://www.habbo.com/']})])
        self.assertNotIn('Runtime.evaluate',str(calls))

    def test_rejects_login_page_without_reading_any_cookie(self):
        page=signed_in_page()
        page['_preflight_step']={'kind':'login'}
        ns=execute(account_habbo_page=lambda _:page,
                   account_cdp_call=lambda *_:self.fail('should not read cookies'))
        with self.assertRaisesRegex(ValueError,'not signed in'):
            ns['account_capture_habbo_session_cookies'](43111)

    def test_rejects_other_profile_debug_port(self):
        page=signed_in_page(43112)
        ns=execute(account_habbo_page=lambda _:page,
                   account_cdp_call=lambda *_:self.fail('wrong profile'))
        with self.assertRaisesRegex(ValueError,'isolated local control port'):
            ns['account_capture_habbo_session_cookies'](43111)

    def test_rejects_insecure_or_ambiguous_cookie_values(self):
        page=signed_in_page()
        ns=execute(account_habbo_page=lambda _:page)
        cases=[
            [{'name':'session.id','domain':'.habbo.com','secure':False,'value':'sid'},
             {'name':'browser_token','domain':'.habbo.com','secure':True,'value':'token'}],
            [{'name':'session.id','domain':'.habbo.com','secure':True,'value':'sid'},
             {'name':'session.id','domain':'.habbo.com','secure':True,'value':'sid2'},
             {'name':'browser_token','domain':'.habbo.com','secure':True,'value':'token'}],
            [{'name':'session.id','domain':'.habbo.com','secure':True,'value':'bad;sid'},
             {'name':'browser_token','domain':'.habbo.com','secure':True,'value':'token'}],
        ]
        for cookies in cases:
            with self.subTest(cookies=cookies):
                ns['account_cdp_call']=lambda *a,**k:{'cookies':cookies}
                with self.assertRaises(ValueError):
                    ns['account_capture_habbo_session_cookies'](43111)


class AutomaticLoginAndImport(TestCase):
    def test_reuses_running_browser_and_saves_only_after_ticket_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[]
            cookies=('opaque-session','opaque-browser')
            ticket=SimpleNamespace(secret='opaque-ticket.V4')
            ns=execute(
                APP_DIR=Path(folder),
                _account_credential_target=lambda ident:ident,
                account_browser_debug_port=lambda ident:43111,
                account_login_browser=lambda:Path('/mock/brave.exe'),
                validate_habbo_login_url=lambda url:url,
                account_saved_login_read=lambda ident:('me@example.com','password'),
                account_browser_pages=lambda port:[signed_in_page(port)],
                account_attempt_auto_play=lambda port,report,credentials,login_only:(
                    events.append(('login',port,credentials,login_only))
                    or 'signed_in'),
                account_capture_habbo_session_cookies=lambda port:cookies,
                fetch_habbo_sso_ticket=lambda sid,tok:(
                    events.append(('verify',sid,tok)) or 'ticket'),
                account_parse_official_ticket_response=lambda raw:ticket,
                account_session_cookie_write=lambda ident,sid,tok:
                    events.append(('write',ident,sid,tok)),
            )
            result=ns['account_import_session_automatically'](
                account(),lambda message:events.append(('status',message)))
            self.assertIs(result,ticket)
            self.assertEqual(events[-2][0],'write')
            self.assertLess(
                next(i for i,x in enumerate(events) if x[0]=='verify'),
                next(i for i,x in enumerate(events) if x[0]=='write'))
            self.assertIn(('login',43111,('me@example.com','password'),True),
                          events)

    def test_headless_profile_created_with_isolated_folder_and_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            launches=[]
            closed=[]
            class Proc:
                def terminate(self):
                    closed.append('terminated')
            profile_port=43111
            page=signed_in_page(profile_port)
            calls={'n':0}
            def browser_pages(_):
                calls['n']+=1
                if calls['n']==1:raise OSError('not started')
                return [page]
            def spawn(args,**kwargs):
                launches.append(args)
                return Proc()
            ns=execute(
                APP_DIR=Path(folder),
                _account_credential_target=lambda ident:ident,
                account_browser_debug_port=lambda ident:profile_port,
                account_login_browser=lambda:Path('/mock/brave.exe'),
                validate_habbo_login_url=lambda url:url,
                account_saved_login_read=lambda ident:None,
                account_browser_pages=browser_pages,
                account_browser_command=lambda browser,dir,url,port:[
                    str(browser),'--user-data-dir='+str(dir),
                    '--remote-debugging-port='+str(port),url],
                subprocess=SimpleNamespace(Popen=spawn,DEVNULL=-3),
                account_attempt_auto_play=lambda *a,**k:'signed_in',
                account_capture_habbo_session_cookies=lambda port:('abc','def'),
                fetch_habbo_sso_ticket=lambda *args:'ticket',
                account_parse_official_ticket_response=lambda x:'token',
                account_session_cookie_write=lambda *args:None,
                account_habbo_page=lambda _:page,
                account_cdp_call=lambda ws,method,timeout:
                    closed.append(method),
            )
            self.assertEqual(
                ns['account_import_session_automatically'](account(),lambda _:None),
                'token')
            self.assertEqual(len(launches),1)
            self.assertIn('--headless=new',launches[0])
            self.assertIn('--remote-debugging-port=43111',launches[0])
            self.assertIn('account_browser_profiles/abcdef123456',
                          ' '.join(launches[0]).replace('\\','/'))
            self.assertEqual(closed,['Browser.close'])

    def test_failed_signin_never_reads_or_saves_cookies(self):
        ns=execute(
            _account_credential_target=lambda ident:ident,
            account_browser_debug_port=lambda ident:43111,
            account_login_browser=lambda:Path('/mock/brave.exe'),
            validate_habbo_login_url=lambda url:url,
            account_saved_login_read=lambda ident:None,
            account_browser_pages=lambda port:[signed_in_page(port)],
            account_attempt_auto_play=lambda *a,**k:'login',
            account_capture_habbo_session_cookies=lambda port:
                self.fail('must not read cookies'),
            account_session_cookie_write=lambda *args:
                self.fail('must not write to vault'),
        )
        with self.assertRaisesRegex(ValueError,'sign-in needs attention'):
            ns['account_import_session_automatically'](account(),lambda _:None)

    def test_ticket_rejected_does_not_write_stale_browser_cookies(self):
        ns=execute(
            _account_credential_target=lambda ident:ident,
            account_browser_debug_port=lambda ident:43111,
            account_login_browser=lambda:Path('/mock/brave.exe'),
            validate_habbo_login_url=lambda url:url,
            account_saved_login_read=lambda ident:None,
            account_browser_pages=lambda port:[signed_in_page(port)],
            account_attempt_auto_play=lambda *a,**k:'signed_in',
            account_capture_habbo_session_cookies=lambda port:('abc','def'),
            fetch_habbo_sso_ticket=lambda *args:
                (_ for _ in ()).throw(ValueError('401 rejected')),
            account_session_cookie_write=lambda *args:
                self.fail('must not save rejected session'),
        )
        with self.assertRaisesRegex(ValueError,'401 rejected'):
            ns['account_import_session_automatically'](account(),lambda _:None)


class AppIntegration(TestCase):
    def test_direct_tcp_buttons_workers_and_no_secret_logging(self):
        self.assertIn('Auto-import session and connect (selected account)',TEXT)
        self.assertIn('Auto-import and connect all',TEXT)
        self.assertIn('self._tcp_connect_one(account,auto_capture=True)',TEXT)
        self.assertIn('ticket=account_import_session_automatically(',TEXT)
        self.assertIn('account_session_cookie_write(ident,*cookies)',TEXT)
        self.assertIn("('tcp_state',ident,generation,message)",TEXT)
        self.assertIn('Network.getCookies',TEXT)
        self.assertNotIn('document.cookie',TEXT.split('def account_capture_habbo_session_cookies',1)[1].split('def account_import_session_automatically',1)[0])
        self.assertNotIn('logging.info(cookies)',TEXT)
        self.assertNotIn('self._tcp_log_event(ident,cookies)',TEXT)


if __name__=='__main__':
    unittest.main()
