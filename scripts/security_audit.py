#!/usr/bin/env python3
"""Pre-release checks for accidentally committed secrets and private user data.

Scans Git-tracked source, not files from the user's local AppData. This is a
conservative safety net, not a substitute for GitHub secret scanning or a
professional security audit. The entire release is still tested separately.
"""
from __future__ import annotations

import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

PRIVATE_DIRS = {
    "chat_logs", "persona_logs", "account_browser_profiles", "browser_profiles",
    "backups", "downloads", "packet_exports", "debug_exports", "fuzz_lab",
}
PRIVATE_NAMES = {
    ".env", "settings.json", "credentials.json", "cookies.json",
    "session.json", "secrets.json", "openai.key", "github.token",
}
PRIVATE_SUFFIXES = (".pem", ".p12", ".pfx", ".pcap", ".pcapng", ".sqlite",
                    ".sqlite3", ".db", ".log")
HIGH_CONFIDENCE = (
    ("private key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("GitHub credential", re.compile(
        r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_-]{20,}")),
    ("OpenAI credential", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}")),
    ("Google credential", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}")),
    ("Slack credential", re.compile(
        r"\bxox(?:b|p|a|r|s)-[A-Za-z0-9-]{22,}")),
)
LITERAL_SECRET = re.compile(
    r"""(?ix)
    (?:(?:['"])?(?:openai_api_key|github_token|api_key|client_secret|
    access_token|refresh_token|sso_ticket|password|passwd|auth_cookie)
    (?:['"])?\s*[:=]\s*)
    (['"])([^'"\r\n]{12,})\1
    """)
NON_SECRETS = re.compile(
    r"(?i)(?:dummy|example|fake|fixture|test|sample|placeholder|redacted|"
    r"none|invalid|not-real|replace-me|your[_ -]|<[^>]+>|\{[^}]+\})")


def tracked_files(root=ROOT):
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [Path(x.decode("utf-8")) for x in
            result.stdout.split(b"\0") if x]


def scan_paths(root, paths):
    """Return descriptions of security issues without echoing secret values."""
    issues = []
    for relative in paths:
        posix = relative.as_posix()
        parts = [p.casefold() for p in relative.parts]
        basename = parts[-1]
        if (any(p in PRIVATE_DIRS for p in parts[:-1])
                or basename in PRIVATE_NAMES
                or basename.startswith(".env.")
                or any(basename.endswith(ext) for ext in PRIVATE_SUFFIXES)):
            issues.append(f"{posix}: private file or runtime capture tracked by Git")
            continue
        path = root / relative
        if (not path.is_file() or path.is_symlink() or
                path.suffix.casefold() in {".zip", ".png", ".jpg", ".jpeg",
                                          ".gif", ".ico", ".webp"}):
            continue
        if path.stat().st_size > 1_500_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for title, regex in HIGH_CONFIDENCE:
            for match in regex.finditer(text):
                issues.append(
                    f"{posix}:{text.count(chr(10), 0, match.start())+1}: "
                    f"possible {title} (value omitted)")
        # Literal generic credentials in tests are usually fixtures. Still
        # scan tests for recognizable provider credentials and private keys.
        if relative.parts[0] == "tests":
            continue
        for match in LITERAL_SECRET.finditer(text):
            if NON_SECRETS.search(match.group(2)):
                continue
            issues.append(
                f"{posix}:{text.count(chr(10), 0, match.start())+1}: "
                "possible hardcoded credential (value omitted)")
    return issues


def main():
    try:
        issues = scan_paths(ROOT, tracked_files(ROOT))
    except (OSError, subprocess.CalledProcessError) as exc:
        print("Security check could not inspect Git-tracked files:", type(exc).__name__)
        return 2
    if issues:
        print("Security audit FAILED: do not publish the release.")
        for issue in issues:
            print(" -", issue)
        return 1
    print("Security audit passed: no obvious tracked credentials or private user logs.")
    print("Note: this is pattern-based and cannot prove the application is secure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
