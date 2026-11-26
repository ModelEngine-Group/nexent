# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Numbered display titles for newly branched conversations."""

import re
from typing import Iterable, Optional


CONVERSATION_TITLE_MAX_LENGTH = 100
LEGACY_BRANCH_SUFFIX = "（分支）"
NUMBERED_TITLE = re.compile(r"(.*?)\s*\(([0-9]+)\)")


def build_branch_title(
    source_title: Optional[str], existing_titles: Iterable[Optional[str]] = ()
) -> str:
    """Pick an unused numbered title while preserving the column length."""
    base = (source_title or "").strip()
    if base.endswith(LEGACY_BRANCH_SUFFIX):
        base = base[:-len(LEGACY_BRANCH_SUFFIX)].rstrip()
    number = 2
    match = NUMBERED_TITLE.fullmatch(base)
    if match:
        base = match.group(1).rstrip()
        number = max(2, int(match.group(2)) + 1)
    occupied = set(existing_titles)
    while True:
        suffix = f" ({number})"
        # An arbitrary user title can contain a very long numeric suffix.
        # Treat that case as ordinary source text rather than exceeding the cap.
        if len(suffix) > CONVERSATION_TITLE_MAX_LENGTH:
            base = (source_title or "").strip()
            number = 2
            continue
        keep = CONVERSATION_TITLE_MAX_LENGTH - len(suffix)
        candidate = f"{base[:keep].rstrip()}{suffix}".strip()
        if candidate not in occupied:
            return candidate
        number += 1
