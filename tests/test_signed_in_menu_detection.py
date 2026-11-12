"""Exercise Habbo's authenticated header/PLAY detection and failure diagnostics."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)
JS=next(ast.literal_eval(n.value) for n in TREE.body if
        isinstance(n,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id=='HABBO_AUTO_PLAY_JS'
            for t in n.targets))

NODE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
          and n.name=='account_attempt_auto_play')
INSPECTOR=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
               and n.name=='account_inspect_play_page')

NODE_RUNNER=r"""
const fs=require('fs');
const mode=process.argv[1];
const rect=(x=810,y=83,w=160,h=42)=>({
    left:x,top:y,width:w,height:h,bottom:y+h,right:x+w});
const button=(text,x=820,y=88,w=155,h=40,avatar=false)=>({
    innerText:text, value:'', parentElement:null, disabled:false,
    className:avatar?'user-menu':'play-button',
    getAttribute:name=>null,
    querySelector:query=>avatar?{}:null,
    getBoundingClientRect:()=>rect(x,y,w,h),
    matches:sel=>true
});
global.location={protocol:'https:',hostname:'www.habbo.com',pathname:'/'};
global.innerWidth=1060;global.innerHeight=800;
global.getComputedStyle=el=>({display:'block',visibility:'visible',cursor:'pointer'});
const play=button('PLAY H',935,160,96,42);
const profile=button('dan.alt100',840,95,165,45,true);
const email=button('',850,270,170,35);
email.type='password';
let controls=mode==='play'?[play]:(mode==='profile'?[profile]:[]);
global.document={querySelectorAll:(selector)=>{
    if(selector==='input[type=password]')return mode==='login'?[email]:[];
    if(selector==='span,strong,div')return [];
    if(selector.startsWith('header a'))return mode==='profile'?[profile]:[];
    if(selector.startsWith('a,button'))return controls;
    return [];
}};
console.log(JSON.stringify(eval(fs.readFileSync(0,'utf8'))));
"""


class AuthenticatedPageDetectionTests(unittest.TestCase):
    def js_scenario(self,scenario):
        node=shutil.which('node')
        if not node:
            self.skipTest('Node is unavailable on this test environment')
        p=subprocess.run([node,'-e',NODE_RUNNER,scenario],
                         input=JS,text=True,capture_output=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)

    def test_visible_play_with_h_icon_is_detected(self):
        out=self.js_scenario('play')
        self.assertEqual(out['kind'],'play')
        self.assertEqual(out['label'],'PLAY H')
        self.assertTrue(out['x']>900)

    def test_logged_in_profile_menu_confirms_session_without_play(self):
        out=self.js_scenario('profile')
        self.assertEqual(out['kind'],'signed_in')
        self.assertEqual(out['evidence'],'profile-menu')

    def test_no_play_or_profile_is_not_mistaken_for_authentication(self):
        self.assertEqual(self.js_scenario('unknown')['kind'],'waiting')

    def test_login_form_takes_priority_over_possible_logged_in_controls(self):
        self.assertEqual(self.js_scenario('login')['kind'],'login')

    def player(self,status,login_only=True):
        ns={}
        exec(compile(ast.Module(body=[NODE],type_ignores=[]),
                     str(SOURCE),'exec'),ns)
        ns['account_habbo_page']=lambda port:{
            'url':'https://www.habbo.com/',
            'webSocketDebuggerUrl':'ws://127.0.0.1:44000/devtools/page/id'}
        ns['account_inspect_play_page']=lambda ws:{'kind':status}
        clicked=[]
        ns['account_click_play_button']=lambda *args:clicked.append(args)
        ns['time']=SimpleNamespace(sleep=lambda _:None)
        messages=[]
        return ns['account_attempt_auto_play'](44000,messages.append,
                                                 None,login_only),clicked,messages

    def test_profile_menu_certifies_only_website_login(self):
        out,clicked,_=self.player('signed_in',True)
        self.assertEqual(out,'signed_in')
        self.assertEqual(clicked,[])

    def test_profile_menu_does_not_guess_play_click_coordinates(self):
        out,clicked,reports=self.player('signed_in',False)
        self.assertEqual(out,'timeout')
        self.assertEqual(clicked,[])
        self.assertIn('PLAY control is not identifiable',reports[-1])

    def test_missing_tab_has_explicit_diagnostic(self):
        ns={}
        exec(compile(ast.Module(body=[NODE],type_ignores=[]),
                     str(SOURCE),'exec'),ns)
        ns['account_habbo_page']=lambda _:None
        ns['time']=SimpleNamespace(sleep=lambda _:None)
        out=[]
        self.assertEqual(ns['account_attempt_auto_play'](
            44000,out.append,None,True),'waiting')
        self.assertIn('No HTTPS Habbo website tab',out[-1])

    def test_cdp_eval_exception_is_reported_not_silent_success(self):
        ns={}
        exec(compile(ast.Module(body=[INSPECTOR],type_ignores=[]),
                     str(SOURCE),'exec'),ns)
        ns['HABBO_AUTO_PLAY_JS']=JS
        ns['account_cdp_call']=lambda *args:{
            'exceptionDetails':{'text':'JavaScript exception'}}
        with self.assertRaisesRegex(RuntimeError,'script failed'):
            ns['account_inspect_play_page'](
                'ws://127.0.0.1:44000/devtools/page/id')


if __name__=='__main__':
    unittest.main()
