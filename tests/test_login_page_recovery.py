"""Offline regression tests for isolated Habbo second-account login recovery."""
import ast
import json
from pathlib import Path
import shutil
import socket
import subprocess
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.parse

SOURCE=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)


def function(name):
    node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
              and n.name==name)
    scope={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),
         scope)
    return scope


class LoginRedirectTests(unittest.TestCase):
    def setUp(self):
        self.scope=function('account_attempt_auto_play')
        self.scope['account_habbo_page']=lambda _: {
            'url':'https://www.habbo.com/',
            'webSocketDebuggerUrl':'ws://127.0.0.1:43111/devtools/page/example'}
        self.scope['time']=SimpleNamespace(sleep=lambda _:None)
        self.events=[]
        self.scope['account_click_play_button']=lambda ws,step:(
            self.events.append('clicked:'+step['kind']))
        self.scope['account_submit_saved_login']=lambda ws,email,password,report=None:(
            self.events.append('submitted') or True)

    def test_temporary_navigation_does_not_abort_saved_login(self):
        sequence=iter([
            {'kind':'not_habbo'}, {'kind':'not_habbo'},
            {'kind':'login'}, {'kind':'signed_in'}])
        self.scope['account_inspect_play_page']=lambda _:next(sequence)
        reports=[]
        result=self.scope['account_attempt_auto_play'](
            43111,reports.append,('test@example.com','secret'),True)
        self.assertEqual(result,'signed_in')
        self.assertEqual(self.events,['submitted'])
        self.assertFalse(any('secret' in text for text in reports))

    def test_persistent_external_navigation_stops_without_password(self):
        self.scope['account_inspect_play_page']=lambda _: {'kind':'not_habbo'}
        reports=[]
        result=self.scope['account_attempt_auto_play'](
            43111,reports.append,('test@example.com','secret'),True)
        self.assertEqual(result,'unknown')
        self.assertEqual(self.events,[])
        self.assertIn('Password entry was stopped for safety',reports[-1])
        self.assertNotIn('secret',' '.join(reports))

    def test_open_login_then_submit_only_after_official_form_detected(self):
        sequence=iter([
            {'kind':'open-login','x':34,'y':22},
            {'kind':'login'}, {'kind':'signed_in'}])
        self.scope['account_inspect_play_page']=lambda _:next(sequence)
        reports=[]
        result=self.scope['account_attempt_auto_play'](
            43111,reports.append,('test@example.com','secret'),True)
        self.assertEqual(result,'signed_in')
        self.assertEqual(self.events,['clicked:open-login','submitted'])
        self.assertTrue(any('Opening the official Habbo' in r for r in reports))

    def test_open_login_never_clicks_without_saved_credentials(self):
        self.scope['account_inspect_play_page']=lambda _: {
            'kind':'open-login','x':12,'y':12}
        reports=[]
        self.assertEqual(self.scope['account_attempt_auto_play'](
            43111,reports.append,None,True),'login')
        self.assertEqual(self.events,[])


class BrowserInspectionTests(unittest.TestCase):
    def js_status(self,hostname,label):
        node=shutil.which('node')
        if not node:
            self.skipTest('Node not available')
        js=next(ast.literal_eval(n.value) for n in TREE.body if
            isinstance(n,ast.Assign) and any(
                isinstance(t,ast.Name) and t.id=='HABBO_AUTO_PLAY_JS'
                for t in n.targets))
        runner=r"""
const fs=require('fs');
const hostname=process.argv[1],text=process.argv[2];
const button={
  innerText:text,value:'',textContent:'',className:'',
  disabled:false,parentElement:null,onclick:null,
  getAttribute:()=>null,querySelector:()=>null,
  getBoundingClientRect:()=>({
    left:900,top:45,width:110,height:40,right:1010,bottom:85
  }),matches:()=>true
};
global.location={protocol:'https:',hostname,pathname:'/'};
global.innerWidth=1100;global.innerHeight=800;
global.getComputedStyle=()=>({display:'block',visibility:'visible',cursor:'pointer'});
global.document={querySelectorAll:selector=>{
  if (selector==='input[type=password]') return [];
  if (selector==='span,strong,div') return [];
  return [button];
}};
console.log(JSON.stringify(eval(fs.readFileSync(0,'utf8'))));
"""
        result=subprocess.run([node,'-e',runner,hostname,label],
            input=js,text=True,capture_output=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_login_button_discovery_on_official_site(self):
        kind=self.js_status('www.habbo.com','Log in')
        self.assertEqual(kind['kind'],'open-login')
        self.assertEqual((kind['x'],kind['y']),(955,65))

    def test_unrelated_domain_never_yields_login_button(self):
        self.assertEqual(
            self.js_status('www.habbo.com.evil.example','Log in')['kind'],
            'not_habbo')


class SurfacedDiagnosticsTests(unittest.TestCase):
    def test_automatic_import_reports_login_failure_cause(self):
        scope=function('account_import_session_automatically')
        scope.update({
            '_account_credential_target':lambda ident:ident,
            'account_browser_debug_port':lambda ident:43111,
            'account_login_browser':lambda:Path('/mock/brave.exe'),
            'APP_DIR':Path('/not-used'),
            'validate_habbo_login_url':lambda url:url,
            'account_saved_login_read':lambda _:('test@example.com','secret'),
            'account_browser_pages':lambda _:[{'type':'page'}],
            'account_capture_habbo_session_cookies':lambda *args,**kwargs:(
                (_ for _ in ()).throw(ValueError('No valid session'))),
            'account_fetch_ticket_from_signed_in_profile':lambda port:(
                _ for _ in ()).throw(ValueError('No signed-in browser ticket')),
            'account_attempt_auto_play':lambda port,report,**kwargs:(
                report('Password entry stopped on unverified page') or 'unknown'),
            'account_session_cookie_write':lambda *args:
                self.fail('Must never store unverified credentials'),
            'HabboTcpError':type('HabboTcpError',(Exception,),{}),
            'socket':socket,
            'urllib':SimpleNamespace(parse=urllib.parse,error=urllib.error),
            'time':SimpleNamespace(sleep=lambda _:None),
        })
        logs=[]
        with self.assertRaisesRegex(ValueError,'Use Accounts'):
            scope['account_import_session_automatically'](
                {'id':'abcdef123456','url':'https://www.habbo.com/'},
                logs.append)
        self.assertTrue(any('Password entry stopped' in message
                            for message in logs))
        self.assertNotIn('secret',' '.join(logs))


if __name__=='__main__':
    unittest.main()
