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
@pytest.mark.case_id("UT-BE-003")
def test_capacity_suggestion_exact_and_provider_inference() -> None:
    from services.model_capacity_suggestion_service import suggest_capacity

    catalog = {("openai", "gpt-functional"): _profile()}
    exact = suggest_capacity("gpt-functional", provider_hint="openai", model_type="llm", catalog=catalog)
    assert exact.match_kind.value == "catalog_exact"
    assert exact.suggested_provider == "openai"
    assert exact.suggestions and exact.suggestions.context_window_tokens == 128_000

    inferred = suggest_capacity(
        "gpt-functional",
        base_url="https://api.openai.example/v1",
        model_type="llm",
        catalog=catalog,
    )
    assert inferred.suggested_provider == "openai"


















