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
@pytest.mark.case_id("UT-BE-009")
def test_capacity_defaults_and_catalog_coverage_are_deterministic() -> None:
    from services.model_capacity_suggestion_service import normalize_model_name, pick_provider

    catalog = {("openai", "org/model-v1"): _profile()}
    assert normalize_model_name(" Org/Model-v1 ") == "orgmodelv1"
    assert pick_provider(None, None, "model-v1", catalog) == "openai"
    ambiguous = {("openai", "model-v1"): _profile(), ("other", "model-v1"): _profile("v2")}
    assert pick_provider(None, None, "model-v1", ambiguous) is None






