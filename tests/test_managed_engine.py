"""Offline managed-engine checks; no Windows UI or network required."""
from pathlib import Path
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
loader=SourceFileLoader('habbo_companion_test',str(ROOT/'Habbo_Companion.pyw'))
spec=importlib.util.spec_from_loader(loader.name,loader)
app=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=app
loader.exec_module(app)

class ManagedEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        keys=('GEARTH_ENGINE_DIR','GEARTH_ENGINE_URL','GEARTH_ENGINE_SHA256','GEARTH_ENGINE_ARCHIVE_BYTES')
        self.old={k:getattr(app,k) for k in keys}
        self.addCleanup(self.restore)
        app.GEARTH_ENGINE_DIR=self.root/'engine'/app.GEARTH_ENGINE_VERSION

    def restore(self):
        for name,value in self.old.items():
            setattr(app,name,value)

    def test_import_user_selected_copy(self):
        folder=self.root/'G-Earth-windows-x64'
        folder.mkdir()
        exe=folder/'G-Earth.exe'
        exe.write_bytes(b'fake program')
        (folder/'runtime.dll').write_bytes(b'runtime')
        path,origin=app.install_managed_gearth(exe,lambda _:None)
        self.assertIn('user-selected',origin)
        self.assertEqual((path.parent/'runtime.dll').read_bytes(),b'runtime')
        self.assertIn('MIT License',(app.GEARTH_ENGINE_DIR/'THIRD_PARTY_G_EARTH_LICENSE.txt').read_text())
        self.assertEqual(app.managed_gearth_executable(),path)
        same,_=app.install_managed_gearth(exe,lambda _:None)
        self.assertEqual(same,path)

    def set_archive(self,path):
        app.GEARTH_ENGINE_URL=path.as_uri()
        app.GEARTH_ENGINE_ARCHIVE_BYTES=path.stat().st_size
        app.GEARTH_ENGINE_SHA256=hashlib.sha256(path.read_bytes()).hexdigest()

    def test_verified_archive(self):
        zip_path=self.root/'official.zip'
        with zipfile.ZipFile(zip_path,'w') as z:
            z.writestr('G-Earth-windows-x64/G-Earth.exe',b'fake exe')
            z.writestr('G-Earth-windows-x64/runtime.txt',b'engine')
        self.set_archive(zip_path)
        path,origin=app.install_managed_gearth('',lambda _:None)
        self.assertEqual(origin,'official verified release')
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(),b'fake exe')

    def test_checksum_mismatch_rejected(self):
        zip_path=self.root/'bad.zip'
        with zipfile.ZipFile(zip_path,'w') as z:
            z.writestr('G-Earth.exe',b'bad')
        self.set_archive(zip_path)
        app.GEARTH_ENGINE_SHA256='0'*64
        with self.assertRaisesRegex(ValueError,'checksum'):
            app.install_managed_gearth('',lambda _:None)
        self.assertIsNone(app.managed_gearth_executable())

    def test_path_traversal_rejected(self):
        zip_path=self.root/'traversal.zip'
        with zipfile.ZipFile(zip_path,'w') as z:
            z.writestr('../malicious.txt',b'bad')
            z.writestr('G-Earth.exe',b'fake')
        self.set_archive(zip_path)
        with self.assertRaisesRegex(ValueError,'Unsafe file path'):
            app.install_managed_gearth('',lambda _:None)
        self.assertFalse((self.root/'malicious.txt').exists())

if __name__=='__main__':
    unittest.main()
