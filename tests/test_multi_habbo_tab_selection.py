"""Regression: verify the correct Habbo tab in each isolated browser profile."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
CODE=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(CODE)
NODES={n.name:n for n in TREE.body
       if isinstance(n,ast.FunctionDef)
       and n.name in ('account_habbo_page','account_attempt_auto_play')}


def target(port,ident,url='https://www.habbo.com/'):
    return {'url':url,'type':'page',
            'webSocketDebuggerUrl':f'ws://127.0.0.1:{port}/devtools/page/{ident}'}


class MultiHabboTabTests(unittest.TestCase):
    def setup_browser(self,pages,inspect):
        import urllib.parse
        ns={'urllib':SimpleNamespace(parse=urllib.parse),
            'socket':SimpleNamespace(timeout=TimeoutError),
            'time':SimpleNamespace(sleep=lambda _:None)}
        exec(compile(ast.Module(body=list(NODES.values()),type_ignores=[]),
                     str(SOURCE),'exec'),ns)
        ns['account_browser_pages']=lambda port:pages[port]
        ns['account_inspect_play_page']=inspect
        return ns

    def test_stale_login_tab_does_not_hide_authenticated_play_tab(self):
        a=target(44000,'stale')
        b=target(44000,'active','https://www.habbo.com/')
        ns=self.setup_browser({44000:[a,b]},
                              lambda ws: {'kind':'login'} if 'stale' in ws else
                              {'kind':'play','label':'PLAY H','x':940,'y':155,
                               'page':'/'})
        winner=ns['account_habbo_page'](44000)
        self.assertEqual(winner['webSocketDebuggerUrl'],b['webSocketDebuggerUrl'])
        self.assertEqual(winner['_preflight_step']['kind'],'play')
        self.assertEqual(ns['account_attempt_auto_play'](
            44000,lambda *_:None,None,True),'signed_in')

    def test_multiple_profiles_have_no_cross_account_browser_pages(self):
        first=target(44000,'main')
        second=target(44001,'alt')
        called=[]
        def inspect(ws):
            called.append(ws)
            return {'kind':'play','label':'PLAY','x':930,'y':150,'page':'/'}
        ns=self.setup_browser({44000:[first],44001:[second]},inspect)
        one=ns['account_habbo_page'](44000)
        two=ns['account_habbo_page'](44001)
        self.assertNotEqual(one['webSocketDebuggerUrl'],two['webSocketDebuggerUrl'])
        self.assertEqual(called,[first['webSocketDebuggerUrl'],
                                 second['webSocketDebuggerUrl']])

    def test_unrelated_url_is_not_inspected(self):
        unrelated=target(44000,'bank','https://mybank.example/account')
        official=target(44000,'site','https://www.habbo.com/')
        calls=[]
        ns=self.setup_browser({44000:[unrelated,official]},
                              lambda ws:(calls.append(ws) or
                                         {'kind':'signed_in','evidence':'profile-menu'}))
        self.assertEqual(ns['account_habbo_page'](44000)['webSocketDebuggerUrl'],
                         official['webSocketDebuggerUrl'])
        self.assertEqual(calls,[official['webSocketDebuggerUrl']])

    def test_bad_tab_inspection_does_not_block_later_signed_in_tab(self):
        bad=target(44000,'bad')
        good=target(44000,'good')
        def inspect(ws):
            if 'bad' in ws:
                raise OSError('Browser rejected websocket control')
            return {'kind':'signed_in','evidence':'profile-menu'}
        ns=self.setup_browser({44000:[bad,good]},inspect)
        self.assertEqual(ns['account_habbo_page'](44000)['webSocketDebuggerUrl'],
                         good['webSocketDebuggerUrl'])

    def test_all_failed_tabs_report_browser_control_error(self):
        bad=target(44000,'bad')
        ns=self.setup_browser({44000:[bad]},
                              lambda ws:(_ for _ in ()).throw(
                                  OSError('Browser DevTools socket rejected handshake: HTTP/1.1 403 Forbidden')))
        picked=ns['account_habbo_page'](44000)
        self.assertIn('403 Forbidden',picked['_inspect_error'])
        reports=[]
        status=ns['account_attempt_auto_play'](44000,reports.append,None,True)
        self.assertEqual(status,'inspect_error')
        self.assertTrue(any('403 Forbidden' in r for r in reports))
        self.assertFalse(any('password' in r.lower() for r in reports))

    def test_missing_habbo_tabs_not_reported_as_logged_out(self):
        unrelated=target(44000,'unrelated','https://www.example.com')
        ns=self.setup_browser({44000:[unrelated]},lambda ws:None)
        self.assertIsNone(ns['account_habbo_page'](44000))
        result=ns['account_attempt_auto_play'](44000,lambda *_:None,None,True)
        self.assertEqual(result,'no_habbo_tab')

    def test_no_credential_or_cookie_dump_added_to_diagnostics(self):
        self.assertNotIn('document.cookie',CODE)
        self.assertNotIn('Network.getAllCookies',CODE)
        self.assertNotIn('Network.getCookies',CODE)
        self.assertIn("'inspect_error':'Browser inspection failed'",CODE)


if __name__=='__main__':
    unittest.main()
