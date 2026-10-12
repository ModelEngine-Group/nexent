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
@pytest.mark.case_id("UT-BE-008")
def test_quota_units_are_exact_and_reject_negative_values() -> None:
    from services.quota_service import _gb_to_bytes, _mb_to_bytes

    assert _gb_to_bytes(1) == 1024**3
    assert _mb_to_bytes(1) == 1024**2
    assert _gb_to_bytes(0) == 0
    with pytest.raises(ValueError):
        _gb_to_bytes(-1)
    with pytest.raises(ValueError):
        _mb_to_bytes(-1)








