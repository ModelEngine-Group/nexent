# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read one historical source section out of the consolidated v2.9.0 bundle."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MERGED = ROOT / "deploy/sql/migrations/v2.9.0_merged_migrations.sql"


def merged_migration_sql(section: str) -> str:
    """Return the named section body, byte-for-byte with the historical file.

    The bundle carries each source's leading copyright line once at the top,
    so the returned body omits that line; SQL semantics are unchanged.
    """
    text = MERGED.read_text(encoding="utf-8")
    marker = f"-- Source migration: {section}"
    start = text.index(marker)
    end = text.find("-- Source migration: ", start + len(marker))
    block = text[start:] if end == -1 else text[start:end]
    # Drop the two section header lines; keep the body exactly.
    return block.split("\n", 2)[2]