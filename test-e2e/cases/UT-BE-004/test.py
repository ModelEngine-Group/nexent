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
@pytest.mark.case_id("UT-BE-004")
def test_capacity_suggestion_boundaries_do_not_guess() -> None:
    from services.model_capacity_suggestion_service import suggest_capacity

    with pytest.raises(ValueError, match="required"):
        suggest_capacity("", catalog={})
    with pytest.raises(ValueError, match="too long"):
        suggest_capacity("x" * 513, catalog={})
    unsupported = suggest_capacity("voice", provider_hint="openai", model_type="tts", catalog={})
    assert unsupported.match_kind.value == "none"
    disabled = suggest_capacity("gpt", provider_hint="openai", catalog={}, enabled=False)
    assert disabled.suggestions is None and disabled.match_kind.value == "none"
















