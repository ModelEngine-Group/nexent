"""D1 contracts for tags, HITL, model catalog, logging and sandbox cleanup."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError


STAGE = pytest.mark.stage("D1")






@STAGE
@pytest.mark.case_id("UT-BE-028")
def test_model_catalog_custom_json_and_http_credentials_follow_the_v260_contract() -> None:
    from apps.model_managment_app import _sanitize_model_credentials
    from consts.model import filter_extra_params
    from configs.model_catalog_loader import _normalize_catalog

    catalog = _normalize_catalog({
        "version": "test-1",
        "providers": {
            "volcengine": {
                "display_name": "Volcengine",
                "base_url": "https://example.invalid/v1",
                "models": {
                    "reasoning-model": {
                        "model_type": "llm",
                        "context_window_tokens": 128000,
                        "max_output_tokens": 8192,
                        "timeout_seconds": 60,
                    },
                    "missing-type": {"max_output_tokens": 1},
                },
            }
        },
    })
    provider = catalog["providers"]["volcengine"]
    assert set(provider["models"]) == {"reasoning-model"}
    profile = provider["models"]["reasoning-model"]
    assert profile.context_window_tokens == 128000
    assert profile.max_output_tokens == 8192
    assert profile.base_url == "https://example.invalid/v1"

    # Custom provider parameters preserve the full JSON value space, including
    # nested objects, arrays, booleans and null. Python-only/non-finite values
    # are rejected before they can reach JSONB or a provider request.
    filtered = filter_extra_params("llm", {
        "__custom__": {
            "routing": {"region": "cn-beijing", "fallbacks": ["a", "b"]},
            "flags": [True, False, None, 3],
            "invalid_nan": float("nan"),
            "invalid_python": {1, 2},
        }
    })
    assert filtered == {
        "__custom__": {
            "routing": {"region": "cn-beijing", "fallbacks": ["a", "b"]},
            "flags": [True, False, None, 3],
        }
    }

    # Credentials are removed recursively at the HTTP response boundary while
    # internal model records remain free to retain their configured key.
    payload = {
        "model": {"display_name": "glm-5.2", "api_key": "sk-never-return"},
        "items": [{"api_key": "nested-secret", "status": "available"}],
    }
    sanitized = _sanitize_model_credentials(payload)
    assert sanitized == {
        "model": {"display_name": "glm-5.2"},
        "items": [{"status": "available"}],
    }
    assert payload["model"]["api_key"] == "sk-never-return"




