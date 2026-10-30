#!/usr/bin/env python3
"""Repository Secret & Security Policy Scanner for ResearchFlow.

Checks tracked and working-tree files for accidental credential patterns,
forbidden `.env` files, private keys, or unsafe `VITE_` secret variables.
Never prints matched secret values to stdout.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "private_uploads",
    "artifacts",
    "skills",
    ".pytest_cache",
}

FORBIDDEN_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "service-account.json",
    "id_rsa",
}

SECRET_PATTERNS = [
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Private Key Header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub Personal Access Token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("Slack Token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Unsafe Public VITE Secret Variable", re.compile(r"VITE_[A-Z0-9_]*(?:SECRET|PASSWORD|PRIVATE_KEY)")),
]

KNOWN_TOP_ENTRIES = [
    ".gitignore",
    ".env.example",
    "docker-compose.yml",
    "README.md",
    "setup_local_pc.ps1",
    "start_local_pc.bat",
    "backend",
    "frontend",
    "docs",
    "scripts",
    ".github",
]


def iter_repo_files(root: Path) -> list[Path]:
    found: set[Path] = set()
    for p in root.rglob("*"):
        if p.is_file():
            found.add(p)
    for entry in KNOWN_TOP_ENTRIES:
        target = root / entry
        if target.is_file():
            found.add(target)
        elif target.is_dir():
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fn in filenames:
                    found.add(Path(dirpath) / fn)
    return sorted(found)


def scan_repository() -> int:
    issues: list[str] = []
    scanned_count = 0

    for f in FORBIDDEN_FILENAMES:
        if (ROOT / f).exists():
            issues.append(f"[FORBIDDEN_FILE] {f} must not be present in committed tree.")

    for path in iter_repo_files(ROOT):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name in FORBIDDEN_FILENAMES or path.suffix in (".pem", ".key", ".p12", ".pfx", ".sqlite3", ".db"):
            issues.append(f"[FORBIDDEN_FILE] {rel} must not be present in committed tree.")
            continue

        if rel.as_posix() == "scripts/security_audit.py":
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        scanned_count += 1
        for label, pattern in SECRET_PATTERNS:
            for line_no, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    issues.append(f"[SECRET_PATTERN] {rel}:{line_no} matched '{label}' (value redacted)")

    if issues:
        print(f"SECURITY AUDIT FAILED with {len(issues)} issue(s):")
        for item in issues:
            print("  -", item)
        return 1

    print(f"SECURITY AUDIT PASSED: Scanned {scanned_count} source files. Zero secrets or forbidden files detected.")
    return 0


if __name__ == "__main__":
    sys.exit(scan_repository())
