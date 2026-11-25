#!/usr/bin/env python3
"""Build a backward-compatible, SHA-256-checked Habbo Companion update.

Legacy installations (including v1.1.38) accept only THREE application
files plus habbo-update.json. New feature modules must be embedded into
Habbo_Companion.pyw for ZIP updates to install without manual bootstrapping.

Fresh installs from source still use the normal independent .py modules.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("Habbo_Companion.pyw", "Habbo_Update_Helper.py", "README.txt")
MANIFEST = "habbo-update.json"

BUNDLED_FILES = (
    "headless_transport.py",
    "local_classic_launch.py",
    "habbo_tcp.py",
    "clientless_bot.py",
    "clientless_gearth_bridge.py",
    "persona_responder.py",
    "persona_responder_ui.py",
)
APP_ANCHOR = "\nAPP_NAME = 'Habbo View Chat'\n"


def _remove_local_imports(source, modules):
    """Remove the expected top-level imports and retain any alias bindings."""
    lines = source.splitlines(keepends=True)
    imports = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ImportFrom) or node.level or node.module not in modules:
            continue
        if node.module in imports or any(name.name == "*" for name in node.names):
            raise ValueError(f"Companion module imports changed: {node.module}")
        tail = lines[node.end_lineno - 1].encode("utf-8")[node.end_col_offset:].strip()
        if node.col_offset or (tail and not tail.startswith(b"#")):
            raise ValueError(f"Expected a standalone import for {node.module}")
        imports[node.module] = "".join(
            f"{name.asname} = {name.name}\n" for name in node.names if name.asname
        )
        for index in range(node.lineno - 1, node.end_lineno):
            lines[index] = ""
    if missing := set(modules) - imports.keys():
        raise ValueError(f"Companion module imports changed: missing {', '.join(sorted(missing))}")
    return "".join(lines), imports


def bundled_application(root=ROOT):
    """Generate a single-file application using our own local module sources."""
    root = Path(root)
    app = (root / APP_FILES[0]).read_text(encoding="utf-8")
    module_names = [Path(filename).stem for filename in BUNDLED_FILES]
    app, aliases = _remove_local_imports(app, module_names)
    if app.count(APP_ANCHOR) != 1:
        raise ValueError("Companion app constant anchor changed")

    modules = ["# Bundled local modules for compatibility with old updaters.\n"]
    for filename, module in zip(BUNDLED_FILES, module_names):
        source = (root / filename).read_text(encoding="utf-8")
        marker = "from __future__ import annotations\n"
        if source.count(marker) != 1:
            raise ValueError("Unexpected module header: " + filename)
        source = source.replace(marker, "", 1)
        if module == "persona_responder_ui":
            source, dependencies = _remove_local_imports(source, ("persona_responder",))
            source = dependencies["persona_responder"] + source
        modules.append(f"\n# Bundled source: {filename}\n{source.strip()}\n{aliases[module]}")

    app = app.replace(APP_ANCHOR, "\n" + "".join(modules) + APP_ANCHOR, 1)
    compile(app, str(root / APP_FILES[0]), "exec")
    if any(f"from {module} import" in app for module in module_names):
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
