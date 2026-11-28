"""Official Habbo.com ticket parsing and local-only Classic process launch."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

import local_classic_launch as launch

SAMPLE="f263b007-1ad2-41dd-9ae3-e2cd8aac018f"


class TicketParserTests(unittest.TestCase):
    def test_plain_and_deeplink_same_ticket(self):
        plain=launch.parse_classic_ticket("hhus."+SAMPLE+".V4.dan.alt100")
        deep=launch.parse_classic_ticket(
            "habbo://hab?server=hhus&token="+SAMPLE+".V4.dan.alt100")
        self.assertEqual(plain,deep)
        self.assertEqual(plain.server_id,"hhus")
        self.assertEqual(plain.secret,SAMPLE+".V4")
        self.assertEqual(plain.username,"dan.alt100")
        self.assertNotIn(SAMPLE,repr(plain))

    def test_token_without_username_is_still_supported(self):
        result=launch.parse_classic_ticket("hhus."+SAMPLE+".V4")
        self.assertIsNone(result.username)

    def test_unsupported_servers_and_ticket_injection_rejected(self):
        invalid=(
            "", "blah", "hhes."+SAMPLE+".V4", "hhbr."+SAMPLE+".V4",
            "hhus."+SAMPLE+".V4; calc.exe",
            "hhus."+SAMPLE+".V4\n--malicious",
            "hhus."+SAMPLE+".V4/..",
            "habbo://evil?server=hhus&token="+SAMPLE+".V4",
            "habbo://hab/path?server=hhus&token="+SAMPLE+".V4",
            "habbo://hab?server=hhes&token="+SAMPLE+".V4",
            "habbo://hab?server=hhus&server=hhus&token="+SAMPLE+".V4",
            "habbo://hab?server=hhus&token="+SAMPLE+".V4&x=1",
            "https://bobba.example/?server=hhus&token="+SAMPLE+".V4",
        )
        for raw in invalid:
            with self.subTest(raw=raw[:50]):
                with self.assertRaises(ValueError):
                    launch.parse_classic_ticket(raw)

    def test_invalid_executable_rejected(self):
        with self.assertRaises(ValueError):
            launch.official_local_executable("https://www.habbo.com/Habbo.exe")
        with self.assertRaises(ValueError):
            launch.official_local_executable("C:/missing/Habbo.exe")

    def test_launch_invokes_only_existing_local_exe_and_correct_args(self):
        # Only launch a mock process; no actual Habbo login or outbound traffic.
        ticket=launch.parse_classic_ticket("hhus."+SAMPLE+".V4")
        fake_exe=Path("/local/example/Habbo.exe")
        with (mock.patch.object(launch,"os",SimpleNamespace(name="nt")),
              mock.patch.object(launch,"official_local_executable",return_value=fake_exe),
              mock.patch.object(launch.subprocess,"Popen") as popen):
            popen.return_value.pid=25001
            pid=launch.launch_local_classic(fake_exe,ticket)
        self.assertEqual(pid,25001)
        args=popen.call_args.args[0]
        self.assertEqual(args,[str(fake_exe),"-server","hhus",
                               "-ticket",SAMPLE+".V4"])
        self.assertEqual(popen.call_args.kwargs["cwd"],str(fake_exe.parent))
        self.assertTrue(popen.call_args.kwargs["close_fds"])
        self.assertNotIn("Bobba",repr(popen.call_args))

    def test_non_windows_and_unrecognised_hotel_dont_spawn(self):
        ticket=launch.parse_classic_ticket("hhus."+SAMPLE+".V4")
        with (mock.patch.object(launch,"os",SimpleNamespace(name="posix")),
              mock.patch.object(launch.subprocess,"Popen") as popen):
            with self.assertRaises(OSError):
                launch.launch_local_classic("/tmp/Habbo.exe",ticket)
            popen.assert_not_called()


class CompanionDirectUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.app=(cls.root/"Habbo_Companion.pyw").read_text(encoding="utf-8")

    def test_obsolete_launcher_ui_and_callbacks_are_removed(self):
        for name in ('_make_direct_classic_panel', '_direct_render',
                     '_direct_ticket_queue', 'direct_table', 'direct_ticket_var',
                     'direct_classic_exe_var', '_direct_launch_worker',
                     'direct_ticket_fetched', 'direct_launch_finished'):
            self.assertNotIn(name, self.app)

    def test_accounts_keeps_exactly_four_launch_modes_and_status(self):
        tree=ast.parse(self.app)
        method=next(n for n in ast.walk(tree)
                    if isinstance(n,ast.FunctionDef)
                    and n.name=='_make_accounts_panel')
        modes=next(ast.literal_eval(n.iter) for n in ast.walk(method)
                   if isinstance(n,ast.For)
                   and isinstance(n.iter,ast.Tuple)
                   and isinstance(n.target,ast.Tuple)
                   and [getattr(t,'id',None) for t in n.target.elts]
                   ==['label','value'])
        self.assertEqual(dict(modes), {
            'HabboAIR without G-Earth':'air',
            'HabboAIR with G-Earth':'gearth',
            'Clientless Bot without G-Earth':'clientless',
            'Clientless Bot with G-Earth':'clientless_gearth'})
        self.assertEqual(len(modes),4)
        self.assertIn("'launch_state'",ast.get_source_segment(self.app,method))

    def test_licensing_independent_module_uses_no_bobba_networking(self):
        module=(self.root/"local_classic_launch.py").read_text(encoding="utf-8")
        self.assertNotIn("bobba-launcher",module)
        self.assertNotIn("game.bobbapacket.com",module)
        self.assertNotIn("requests.get",module)
        self.assertNotIn("urlopen",module)
        self.assertNotIn("subprocess.run(['powershell",module)

    def test_verified_update_contains_direct_launcher(self):
        for path in ("scripts/build_release.py","Habbo_Update_Helper.py",
                     "Install_Habbo_Companion.py"):
            text=(self.root/path).read_text(encoding="utf-8")
            self.assertIn("local_classic_launch.py",text)


if __name__ == "__main__":
    unittest.main()
