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
@pytest.mark.case_id("UT-BE-010")
def test_content_disposition_sanitizes_header_injection_and_unicode() -> None:
    from apps.file_management_app import build_content_disposition_header

    header = build_content_disposition_header(' report\\"\r\nX-Evil: yes.txt ')
    assert header.startswith("attachment;")
    assert "\r" not in header and "\n" not in header and "\\" not in header
    unicode_header = build_content_disposition_header("测试 文档.pdf", inline=True)
    assert unicode_header.startswith("inline;")
    assert "filename*=UTF-8''" in unicode_header




