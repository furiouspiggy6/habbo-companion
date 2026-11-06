#!/usr/bin/env python3
"""Build a checked Habbo Companion ZIP and raw-GitHub update feed.

This only packages source files already committed to this repository.
No secrets, Habbo client files, chat logs, or user settings are included.
"""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    raise SystemExit("Invalid VERSION")
names = ("Habbo_Companion.pyw", "Habbo_Update_Helper.py", "README.txt")
files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
package_name = f"Habbo_Companion_Update_v{version}.zip"
meta = {"app_id": "habbo-companion", "format": 1, "version": version, "files": files}
with zipfile.ZipFile(ROOT / package_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for name in names:
        zf.write(ROOT / name, arcname=name)
    zf.writestr("habbo-update.json", json.dumps(meta, indent=2) + "\n")
digest = hashlib.sha256((ROOT / package_name).read_bytes()).hexdigest()
feed = {
    "app_id": "habbo-companion",
    "version": version,
    "package_url": "https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/" + package_name,
    "sha256": digest,
}
(ROOT / "latest.json").write_text(json.dumps(feed, indent=2) + "\n", encoding="utf-8")
(ROOT / "app_manifest.json").write_text(json.dumps({"app_id":"habbo-companion","version":version,"format":1}, indent=2)+"\n",encoding="utf-8")
print(f"Built {package_name} SHA256={digest}")
