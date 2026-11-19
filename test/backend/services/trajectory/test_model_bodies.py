# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Model display references must use the provider body, never internal DTOs."""

import pytest
from ops.services.trajectory.nodes import build_nodes

from test.backend.services.trajectory.test_nodes import request, span


@pytest.mark.parametrize("kind", ["LLM", "AGENT", "TOOL"])
def test_provider_body_projection_is_limited_to_models(kind):
    node = span(
        "node",
        kind=kind,
        **{
            "input.value": "wire request",
            "output.value": "internal DTO",
            "nexent.provider.response.format": "provider_json",
            "nexent.provider.response.value": "provider body",
        },
    )
    nodes, _, _ = build_nodes(request(node), conversation_id="123")
    assert nodes[0]["_bodies"]["output"] == (
        "provider body" if kind == "LLM" else "internal DTO"
    )
    assert nodes[0]["_bodies"]["input"] == "wire request"


def test_missing_provider_body_never_falls_back_to_internal_dto():
    nodes, _, _ = build_nodes(
        request(
            span(
                "model",
                kind="LLM",
                **{
                    "output.value": "internal DTO",
                    "nexent.provider.response.format": "provider_json",
                    "nexent.availability.output": "not_captured",
                },
            )
        ),
        conversation_id="123",
    )
    assert "output" not in nodes[0]["_bodies"]
    assert nodes[0]["_availability"]["output"] == "not_captured"


def test_historical_model_body_keeps_its_existing_source():
    nodes, _, _ = build_nodes(
        request(span("model", kind="LLM", **{"output.value": "old body"})),
        conversation_id="123",
    )
    assert nodes[0]["_bodies"]["output"] == "old body"
