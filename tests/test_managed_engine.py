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


    def test_auto_setup_starts_even_if_window_tracker_is_false_positive(self):
        """A stray Habbo-title window must not prevent installing the engine."""
        from unittest.mock import patch
        from types import SimpleNamespace
        messages=[]
        class Var:
            def __init__(self,value=None):self.value=value
            def get(self):return self.value
            def set(self,value):self.value=value;messages.append(value)
        class FakeTracker:
            def find(self,_):return (0,0,800,600,1234,'Habbo')
        class FakeRoot:
            def winfo_id(self):return 100
        appobj=object.__new__(app.ChatOverlayApp)
        appobj._engine_installing=False
        appobj._engine_last_error=''
        appobj._engine_start_attempted=False
        appobj.root=FakeRoot()
        appobj.overlay=SimpleNamespace(winfo_id=lambda:200)
        appobj.tracker=FakeTracker()
        appobj.gearth_port_var=Var('9092')
        appobj.engine_status_var=Var()
        appobj.packet_status=Var()
        appobj.config={'gearth_path':str(self.root/'working-beta'/'G-Earth.exe')}
        appobj._engine_install_worker=lambda _seed:None
        class FakeThread:
            def __init__(self,target,args,daemon):self.target=target
            def start(self):pass
        with patch.object(app.ChatOverlayApp,'_gearth_extension_port_responds',return_value=False), \
             patch.object(app,'managed_gearth_executable',return_value=None), \
             patch.object(app.threading,'Thread',FakeThread):
            appobj._start_integrated_engine()
        self.assertTrue(appobj._engine_installing)
        self.assertTrue(appobj._engine_start_attempted)
        self.assertIn('importing or downloading',appobj.engine_status_var.get())

    def test_heartbeat_does_not_erase_engine_error(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        class Var:
            def __init__(self,value=None):self.value=value
            def get(self):return self.value
            def set(self,value):self.value=value
        class FakeRoot:
            def winfo_exists(self):return True
            def after(self,*args):pass
        appobj=object.__new__(app.ChatOverlayApp)
        appobj.root=FakeRoot()
        appobj._engine_installing=False
        appobj._engine_last_error='PermissionError: access denied'
        appobj._engine_start_attempted=True
        appobj.engine_status_var=Var()
        appobj.gearth_port_var=Var('9092')
        with patch.object(app.ChatOverlayApp,'_gearth_extension_port_responds',return_value=False):
            appobj._engine_heartbeat()
        self.assertIn('access denied',appobj.engine_status_var.get())


    def test_installed_engine_starts_despite_false_habbo_window(self):
        """Previously an unrelated Habbo-titled window prevented engine start."""
        from types import SimpleNamespace
        from unittest.mock import patch
        class Var:
            def __init__(self,value=None):self.value=value
            def get(self):return self.value
            def set(self,value):self.value=value
        exe=self.root/'installed'/'G-Earth.exe'
        exe.parent.mkdir()
        exe.write_bytes(b'test exe')
        appobj=object.__new__(app.ChatOverlayApp)
        appobj.config={'gearth_path':str(exe)}
        appobj._engine_installing=False
        appobj._engine_start_attempted=False
        appobj._engine_last_error=''
        appobj.gearth_port_var=Var('9092')
        appobj.engine_status_var=Var()
        appobj.packet_status=Var()
        appobj.gearth_path_display=Var()
        appobj.tracker=SimpleNamespace(find=lambda _:('false Habbo window',))
        appobj.root=SimpleNamespace(winfo_id=lambda:55)
        appobj.overlay=SimpleNamespace(winfo_id=lambda:56)
        appobj.save=lambda:None
        called=[]
        appobj._start_gearth_direct=lambda select_if_missing:called.append(select_if_missing)
        with patch.object(app.ChatOverlayApp,'_gearth_extension_port_responds',return_value=False), \
             patch.object(app,'managed_gearth_executable',return_value=exe):
            appobj._start_integrated_engine()
        self.assertEqual(called,[False])
        self.assertIn('installed',appobj.engine_status_var.get())

    def test_diagnostic_button_and_cache_bust_are_present(self):
        import inspect
        self.assertTrue(callable(app.ChatOverlayApp._diagnose_and_repair))
        self.assertTrue(callable(app.ChatOverlayApp._copy_engine_diagnostic))
        code=inspect.getsource(app.ChatOverlayApp._check_online_update)
        self.assertIn('uuid.uuid4().hex',code)
        self.assertIn("Cache-Control",code)


    def test_auto_hide_restores_explicit_advanced_control(self):
        import inspect
        code=inspect.getsource(app.ChatOverlayApp._try_hide_gearth)
        self.assertIn('user32.ShowWindowAsync(hwnd,0)',code)
        self.assertIn('IsWindowVisible',code)
        self.assertIn('self.root.after(1000,self._try_hide_gearth)',code)
        show=inspect.getsource(app.ChatOverlayApp._show_gearth)
        self.assertIn('self._gearth_manual_window=True',show)
        self.assertIn('user32.ShowWindowAsync(hwnd,5)',show)

    def test_hide_uses_verified_backend_not_early_launch(self):
        import inspect
        code=inspect.getsource(app.ChatOverlayApp._schedule_gearth_hide)
        self.assertIn('_gearth_extension_port_responds(port)',code)
        self.assertIn('_gearth_hide_pending',code)
        self.assertIn('_gearth_manual_window',code)
        startup=inspect.getsource(app.ChatOverlayApp._launch_gearth)
        self.assertIn("result=execute(None,'runas',program,parameters,str(path.parent),1)",startup)


    def test_auto_start_default_off_after_outage(self):
        self.assertFalse(app.DEFAULT['gearth_auto_arm'])

    def test_scoped_hosts_repair_and_backup(self):
        from unittest.mock import patch
        hosts=self.root/'hosts'
        original=(b'127.0.0.1 localhost\r\n'
                  b'127.0.0.2 game-us.habbo.com # G-Earth replacement\r\n'
                  b'127.0.0.3 private.example # G-Earth replacement\r\n')
        hosts.write_bytes(original)
        with patch.object(app,'gearth_hosts_path',return_value=hosts), \
             patch.object(app,'APP_DIR',self.root/'AppData'):
            msg=app.repair_gearth_hosts()
        self.assertIn('Removed 1',msg)
        self.assertIn(b'private.example',hosts.read_bytes())
        self.assertNotIn(b'game-us.habbo.com',hosts.read_bytes())
        backup=list((self.root/'AppData'/'network-backups').glob('*.bak'))
        self.assertEqual(len(backup),1)
        self.assertEqual(backup[0].read_bytes(),original)

    def test_scoped_hosts_noop(self):
        from unittest.mock import patch
        hosts=self.root/'hosts'
        hosts.write_bytes(b'127.0.0.1 localhost\n')
        with patch.object(app,'gearth_hosts_path',return_value=hosts), \
             patch.object(app,'APP_DIR',self.root/'AppData'):
            self.assertIn('No tagged',app.repair_gearth_hosts())


    def test_saved_proxy_is_inactive_when_disabled(self):
        from unittest.mock import patch
        from types import ModuleType
        import sys
        class FakeKey:
            def __enter__(self):return self
            def __exit__(self,*args):return False
        fake=ModuleType('winreg')
        fake.HKEY_CURRENT_USER=1
        fake.KEY_READ=1
        fake.OpenKey=lambda *args:FakeKey()
        def query(h,name):
            return (0 if name=='ProxyEnable' else 'http=127.0.0.1:42822;https=127.0.0.1:42822',4)
        fake.QueryValueEx=query
        path=self.root/'hosts'
        path.write_bytes(b'127.0.0.1 localhost\n')
        with patch.object(app,'os') as mock_os, \
             patch.object(app,'gearth_hosts_path',return_value=path), \
             patch.dict(sys.modules,{'winreg':fake}):
            mock_os.name='nt'
            state=app.gearth_network_state()
        self.assertTrue(state['local_proxy'])
        self.assertFalse(state['proxy'])
        self.assertFalse(state['active_local_proxy'])
        self.assertFalse(state['unsafe'])

    def test_inactive_proxy_repair_is_noop(self):
        from unittest.mock import patch
        data={'error':'','proxy':False,'proxy_server':'127.0.0.1:42822',
              'local_proxy':True,'active_local_proxy':False}
        with patch.object(app,'os') as mock_os, \
             patch.object(app,'gearth_network_state',return_value=data):
            mock_os.name='nt'
            self.assertIn('already disabled',app.disable_active_local_proxy())

    def test_active_proxy_recovery_requests_user_approval(self):
        import inspect
        src=inspect.getsource(app.ChatOverlayApp._disable_local_proxy_ui)
        self.assertIn('messagebox.askyesno',src)
        self.assertIn('disable_active_local_proxy()',src)


    def test_single_window_migration_does_not_enable_autostart(self):
        from unittest.mock import patch
        cfg=self.root/'settings.json'
        settings=dict(gearth_auto_arm=False,gearth_minimize=False,
                      gearth_startup_safety_v104=True,gearth_visible_debug_v106=True,
                      gearth_startup_uia_v105=True,gearth_background_v108=True,
                      gearth_network_safety_v114=True)
        cfg.write_text(json.dumps(settings),encoding='utf-8')
        with patch.object(app,'APP_DIR',self.root),patch.object(app,'CONFIG_PATH',cfg):
            result=app.load_config()
        self.assertFalse(result['gearth_auto_arm'])
        self.assertTrue(result['gearth_minimize'])
        self.assertTrue(result['gearth_single_window_v116'])

    def test_unified_workspace_keeps_viewer_manual_and_advanced_controls(self):
        import inspect
        code=inspect.getsource(app.ChatOverlayApp._make_packet_panel)
        self.assertIn('command=self._connect_gearth',code)
        self.assertIn('command=self._launch_habbo_with_gearth',code)
        self.assertIn('self._engine_advanced_panel',code)
        toggle=inspect.getsource(app.ChatOverlayApp._toggle_engine_advanced)
        self.assertIn('pack_forget()',toggle)
        self.assertIn('before=self._packet_search_row',toggle)
        launch=inspect.getsource(app.ChatOverlayApp._launch_habbo_with_gearth)
        self.assertIn('_gearth_extension_port_responds(port)',launch)

if __name__=='__main__':
    unittest.main()
