"""Tests for authoritative NL2AGENT card validation."""

import json

import pytest

from utils.nl2agent_card_validation import (
    Nl2AgentCardValidationError,
    parse_nl2agent_final_answer,
)


def _fence(language: str, payload: object) -> str:
    return f"```{language}\n{json.dumps(payload)}\n```"


def message_contains_valid_card(
    content: str,
    card_type: str,
    draft_agent_id: int,
    card_key: str | None,
) -> bool:
    try:
        parsed = parse_nl2agent_final_answer(
            content,
            draft_agent_id=draft_agent_id,
            workflow_revision=0,
        )
    except Nl2AgentCardValidationError:
        return False
    expected_key = card_key or card_type
    return sum(
        card.card_type == card_type and card.card_key == expected_key
        for card in parsed.envelope.cards
    ) == 1


def validate_nl2agent_final_answer(
    content,
    draft_agent_id,
    trusted_search_batch_provider=None,
):
    try:
        parse_nl2agent_final_answer(
            content,
            draft_agent_id=draft_agent_id,
            workflow_revision=0,
            trusted_search_batch_provider=trusted_search_batch_provider,
        )
    except Nl2AgentCardValidationError as exc:
        return exc.repair_instruction
    return None


@pytest.mark.parametrize(
    ("language", "card_type", "payload", "card_key"),
    [
        (
            "nl2agent-requirements-summary",
            "requirements_summary",
            {
                "agent_id": 202,
                "goal": "Build presentations",
                "audience_or_scenario": "Office users",
                "primary_input": "DOCX files",
                "expected_output": "PPT files",
                "key_constraints": "Preserve source facts",
            },
            None,
        ),
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
            _fence(
                "nl2agent-web-mcps", {"recommendation_batch_id": "other", "items": []}
            ),
            "web_mcp",
            "expected",
        ),
        (
            _fence(
                "nl2agent-requirements-summary",
                {
                    "agent_id": 202,
                    "goal": "Build presentations",
                    "audience_or_scenario": "Office users",
                    "primary_input": "DOCX files",
                    "expected_output": "PPT files",
                    "key_constraints": "Preserve source facts",
                },
            ),
            "requirements_summary",
            "a" * 64,
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
    assert not message_contains_valid_card(
        f"{card}\n{card}", "model_selection", 202, None
    )


def test_message_accepts_inline_fence_text_inside_json_string():
    payload = {
        "agent_id": 202,
        "recommendation_batch_id": "local_1",
        "tools": [{"tool_id": 1, "name": "Untrusted ``` marker"}],
        "skills": [],
    }

    assert message_contains_valid_card(
        _fence("nl2agent-local-resources", payload),
        "local_resources",
        202,
        "local_1",
    )


def test_message_accepts_crlf_fences():
    content = '```nl2agent-model-selection\r\n{"agent_id": 202}\r\n```\r\n'

    assert message_contains_valid_card(content, "model_selection", 202, None)


def test_message_rejects_inline_fence_without_line_anchored_closing_fence():
    content = (
        '```nl2agent-model-selection\n{"agent_id": 202, '
        '"description": "inline ``` only"}'
    )

    assert not message_contains_valid_card(content, "model_selection", 202, None)


def test_final_answer_validator_rejects_nested_local_skill_payload():
    content = """```nl2agent-local-resources
{"agent_id":77,"recommendation_batch_id":"local_1","tools":[],"skills":[{"name":"create-docx","skills":[{"skill_id":3,"name":"create-docx"}]}]}
```"""

    error = validate_nl2agent_final_answer(content, draft_agent_id=77)

    assert error is not None
    assert "flat" in error


def test_final_answer_validator_accepts_complete_local_card():
    payload = {
        "agent_id": 77,
        "recommendation_batch_id": "local_1",
        "tools": [],
        "skills": [
            {
                "skill_id": 3,
                "name": "create-docx",
                "description": "Create documents",
                "score": 0.87,
                "reason": "Matched",
            }
        ],
    }

    assert (
        validate_nl2agent_final_answer(_fence("nl2agent-local-resources", payload), 77)
        is None
    )


def test_final_answer_validator_rejects_local_card_filtered_from_trusted_batch():
    payload = {
        "agent_id": 80,
        "recommendation_batch_id": "local_3e22328ccb2f4a3c48370961",
        "tools": [],
        "skills": [{"skill_id": 3, "name": "create-docx"}],
    }
    trusted = {
        "local_3e22328ccb2f4a3c48370961": {
            "resource_type": "local",
            "tool_ids": [28, 52],
            "skill_ids": [3, 11, 14],
            "item_keys": [],
        }
    }

    error = validate_nl2agent_final_answer(
        _fence("nl2agent-local-resources", payload),
        80,
        trusted_search_batch_provider=lambda: trusted,
    )

    assert error is not None
    assert "does not match its trusted search result" in error
    assert "without adding, removing, filtering, or replacing resources" in error


def test_final_answer_validator_accepts_exact_trusted_local_card():
    payload = {
        "agent_id": 80,
        "recommendation_batch_id": "local_exact",
        "tools": [
            {"tool_id": 28, "name": "tool-28"},
            {"tool_id": 52, "name": "tool-52"},
        ],
        "skills": [
            {"skill_id": 3, "name": "create-docx"},
            {"skill_id": 11, "name": "search-datamate"},
            {"skill_id": 14, "name": "search-knowledge-base"},
        ],
    }
    trusted = {
        "local_exact": {
            "resource_type": "local",
            "tool_ids": [28, 52],
            "skill_ids": [3, 11, 14],
            "item_keys": [],
        }
    }

    assert (
        validate_nl2agent_final_answer(
            _fence("nl2agent-local-resources", payload),
            80,
            trusted_search_batch_provider=lambda: trusted,
        )
        is None
    )


def test_final_answer_validator_accepts_name_keyed_web_skill_card():
    payload = {
        "agent_id": 80,
        "recommendation_batch_id": "skill_names",
        "items": [
            {
                "skill_name": "document-builder",
                "name": "Document Builder",
                "status": "installable",
            }
        ],
    }
    trusted = {
        "skill_names": {
            "resource_type": "skill",
            "tool_ids": [],
            "skill_ids": [],
            "item_keys": ["skill-name:document-builder"],
        }
    }

    assert (
        validate_nl2agent_final_answer(
            _fence("nl2agent-web-skills", payload),
            80,
            trusted_search_batch_provider=lambda: trusted,
        )
        is None
    )


@pytest.mark.parametrize(
    ("language", "payload", "trusted"),
    [
        (
            "nl2agent-web-mcps",
            {
                "agent_id": 80,
                "recommendation_batch_id": "mcp_batch",
                "items": [
                    {
                        "agent_id": 80,
                        "recommendation_id": "registry:github",
                        "name": "GitHub",
                        "install_options": [
                            {
                                "option_id": "remote",
                                "type": "remote",
                                "label": "Remote",
                                "requires_configuration": False,
                                "fields": [],
                                "supported": True,
                                "status": "ready",
                            }
                        ],
                    }
                ],
            },
            {
                "mcp_batch": {
                    "resource_type": "mcp",
                    "tool_ids": [],
                    "skill_ids": [],
                    "item_keys": ["registry:other"],
                }
            },
        ),
        (
            "nl2agent-web-skills",
            {
                "agent_id": 80,
                "recommendation_batch_id": "skill_batch",
                "items": [{"skill_id": 3, "name": "create-docx"}],
            },
            {
                "skill_batch": {
                    "resource_type": "skill",
                    "tool_ids": [],
                    "skill_ids": [],
                    "item_keys": ["skill:14"],
                }
            },
        ),
    ],
)
def test_final_answer_validator_rejects_modified_online_card(
    language,
    payload,
    trusted,
):
    error = validate_nl2agent_final_answer(
        _fence(language, payload),
        80,
        trusted_search_batch_provider=lambda: trusted,
    )

    assert error is not None
    assert "does not match its trusted search result" in error


def test_final_answer_validator_fails_closed_when_trusted_state_is_unavailable():
    payload = {
        "agent_id": 80,
        "recommendation_batch_id": "local_1",
        "tools": [],
        "skills": [],
    }

    def fail_loading():
        raise RuntimeError("database unavailable")

    error = validate_nl2agent_final_answer(
        _fence("nl2agent-local-resources", payload),
        80,
        trusted_search_batch_provider=fail_loading,
    )

    assert error is not None
    assert "could not be verified" in error


def test_final_answer_validator_rejects_malformed_opening_fence():
    content = '```nl2agent-local-resources {"agent_id":77}```'

    assert validate_nl2agent_final_answer(content, 77) is not None


def test_complete_answer_parser_builds_envelope_and_strips_card_fences():
    content = (
        "The configuration is ready.\n\n"
        + _fence("nl2agent-model-selection", {"agent_id": 202})
        + "\n\nChoose the models below."
    )

    parsed = parse_nl2agent_final_answer(
        content,
        draft_agent_id=202,
        workflow_revision=18,
    )

    assert parsed.display_text == (
        "The configuration is ready.\n\nChoose the models below."
    )
    assert parsed.envelope.model_dump(mode="json", exclude_none=True) == {
        "schema_version": 1,
        "draft_agent_id": 202,
        "workflow_revision": 18,
        "cards": [
            {
                "card_type": "model_selection",
                "card_key": "model_selection",
                "payload": {"agent_id": 202},
            }
        ],
    }


def test_complete_answer_parser_uses_recommendation_batch_as_card_key():
    parsed = parse_nl2agent_final_answer(
        _fence(
            "nl2agent-local-resources",
            {
                "agent_id": 202,
                "recommendation_batch_id": "local_18",
                "tools": [],
                "skills": [],
            },
        ),
        draft_agent_id=202,
        workflow_revision=18,
    )

    assert parsed.envelope.cards[0].card_key == "local_18"


def test_complete_answer_parser_rejects_more_than_one_card_of_same_type():
    card = _fence("nl2agent-model-selection", {"agent_id": 202})

    with pytest.raises(Nl2AgentCardValidationError):
        parse_nl2agent_final_answer(
            f"{card}\n{card}",
            draft_agent_id=202,
            workflow_revision=18,
        )
