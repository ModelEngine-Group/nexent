#!/usr/bin/env python3
# coding: utf-8
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Copyright header checker for the Nexent repository.

Modes:
  1. Full scan (default): scan the whole repository for target files.
  2. Explicit files: pass paths via --files or --files-from (CI incremental mode).
  3. Fix mode: --fix inserts the standard header into files that lack it.

Exit code 1 when any checked file is missing the required header in check mode.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Standard header text inserted by --fix (aligned with NOTICE).
COPYRIGHT_TEXT = "Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved."

# Loose matching pattern so existing year variants keep passing, e.g.
#   Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
#   Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved
COPYRIGHT_PATTERN = re.compile(
    r"Copyright\s*\(c\)\s*(?:\d{4}(?:\s*[-,\u2013]\s*\d{4})*\s*,?\s*)?"
    r"Huawei\s+Technologies\s+Co\.,?\s*Ltd\.?",
    re.IGNORECASE,
)

# Encoding declaration lines such as "# -*- coding: utf-8 -*-" or "# coding: utf-8".
CODING_PATTERN = re.compile(r"^#\s*(?:-\*-\s*)?coding[:=]", re.IGNORECASE)

# Comment prefix per target extension.
COMMENT_STYLES = {
    ".py": "#",
    ".sh": "#",
    ".sql": "--",
    ".js": "//",
    ".jsx": "//",
    ".mjs": "//",
    ".ts": "//",
    ".tsx": "//",
}

# Search the header within the first N lines of the file.
HEADER_SEARCH_LINES = 10
# Give up after N non-trivial content lines without a copyright match.
CONTENT_LINE_LIMIT = 5

# Directories never scanned in full-scan mode.
EXCLUDED_DIRS = {
    ".git",
    ".cache",
    ".ua",
    ".slidep",
    ".trae",
    ".idea",
    ".vscode",
    "node_modules",
    ".next",
    "dist",
    "build",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "assets",
}

# Generated files exempt from the header requirement (relative path or bare name).
EXCLUDED_FILES = {
    "next-env.d.ts",
}


def rel(path: Path) -> str:
    """Return a repo-relative display path."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def is_target_file(path: Path) -> bool:
    """True when the file is in scope of the copyright check."""
    if path.name in EXCLUDED_FILES:
        return False
    if path.suffix.lower() not in COMMENT_STYLES:
        return False
    try:
        parts = path.resolve().relative_to(REPO_ROOT).parts
    except (OSError, ValueError):
        return False
    return not any(part in EXCLUDED_DIRS or part.startswith(".") for part in parts[:-1])


def has_header(path: Path) -> bool:
    """True when the copyright line appears in the file header zone."""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        print(f"warning: cannot read {rel(path)}", file=sys.stderr)
        return True

    content_seen = 0
    for line in lines[:HEADER_SEARCH_LINES]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#!"):
            continue
        if CODING_PATTERN.match(stripped):
            continue
        if COPYRIGHT_PATTERN.search(stripped):
            return True
        content_seen += 1
        if content_seen >= CONTENT_LINE_LIMIT:
            return False
    return False


def fix_file(path: Path) -> bool:
    """Insert the standard header after shebang/coding lines. True on success."""
    try:
        raw = path.read_bytes()
    except OSError:
        print(f"warning: cannot read {rel(path)}", file=sys.stderr)
        return False

    has_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        print(f"warning: skip non-utf8 file {rel(path)}", file=sys.stderr)
        return False

    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"

    insert_at = 0
    for index, line in enumerate(lines[:3]):
        stripped = line.strip()
        if stripped.startswith("#!") or CODING_PATTERN.match(stripped):
            insert_at = index + 1
        else:
            break

    style = COMMENT_STYLES[path.suffix.lower()]
    lines.insert(insert_at, f"{style} {COPYRIGHT_TEXT}{newline}")
    # Keep a blank separator line between the header and the body when needed.
    if insert_at + 1 < len(lines) and lines[insert_at + 1].strip():
        lines.insert(insert_at + 1, newline)

    payload = "".join(lines).encode("utf-8")
    if has_bom:
        payload = b"\xef\xbb\xbf" + payload
    path.write_bytes(payload)
    print(f"  [fixed]    {rel(path)}")
    return True


def iter_repo_files() -> list[Path]:
    """Collect in-scope files across the repository (full-scan mode)."""
    collected = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [
            d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            candidate = Path(dirpath) / name
            if name in EXCLUDED_FILES:
                continue
            if candidate.suffix.lower() in COMMENT_STYLES:
                collected.append(candidate)
    return collected


def read_file_list(list_path: Path) -> list[Path]:
    """Read one path per line; missing files are skipped silently (deleted in PR)."""
    if not list_path.exists():
        return []
    files = []
    for line in list_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        candidate = Path(line) if Path(line).is_absolute() else REPO_ROOT / line
        if candidate.exists():
            files.append(candidate)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="specific files to check (default: full repository scan)",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        help="specific files to check",
    )
    parser.add_argument(
        "--files-from",
        metavar="FILE",
        help="read the file list line-by-line from a text file (CI mode)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="insert the standard header into files that lack it",
    )
    args = parser.parse_args()

    explicit = [Path(p) for p in (args.paths + (args.files or []))]
    if args.files_from:
        explicit.extend(read_file_list(Path(args.files_from)))

    if explicit:
        targets = [p for p in explicit if p.is_file() and is_target_file(p)]
        scope = "provided file list"
    else:
        targets = iter_repo_files()
        scope = "full repository scan"

    print(f"Copyright header check ({scope}): {len(targets)} target file(s)")

    missing = [path for path in targets if not has_header(path)]
    if not missing:
        print("OK: all target files carry the required copyright header.")
        return 0

    for path in missing:
        print(f"  [missing]  {rel(path)}")

    print(
        f"\n{len(missing)} file(s) missing the required header. "
        "Expected comment line within the file header:\n"
        f"    {COPYRIGHT_TEXT}\n"
        "Comment style: '#' for .py/.sh, '--' for .sql, '//' for .ts/.tsx/.js/.jsx/.mjs.\n"
        "Fix automatically with:\n"
        "    python scripts/check_copyright.py --fix <files...>"
    )

    if args.fix:
        for path in missing:
            fix_file(path)
        print(f"Inserted headers into {len(missing)} file(s). Re-run to verify.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
