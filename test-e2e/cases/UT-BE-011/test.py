"""D1 backend unit contracts derived from the functional baseline.

These tests import production modules directly and never import Nexent's old
``test`` package. External services and databases are replaced at the module
boundary; assertions describe user-visible policy, not implementation calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


STAGE = pytest.mark.stage("D1")






def _profile(version: str = "2026-01") -> SimpleNamespace:
    return SimpleNamespace(
        context_window_tokens=128_000,
        max_input_tokens=120_000,
        max_output_tokens=8_000,
        default_output_reserve_tokens=4_000,
        tokenizer_family="openai",
        capability_profile_version=version,
    )


















@STAGE
@pytest.mark.case_id("UT-BE-011")
def test_range_header_accepts_single_range_and_rejects_invalid_ranges() -> None:
    from apps.file_management_app import _parse_range_header

    assert _parse_range_header("bytes=0-9", 100) == (0, 9)
    assert _parse_range_header("bytes=90-", 100) == (90, 99)
    assert _parse_range_header("bytes=-10", 100) == (90, 99)
    assert _parse_range_header("bytes=95-500", 100) == (95, 99)
    for value in ("bytes=100-101", "bytes=9-2", "bytes=0-1,4-5", "items=0-1", "bytes=-0"):
        assert _parse_range_header(value, 100) is None


