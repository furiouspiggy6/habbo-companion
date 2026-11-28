import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import Habbo_Update_Helper as helper


class TestRestorePrevious(unittest.TestCase):

    def test_failed_restore_rolls_back_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "install"
            data = base / "data"
            backup = data / "Backups" / "test_backup"

            root.mkdir()
            backup.mkdir(parents=True)

            existing = "Habbo_Companion.pyw"
            new = "Habbo_Update_Helper.py"

            (root / existing).write_text("Original")
            (root / "app_manifest.json").write_text(
                json.dumps({
                    "app_id": helper.APP_ID,
                    "version": "2.0.0",
                    "format": 1
                })
            )

            (backup / existing).write_text("Restored")
            (backup / new).write_text("New file")
            (backup / "app_manifest.json").write_text(
                json.dumps({
                    "app_id": helper.APP_ID,
                    "version": "1.0.0",
                    "format": 1
                })
            )

            real_copy = shutil.copy2

            def failing_copy(src, dst, *args, **kwargs):
                if Path(src) == backup / "app_manifest.json":
                    self.assertEqual(
                        (root / existing).read_text(),
                        "Restored"
                    )
                    self.assertTrue((root / new).is_file())
                    raise OSError("Simulated restore failure")
                return real_copy(src, dst, *args, **kwargs)

            with patch.object(helper, "data_folder", return_value=data):
                with patch.object(helper, "APP_FILES", (existing, new)):
                    with patch.object(helper.shutil, "copy2", side_effect=failing_copy):
                        with self.assertRaisesRegex(OSError, "Simulated restore failure"):
                            helper.restore_previous(
                                root, backup, no_restart=True
                            )

            self.assertEqual((root / existing).read_text(), "Original")
            self.assertFalse((root / new).exists())
            self.assertEqual(
                json.loads((root / "app_manifest.json").read_text())["version"],
                "2.0.0"
            )


if __name__ == "__main__":
    unittest.main()
