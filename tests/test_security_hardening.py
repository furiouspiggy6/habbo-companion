"""Security checks that protect the same release for all Companion users."""
from pathlib import Path
import runpy
import tempfile
import unittest

from Habbo_Update_Helper import (
    TRUSTED_RELEASE_ROOT, validate_official_release_url,
)
from scripts.security_audit import scan_paths

ROOT = Path(__file__).resolve().parents[1]


class UpdaterTrustBoundaryTests(unittest.TestCase):
    def test_accept_only_official_manifest_and_versioned_zip(self):
        manifest=TRUSTED_RELEASE_ROOT+"latest.json"
        package=TRUSTED_RELEASE_ROOT+"Habbo_Companion_Update_v1.1.83.zip"
        self.assertEqual(validate_official_release_url(manifest,"manifest"),
                         manifest)
        self.assertEqual(validate_official_release_url(package,"package"),package)
        self.assertEqual(validate_official_release_url(
            package,"package",version="1.1.83"),package)

    def test_reject_external_or_malformed_update_sources(self):
        manifest=TRUSTED_RELEASE_ROOT+"latest.json"
        package=TRUSTED_RELEASE_ROOT+"Habbo_Companion_Update_v1.1.83.zip"
        bad_manifests=[
            "http://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/latest.json",
            "https://evil.example/latest.json",
            "https://raw.githubusercontent.com.attacker.example/furiouspiggy6/habbo-companion/main/latest.json",
            "https://raw.githubusercontent.com@evil.example/latest.json",
            manifest+"?token=test",
            manifest+"#other",
            manifest.replace("/main/","/other/"),
            manifest.replace("raw.githubusercontent.com","RAW.GITHUBUSERCONTENT.COM"),
        ]
        bad_packages=[
            "https://evil.example/Companion_Update_v1.1.83.zip",
            package.replace("/main/","/fork/"),
            package+"?download=1",
            package.replace("1.1.83","1.1.82"),
            package.replace(".zip",".exe"),
        ]
        for url in bad_manifests:
            with self.subTest(url=url),self.assertRaises(ValueError):
                validate_official_release_url(url,"manifest")
        for url in bad_packages:
            with self.subTest(url=url),self.assertRaises(ValueError):
                validate_official_release_url(url,"package",version="1.1.83")

    @classmethod
    def setUpClass(cls):
        cls.app=runpy.run_path(str(ROOT/"Habbo_Companion.pyw"),
                               run_name="companion_security_tests")

    def test_redirects_cannot_leave_official_publisher(self):
        handler=self.app["_NoUpdateRedirect"]()
        with self.assertRaisesRegex(ValueError,"redirects"):
            handler.redirect_request(None,None,302,"Moved",{},
                                     "https://attacker.example/release.zip")

    def test_default_packet_export_contains_no_chat_or_secret_payload(self):
        exporter=self.app["packet_export_record"]
        private="User: hello, my private ticket is ABC123 and pass is xxxxx"
        safe=exporter("13:05:10","Incoming",private)
        self.assertIn("payload omitted",safe)
        self.assertNotIn("hello",safe)
        self.assertNotIn("ticket is",safe)
        self.assertNotIn("ABC123",safe)
        self.assertEqual(safe.count("\n"),1)

    def test_sensitive_diagnostics_are_masked(self):
        redact=self.app["redact_sensitive_diagnostic"]
        bearer="Bearer "+"A"*36
        key="sk-"+"B"*32
        value="sso_ticket="+"C"*36
        message=f"request: {bearer}, {key}, {value}"
        cleaned=redact(message)
        for secret in (bearer,key,"C"*36):
            self.assertNotIn(secret,cleaned)
        self.assertIn("REDACTED",cleaned)
        raw=self.app["packet_export_record"](
            "14:10:10","Outgoing",message,include_contents=True)
        self.assertNotIn(key,raw)
        self.assertNotIn(bearer,raw)

    def test_packet_export_and_online_updates_use_security_guards(self):
        src=(ROOT/"Habbo_Companion.pyw").read_text(encoding="utf-8")
        self.assertIn("packet_export_record(",src)
        self.assertIn("default='no'",src)
        self.assertIn("validate_official_release_url(",src)
        self.assertIn("_open_official_update(req,timeout=12)",src)
        self.assertIn("_open_official_update(req,timeout=25)",src)


class TrackedSourceScannerTests(unittest.TestCase):
    def test_flags_private_paths_and_representative_fake_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"app.py").write_text("OPENAI_API_KEY='"+("A"*35)+"'\n")
            (root/"safe.py").write_text("DEFAULT_MODEL='gpt-5-mini'\n")
            (root/".env").write_text("something=value\n")
            (root/"chat_logs").mkdir()
            (root/"chat_logs"/"Alice.txt").write_text("Hello!\n")
            findings=scan_paths(root,[Path("app.py"),Path("safe.py"),
                                      Path(".env"),Path("chat_logs/Alice.txt")])
            self.assertEqual(len(findings),3)
            self.assertFalse(any("safe.py" in item for item in findings))
            self.assertTrue(any("app.py" in item for item in findings))
            self.assertTrue(any(".env" in item for item in findings))
            self.assertTrue(any("chat_logs/Alice.txt" in item
                                for item in findings))

    def test_does_not_print_the_secret_value_into_scan_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            key="sk-"+("R"*40)
            (root/"secrets.py").write_text("VALUE='"+key+"'\n")
            issues=scan_paths(root,[Path("secrets.py")])
            self.assertEqual(len(issues),1)
            self.assertNotIn(key," ".join(issues))


if __name__=="__main__":
    unittest.main()
