# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import patch

from management.services.agent.reasoning import (
    _resolve_model_reasoning_capability,
    reasoning_snapshot_from_model,
    snapshot_agent_reasoning_config,
)


def test_reasoning_snapshot_from_model_normalizes_model_rows():
    assert reasoning_snapshot_from_model(None) == {"enable_thinking": False}
    assert reasoning_snapshot_from_model({"extra_params": {"enable_thinking": False}}) == {
        "enable_thinking": False,
    }
    assert reasoning_snapshot_from_model(
        {
            "reasoning_capability": {
                "status": "supported",
                "levels": ["low", "high"],
            },
            "extra_params": {"reasoning_effort": "high"},
        }
    ) == {
        "enable_thinking": True,
        "reasoning_effort": "high",
    }
    assert reasoning_snapshot_from_model(
        {
            "reasoning_capability": {"status": "unsupported"},
            "extra_params": {"enable_thinking": True, "reasoning_effort": "high"},
        }
    ) == {
        "enable_thinking": False,
    }
    assert reasoning_snapshot_from_model({"extra_params": {"enable_thinking": True}}) == {
        "enable_thinking": False,
    }


def test_reasoning_snapshot_from_model_clamps_budget_to_declared_range():
    capability = {
        "status": "supported",
        "levels": [],
        "controls": [{"type": "budget_tokens", "min": 128, "max": 32768}],
    }

    low = reasoning_snapshot_from_model(
        {
            "reasoning_capability": capability,
            "extra_params": {
                "enable_thinking": True,
                "reasoning_budget_tokens": 64,
            },
        }
    )
    high = reasoning_snapshot_from_model(
        {
            "reasoning_capability": capability,
            "extra_params": {
                "enable_thinking": True,
                "reasoning_budget_tokens": 65536,
            },
        }
    )

    assert low["reasoning_budget_tokens"] == 128
    assert high["reasoning_budget_tokens"] == 32768


def test_reasoning_snapshot_from_model_ignores_invalid_budget_values():
    capability = {
        "status": "supported",
        "controls": [{"type": "budget_tokens", "min": 128, "max": 32768}],
    }

    for value in (True, 0, -1, "4096"):
        result = reasoning_snapshot_from_model(
            {
                "reasoning_capability": capability,
                "extra_params": {
                    "enable_thinking": True,
                    "reasoning_budget_tokens": value,
                },
            }
        )
        assert "reasoning_budget_tokens" not in result

    result = reasoning_snapshot_from_model(
        {
            "reasoning_capability": {"status": "supported", "controls": []},
            "extra_params": {"enable_thinking": True, "reasoning_budget_tokens": 4096},
        }
    )
    assert result == {"enable_thinking": False}
    assert "reasoning_budget_tokens" not in result


def test_reasoning_snapshot_from_model_handles_enabled_unknown_capability():
    with patch(
        "management.services.agent.reasoning.normalize_reasoning_params",
        return_value={"enable_thinking": True},
    ):
        result = reasoning_snapshot_from_model(
            {
                "reasoning_capability": {"status": "unsupported"},
                "extra_params": {"enable_thinking": True},
            }
        )

    assert result == {"enable_thinking": True}


def test_snapshot_agent_reasoning_config_adds_auto_for_effort_control():
    with patch(
        "management.services.agent.reasoning.get_model_by_model_id",
        return_value={
            "reasoning_capability": {
                "status": "supported",
                "controls": [{"type": "effort", "values": ["low", "high"]}],
            }
        },
    ):
        result = snapshot_agent_reasoning_config(
            model_ids=[1],
            requested_overrides={"1": {"extra_params": {"enable_thinking": True}}},
            existing_overrides=None,
            tenant_id="tenant-1",
        )

    assert result == {
        "1": {
            "extra_params": {
                "enable_thinking": True,
                "reasoning_effort": "auto",
            }
        }
    }


def test_resolve_model_reasoning_capability_handles_invalid_model_and_import_error():
    assert _resolve_model_reasoning_capability(None) is None

    with patch.dict("sys.modules", {"configs.model_catalog_loader": None}):
        assert _resolve_model_reasoning_capability({"model_name": "reasoner"}) is None


def test_snapshot_agent_reasoning_config_preserves_explicit_values_and_fills_missing():
    model_rows = {
        1: {
            "reasoning_capability": {"status": "supported", "levels": ["low", "high"]},
            "extra_params": {"enable_thinking": True, "reasoning_effort": "low"},
        },
        2: {"extra_params": {"enable_thinking": False}},
        3: {"extra_params": {"enable_thinking": True, "reasoning_effort": "invalid"}},
    }

    with patch(
        "management.services.agent.reasoning.get_model_by_model_id",
        side_effect=lambda model_id, tenant_id: model_rows.get(model_id),
    ):
        result = snapshot_agent_reasoning_config(
            model_ids=[1, 2, 3, 4],
            requested_overrides={
                "1": {"temperature": 0.2},
                "2": {"extra_params": {"enable_thinking": True}},
                "3": {"extra_params": {"enable_thinking": False, "reasoning_effort": "high"}},
            },
            existing_overrides=None,
            tenant_id="tenant-1",
        )

    assert result["1"]["extra_params"] == {
        "enable_thinking": True,
        "reasoning_effort": "low",
    }
    assert result["2"]["extra_params"] == {}
    assert result["3"]["extra_params"] == {}
    assert result["4"]["extra_params"] == {}


def test_snapshot_agent_reasoning_config_removes_effort_when_disabled():
    with patch(
        "management.services.agent.reasoning.get_model_by_model_id",
        return_value={
            "reasoning_capability": {"status": "supported", "levels": ["low", "high"]}
        },
    ):
        assert snapshot_agent_reasoning_config(
            model_ids=[1],
            requested_overrides={
                "1": {"extra_params": {"enable_thinking": False, "reasoning_effort": "high"}}
            },
            existing_overrides=None,
            tenant_id="tenant-1",
        ) == {"1": {"extra_params": {"enable_thinking": False}}}


def test_snapshot_agent_reasoning_config_preserves_effort_without_toggle():
    with patch(
        "management.services.agent.reasoning.get_model_by_model_id",
        return_value={
            "reasoning_capability": {"status": "supported", "levels": ["low", "high"]}
        },
    ):
        assert snapshot_agent_reasoning_config(
            model_ids=[1],
            requested_overrides={"1": {"extra_params": {"reasoning_effort": "high"}}},
            existing_overrides=None,
            tenant_id="tenant-1",
        ) == {"1": {"extra_params": {"enable_thinking": True, "reasoning_effort": "high"}}}


def test_snapshot_agent_reasoning_config_uses_existing_map_when_request_is_omitted():
    existing = {"7": {"extra_params": {"enable_thinking": False}}}
    assert snapshot_agent_reasoning_config(
        model_ids=None,
        requested_overrides=None,
        existing_overrides=existing,
        tenant_id="tenant-1",
    ) == existing
    with patch(
        "management.services.agent.reasoning.get_model_by_model_id",
        return_value=None,
    ):
        assert snapshot_agent_reasoning_config(
            model_ids=[7],
            requested_overrides=["invalid"],
            existing_overrides=None,
            tenant_id="tenant-1",
        ) == {"7": {"extra_params": {}}}


def test_saved_llm_outlets_do_not_generate_new_agent_owned_reasoning_defaults():
    from management.services.model.profiles import build_outlet_draft
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
    from nexent.core.model_service.registry import model_service_references
    from test.backend.services.test_model_profile_service import draft_request

    profile, _ = build_outlet_draft(draft_request(), "tenant")
    data = profile.model_dump()
    data["outlet_id"] = 1
    data["connection"]["credential_ref"]["model_id"] = 1
    row = encode_resolved_model_profile(profile.__class__.model_validate(data), registered_references=model_service_references())
    with patch("management.services.agent.reasoning.get_model_by_model_id",
               return_value=row), \
         patch("management.services.agent.reasoning._resolve_model_reasoning_capability") as resolve:
        assert snapshot_agent_reasoning_config([1], None, None, "tenant") is None
        explicit = {"1": {"extra_params": {"enable_thinking": False}}}
        assert snapshot_agent_reasoning_config([1], explicit, None, "tenant") == {"1": {"parameter_values": {"enable_thinking": False}}}
        resolve.assert_not_called()


def test_saving_profile_agent_converts_historical_entry_without_rewriting_input():
    from copy import deepcopy
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
    from nexent.core.model_service.registry import model_service_references
    from management.services.model.profiles import build_outlet_draft
    from test.backend.services.test_model_profile_service import draft_request
    profile, _ = build_outlet_draft(draft_request(), "tenant")
    data = profile.model_dump()
    data["outlet_id"] = 1
    data["connection"]["credential_ref"]["model_id"] = 1
    row = encode_resolved_model_profile(profile.__class__.model_validate(data), registered_references=model_service_references())
    historical = {"1": {"temperature": 0, "extra_params": {"enable_thinking": False}}}
    before = deepcopy(historical)
    with patch("management.services.agent.reasoning.get_model_by_model_id", return_value=row):
        saved = snapshot_agent_reasoning_config([1], historical, None, "tenant")
    assert saved == {"1": {"parameter_values": {"temperature": 0, "enable_thinking": False}}}
    assert historical == before



def test_runtime_backfill_does_not_rewrite_published_profile_agent_versions():
    historical = {"1": {"temperature": 0, "extra_params": {"enable_thinking": False}}}
    row = {"profile_schema_version": 1, "model_type": "llm"}
    with patch("management.services.agent.reasoning.get_model_by_model_id", return_value=row):
        result = snapshot_agent_reasoning_config([1], historical, historical, "tenant", normalize_profiles=False)
    assert result == historical
