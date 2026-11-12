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

    def test_direct_ui_runs_only_local_executable_no_browser_steps(self):
        section=self.app.split("    def _make_direct_classic_panel(",1)[1].split(
            "    def _make_accounts_panel(",1)[0]
        self.assertIn("Launch all queued",section)
        self.assertIn("Queue ticket locally",section)
        self.assertIn("launch_local_classic(exe,ticket)",section)
        self.assertNotIn("account_browser_command",section)
        self.assertNotIn("account_saved_login_read",section)
        self.assertNotIn("urllib.request",section)
        self.assertIn("self._direct_ticket_queue.pop(ident,None)",section)
        self.assertIn("self.direct_ticket_var.set('')",section)

    def test_no_tokens_persist_in_settings(self):
        section=self.app.split("    def _make_direct_classic_panel(",1)[1].split(
            "    def _make_accounts_panel(",1)[0]
        self.assertIn("self.config['direct_classic_executable']=str(exe)",section)
        self.assertNotIn("self.config['direct_ticket",section)
        self.assertNotIn("self.config['direct_ss",section)
        self.assertIn("self._direct_ticket_queue.clear()",self.app)
        self.assertIn("self.notebook.add(direct,text='  Direct Classic  ')",self.app)

    def test_ui_handles_packet_queue_status_on_main_thread(self):
        self.assertIn("if item[0]=='direct_launch_state':",self.app)
        self.assertIn("if item[0]=='direct_launch_finished':",self.app)
        self.assertIn("self._direct_launch_running=False",self.app)

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
