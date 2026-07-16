"""Tests for authoritative NL2AGENT card validation."""

import json

import pytest

from utils.nl2agent_card_validation import message_contains_valid_card


def _fence(language: str, payload: object) -> str:
    return f"```{language}\n{json.dumps(payload)}\n```"


@pytest.mark.parametrize(
    ("language", "card_type", "payload", "card_key"),
    [
        ("nl2agent-model-selection", "model_selection", {"agent_id": 202}, None),
        (
            "nl2agent-local-resources",
            "local_resources",
            {
                "agent_id": 202,
                "recommendation_batch_id": "local_1",
                "tools": [{"tool_id": 1, "name": "Reader"}],
                "skills": [],
            },
            "local_1",
        ),
        (
            "nl2agent-web-mcps",
            "web_mcp",
            {
                "recommendation_batch_id": "mcp_1",
                "items": [],
            },
            "mcp_1",
        ),
    ],
)
def test_message_contains_matching_schema_valid_card(
    language, card_type, payload, card_key
):
    assert message_contains_valid_card(
        f"Before\n{_fence(language, payload)}\nAfter",
        card_type,
        202,
        card_key,
    )


@pytest.mark.parametrize(
    ("content", "card_type", "card_key"),
    [
        ("No card here", "model_selection", None),
        ("```nl2agent-model-selection\n{not-json}\n```", "model_selection", None),
        (
            _fence("nl2agent-local-resources", {"recommendation_batch_id": "local_1"}),
            "local_resources",
            "local_1",
        ),
        (
            _fence("nl2agent-model-selection", {"agent_id": 999}),
            "model_selection",
            None,
        ),
        (
            _fence("nl2agent-web-mcps", {"recommendation_batch_id": "other", "items": []}),
            "web_mcp",
            "expected",
        ),
    ],
)
def test_message_rejects_missing_malformed_or_mismatched_card(
    content,
    card_type,
    card_key,
):
    assert not message_contains_valid_card(content, card_type, 202, card_key)


def test_message_rejects_duplicate_card_type():
    card = _fence("nl2agent-model-selection", {"agent_id": 202})
    assert not message_contains_valid_card(f"{card}\n{card}", "model_selection", 202, None)
