"""Safe browser-login diagnostics and form-targeting regression tests."""
import ast
import json
from pathlib import Path
import shutil
import socket
import subprocess
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'Habbo_Companion.pyw'
TEXT=SOURCE.read_text(encoding='utf-8')
TREE=ast.parse(TEXT)


def js_constant(name):
    return next(ast.literal_eval(node.value) for node in TREE.body if
        isinstance(node,ast.Assign) and any(
            isinstance(target,ast.Name) and target.id==name
            for target in node.targets))


def run_js(expression,scenario):
    node=shutil.which('node')
    if not node:
        raise unittest.SkipTest('Node.js not available')
    runner=r"""
const fs=require('fs');
const scenario=JSON.parse(process.argv[1]);
const rect=(x,y)=>({left:x,top:y,right:x+90,bottom:y+30,width:90,height:30});
function el(props){
  return Object.assign({
    type:'text',innerText:'',textContent:'',value:'',disabled:false,
    autocomplete:'',placeholder:'',getAttribute:()=>null,
    getBoundingClientRect:()=>rect(100,100),
    closest:()=>null
  },props||{});
}
const outside=el({type:'text',getBoundingClientRect:()=>rect(20,20)});
const email=el({type:'email',getBoundingClientRect:()=>rect(100,200)});
const pwd=el({type:'password',getBoundingClientRect:()=>rect(100,250)});
const submit=el({type:'submit',innerText:'Log in',
  getBoundingClientRect:()=>rect(150,300)});
const form={querySelectorAll:s=>s.startsWith('button')?[submit]:[email]};
pwd.closest=selector=>selector==='form'?form:null;
const notices=(scenario.alert||'')?[el({innerText:scenario.alert})]:[];
global.location={protocol:'https:',hostname:scenario.hostname||'www.habbo.com',pathname:'/login'};
global.innerWidth=1200;global.innerHeight=900;
global.getComputedStyle=()=>({display:'block',visibility:'visible'});
global.document={
  activeElement:scenario.inputKind?
    el({tagName:'INPUT',type:scenario.inputKind,
        value:scenario.populated?'test-value':''}):null,
  querySelector:()=>null,
  querySelectorAll:selector=>{
    if (selector.startsWith('iframe[title*=challenge i]')) {
      if (scenario.captcha) return [el({})];
      if (scenario.hiddenChallenge) return [el({
        getBoundingClientRect:()=>({
          left:0,top:0,right:0,bottom:0,width:0,height:0
        })
      })];
      return [];
    }
    if (selector==='input[type=password]')return [pwd];
    if (selector.startsWith('input[autocomplete=one-time-code]'))
      return scenario.otp?[el({})]:[];
    if (selector.startsWith('[role=alert]'))return notices;
    if (selector.startsWith('input[type=email]'))return [outside,email];
    return [];
  }
};
console.log(JSON.stringify(eval(fs.readFileSync(0,'utf8'))));
"""
    result=subprocess.run([node,'-e',runner,json.dumps(scenario)],
            input=expression,text=True,capture_output=True,timeout=8)
    if result.returncode!=0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class SafeDiagnosticsTests(unittest.TestCase):
    def test_detects_login_denial_without_returning_page_text(self):
        status=run_js(js_constant('HABBO_LOGIN_DIAGNOSTIC_JS'),
            {'alert':'Wrong email or password for my.email@example.com'})
        self.assertEqual(status,{'kind':'invalid-credentials'})
        self.assertNotIn('my.email',str(status))

    def test_captcha_and_verification_have_distinct_codes(self):
        js=js_constant('HABBO_LOGIN_DIAGNOSTIC_JS')
        self.assertEqual(run_js(js,{'captcha':True})['kind'],'captcha')
        self.assertEqual(run_js(js,{'otp':True})['kind'],'verification')
        self.assertEqual(run_js(js,{})['kind'],'still-on-form')

    def test_passive_captcha_markup_is_not_mistaken_for_a_challenge(self):
        js=js_constant('HABBO_LOGIN_DIAGNOSTIC_JS')
        self.assertNotIn('[data-sitekey]',js)
        self.assertNotIn('iframe[src*=recaptcha]',js)
        self.assertEqual(run_js(js,{'hiddenChallenge':True})['kind'],
                         'still-on-form')

    def test_unrelated_hostname_cannot_disclose_login_status(self):
        status=run_js(js_constant('HABBO_LOGIN_DIAGNOSTIC_JS'),
            {'hostname':'habbo.com.fake.example',
             'alert':'Wrong email and password'})
        self.assertEqual(status['kind'],'unverified-page')

    def test_login_fields_prefer_form_matched_email_to_header_search(self):
        status=run_js(js_constant('HABBO_LOGIN_FIELDS_JS'),{})
        self.assertEqual(status['kind'],'form')
        self.assertEqual(status['email'],{'x':145,'y':215})
        self.assertEqual(status['password'],{'x':145,'y':265})

    def test_login_entry_confirmation_is_origin_locked_and_redacted(self):
        js=js_constant('HABBO_LOGIN_INPUT_READY_JS')
        self.assertEqual(
            run_js(js,{'inputKind':'email','populated':True}),
            {'kind':'populated','field':'email'})
        self.assertEqual(
            run_js(js,{'inputKind':'password','populated':True}),
            {'kind':'populated','field':'password'})
        self.assertEqual(
            run_js(js,{'inputKind':'password','populated':False}),
            {'kind':'empty','field':'password'})
        denied=run_js(js,{'hostname':'habbo.com.fake.example',
                          'inputKind':'password','populated':True})
        self.assertEqual(denied,{'kind':'unverified-page'})
        self.assertNotIn('test-value',
                         str(run_js(js,{'inputKind':'password','populated':True})))

    def test_diagnostic_adapter_whitelists_returned_codes(self):
        node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
                  and n.name=='account_login_diagnostic')
        scope={'socket':socket}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),scope)
        scope['HABBO_LOGIN_DIAGNOSTIC_JS']=js_constant('HABBO_LOGIN_DIAGNOSTIC_JS')
        scope['account_cdp_call']=lambda *args,**kwargs:{
            'result':{'value':{'kind':'invalid-credentials'}}}
        self.assertEqual(scope['account_login_diagnostic']('local-socket'),
                         'invalid-credentials')
        scope['account_cdp_call']=lambda *args,**kwargs:{
            'result':{'value':{'kind':'password=secret'}}}
        self.assertEqual(scope['account_login_diagnostic']('local-socket'),
                         'unknown')


if __name__=='__main__':
    unittest.main()
