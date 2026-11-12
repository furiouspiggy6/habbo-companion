"""Regression for legacy update allowlists and self-contained application.

The v1.1.38 updater permits only:
  Habbo_Companion.pyw, Habbo_Update_Helper.py, README.txt, habbo-update.json
v1.1.39 also permits headless_transport.py; v1.1.40 added a second module.
Any newly named file in a ZIP must NOT be required for upgrade.
"""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from scripts.build_release import ROOT, APP_FILES, MANIFEST, build, bundled_application
from Habbo_Update_Helper import inspect_package

LEGACY_ALLOWLIST={"Habbo_Companion.pyw", "Habbo_Update_Helper.py", "README.txt"}


class LegacyUpdaterCompatibilityTests(unittest.TestCase):
    def test_bundled_app_compiles_without_separate_python_modules(self):
        app=bundled_application()
        text=app.decode("utf-8")
        compile(text, "Habbo_Companion.pyw", "exec")
        self.assertIn("class HeadlessLocalManager:", text)
        self.assertIn("class HeadlessLocalSession:", text)
        self.assertIn("def launch_local_classic(", text)
        self.assertIn("def parse_classic_ticket(", text)
        self.assertIn("HEADLESS_TEST_MAX_ACCOUNTS = MAX_ACCOUNTS", text)
        self.assertNotIn("from headless_transport import",text)
        self.assertNotIn("from local_classic_launch import",text)

    def test_zip_is_accepted_by_legacy_allowlist_and_current_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            for path in ("VERSION", "README.txt", "Habbo_Companion.pyw",
                         "Habbo_Update_Helper.py", "headless_transport.py",
                         "local_classic_launch.py"):
                shutil.copy2(ROOT/path,target/path)
            build(target)
            version=(target/"VERSION").read_text(encoding="utf-8").strip()
            package=target/f"Habbo_Companion_Update_v{version}.zip"
            with zipfile.ZipFile(package) as zf:
                names=zf.namelist()
                self.assertEqual(set(names),LEGACY_ALLOWLIST|{MANIFEST})
                self.assertEqual(len(names),4)
                self.assertEqual(len(names),len(set(names)))
                manifest=json.loads(zf.read(MANIFEST))
                self.assertEqual(set(manifest["files"]),LEGACY_ALLOWLIST)
                for name,digest in manifest["files"].items():
                    self.assertEqual(sha256(zf.read(name)).hexdigest(),digest)
                self.assertNotIn(b"from local_classic_launch import",
                                 zf.read("Habbo_Companion.pyw"))
                self.assertNotIn(b"from headless_transport import",
                                 zf.read("Habbo_Companion.pyw"))
            info=inspect_package(package,current_version="1.1.38")
            self.assertEqual(info["version"],version)
            info=inspect_package(package,current_version="1.1.39")
            self.assertEqual(info["version"],version)
            info=inspect_package(package,current_version="1.1.40")
            self.assertEqual(info["version"],version)
            feed=json.loads((target/"latest.json").read_text(encoding="utf-8"))
            self.assertEqual(feed["sha256"],sha256(package.read_bytes()).hexdigest())

    def test_import_anchor_changes_cause_build_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            for path in ("Habbo_Companion.pyw", "headless_transport.py",
                         "local_classic_launch.py"):
                shutil.copy2(ROOT/path,target/path)
            source=(target/"Habbo_Companion.pyw").read_text(encoding="utf-8")
            source=source.replace("from local_classic_launch import",
                                  "from unexpected_module import")
            (target/"Habbo_Companion.pyw").write_text(source,encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"module imports changed"):
                bundled_application(target)


if __name__=="__main__":
    unittest.main()
