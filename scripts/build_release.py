#!/usr/bin/env python3
"""Build a backward-compatible, SHA-256-checked Habbo Companion update.

Legacy installations (including v1.1.38) accept only THREE application
files plus habbo-update.json. New feature modules must be embedded into
Habbo_Companion.pyw for ZIP updates to install without manual bootstrapping.

Fresh installs from source still use the normal independent .py modules.
"""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("Habbo_Companion.pyw", "Habbo_Update_Helper.py", "README.txt")
MANIFEST = "habbo-update.json"

# Anchors intentionally exact: a renamed import must make packaging fail
# loudly, rather than silently ship an app with missing dependencies.
HEADLESS_IMPORT = (
    "from headless_transport import (HeadlessLocalManager, LocalHeadlessTestServer,\n"
    "                                MAX_ACCOUNTS as HEADLESS_TEST_MAX_ACCOUNTS)\n"
)
DIRECT_IMPORT = (
    "from local_classic_launch import (parse_classic_ticket, official_local_executable,\n"
    "                                  launch_local_classic)\n"
)
APP_ANCHOR = "\nAPP_NAME = 'Habbo View Chat'\n"


def bundled_application(root=ROOT):
    """Generate a single-file application using our own local module sources."""
    root = Path(root)
    app = (root / APP_FILES[0]).read_text(encoding="utf-8")
    if app.count(HEADLESS_IMPORT) != 1 or app.count(DIRECT_IMPORT) != 1:
        raise ValueError("Companion module imports changed; update bundle anchors")
    if app.count(APP_ANCHOR) != 1:
        raise ValueError("Companion app constant anchor changed")

    modules = []
    for filename in ("headless_transport.py", "local_classic_launch.py"):
        source = (root / filename).read_text(encoding="utf-8")
        marker = "from __future__ import annotations\n"
        if source.count(marker) != 1:
            raise ValueError("Unexpected module header: " + filename)
        source = source.replace(marker, "", 1)
        modules.append("# Bundled source: " + filename + "\n" + source.strip() + "\n")

    app = app.replace(HEADLESS_IMPORT, "", 1)
    app = app.replace(DIRECT_IMPORT, "", 1)
    embedded = (
        "\n# Bundled local modules for compatibility with old updaters.\n"
        + modules[0]
        + "\nHEADLESS_TEST_MAX_ACCOUNTS = MAX_ACCOUNTS\n"
        + modules[1]
    )
    app = app.replace(APP_ANCHOR, "\n" + embedded + APP_ANCHOR, 1)
    compile(app, str(root / APP_FILES[0]), "exec")
    if "from headless_transport import" in app or "from local_classic_launch import" in app:
        raise ValueError("Unbundled application dependency remains")
    return app.encode("utf-8")


def build(root=ROOT):
    root = Path(root)
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid VERSION")

    # Keep ZIP contents within the allowlist of v1.1.38 and earlier.
    payloads = {
        "Habbo_Companion.pyw": bundled_application(root),
        "Habbo_Update_Helper.py": (root / "Habbo_Update_Helper.py").read_bytes(),
        "README.txt": (root / "README.txt").read_bytes(),
    }
    digests = {name: hashlib.sha256(data).hexdigest()
               for name, data in payloads.items()}
    package_name = f"Habbo_Companion_Update_v{version}.zip"
    meta = {"app_id": "habbo-companion", "format": 1,
            "version": version, "files": digests}
    with zipfile.ZipFile(root / package_name, "w",
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for name, data in payloads.items():
            zf.writestr(name, data)
        zf.writestr(MANIFEST, json.dumps(meta, indent=2) + "\n")
    digest = hashlib.sha256((root / package_name).read_bytes()).hexdigest()
    feed = {
        "app_id": "habbo-companion",
        "version": version,
        "package_url": "https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/" + package_name,
        "sha256": digest,
    }
    (root / "latest.json").write_text(
        json.dumps(feed, indent=2) + "\n", encoding="utf-8")
    (root / "app_manifest.json").write_text(
        json.dumps({"app_id": "habbo-companion", "version": version,
                    "format": 1}, indent=2) + "\n", encoding="utf-8")
    print(f"Built {package_name} SHA256={digest}")


if __name__ == "__main__":
    build()
