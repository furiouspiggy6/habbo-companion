import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import urllib.request
import uuid
import re

class FreshManifestTests(unittest.TestCase):
    def run_fetch(self,api,raw):
        p=Path(__file__).resolve().parents[1]/'Habbo_Companion.pyw'
        node=next(n for n in ast.parse(p.read_text(encoding='utf-8')).body
                  if isinstance(n,ast.FunctionDef) and n.name=='fetch_current_update_manifest')
        class Response:
            def __init__(self,url,data):self.url=url;self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return self.url
            def read(self,n):return json.dumps(self.data).encode()
        def open_update(req,timeout):
            data=api if 'api.github.com' in req.full_url else raw
            if isinstance(data,Exception):raise data
            return Response(req.full_url,data)
        scope=dict(json=json,urllib=urllib,uuid=uuid,re=re,_open_official_update=open_update)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope)
        helper=SimpleNamespace(validate_official_release_url=lambda *a,**k:None,
                               version_tuple=lambda v:tuple(map(int,v.split('.'))))
        return scope[node.name]('https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/latest.json',helper)
    def manifest(self,v,digest='a'):
        return dict(app_id='habbo-companion',version=v,package_url='https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/Habbo_Companion_Update_v'+v+'.zip',sha256=digest*64)
    def test_stale_raw(self):
        self.assertEqual(self.run_fetch(self.manifest('1.1.105'),self.manifest('1.1.104'))[0]['version'],'1.1.105')
    def test_api_unavailable(self):
        self.assertEqual(self.run_fetch(OSError('offline'),self.manifest('1.1.104'))[0]['version'],'1.1.104')
    def test_conflicting_hashes(self):
        with self.assertRaisesRegex(ValueError,'disagree'):
            self.run_fetch(self.manifest('1.1.105'),self.manifest('1.1.105','b'))
