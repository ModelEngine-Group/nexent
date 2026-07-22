"""Cross-runtime checks for the canonical NL2AGENT card contract."""

import json
import re
from pathlib import Path

from jsonschema import Draft7Validator, RefResolver
import yaml

from consts.model import (
    Nl2AgentFinalizeRequest,
    Nl2AgentRecommendationBatchRequest,
    Nl2AgentRequirementsSummaryRequest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (PROJECT_ROOT / "contracts" / "nl2agent-card.schema.json").read_text(
        encoding="utf-8"
    )
)
OPENAPI = json.loads(
    (PROJECT_ROOT / "contracts" / "nl2agent-openapi.json").read_text(
        encoding="utf-8"
    )
)


def _validator(card_type: str) -> Draft7Validator:
    return Draft7Validator(
        SCHEMA["$defs"][card_type],
        resolver=RefResolver.from_schema(SCHEMA),
    )


def test_canonical_schema_is_valid() -> None:
    Draft7Validator.check_schema(SCHEMA)


def test_every_nl2agent_endpoint_declares_a_typed_success_response() -> None:
    for path, path_item in OPENAPI["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "delete", "patch"}:
                continue
            schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            non_null_schema = next(
                (item for item in schema.get("anyOf", []) if "$ref" in item),
                schema,
            )
            assert non_null_schema["$ref"].startswith("#/components/schemas/Nl2Agent"), (
                path,
                method,
                schema,
            )


def test_all_seven_nl2agent_card_payloads_validate() -> None:
    payloads = {
        "requirements_summary": {
            "agent_id": 54,
            "goal": "Summarize documents",
            "audience_or_scenario": "Office users",
            "primary_input": "DOCX files",
            "expected_output": "Presentation",
            "key_constraints": "Preserve source facts",
        },
        "model_selection": {"agent_id": 54},
        "local_resources": {
            "agent_id": 54,
            "recommendation_batch_id": "local_1",
            "tools": [{"tool_id": 1, "name": "Document reader"}],
            "skills": [{"skill_id": 2, "name": "Presentation writer"}],
        },
        "web_mcp": {
            "agent_id": 54,
            "recommendation_batch_id": "online_mcp",
            "items": [
                {
                    "recommendation_id": "registry:document",
                    "name": "Document MCP",
                    "install_options": [
                        {
                            "option_id": "remote",
                            "type": "remote",
                            "label": "Remote endpoint",
                            "requires_configuration": False,
                            "fields": [],
                            "supported": True,
                            "status": "ready",
                        },
                    ],
                }
            ],
        },
        "web_skill": {
            "agent_id": 54,
            "recommendation_batch_id": "online_skill",
            "items": [
                {
                    "skill_id": 3,
                    "skill_name": "slides",
                    "name": "Slides",
                }
            ],
        },
        "agent_identity": {"agent_id": 54, "display_name": "Document Assistant"},
        "final_review": {
            "agent_id": 54,
            "business_description": "Build presentations from documents.",
            "duty_prompt": "Read source documents and create slides.",
            "greeting_message": "Upload a document to begin.",
        },
    }

    for card_type, payload in payloads.items():
        assert list(_validator(card_type).iter_errors(payload)) == []


def test_contract_rejects_unstable_resource_payloads() -> None:
    invalid_local = {
        "recommendation_batch_id": "local_1",
        "tools": [{"name": "Missing stable ID"}],
        "skills": [],
    }
    invalid_mcp = {
        "recommendation_batch_id": "online_1",
        "items": [
            {
                "recommendation_id": "registry:broken",
                "name": "Broken",
                "install_options": [{"option_id": "remote"}],
            }
        ],
    }

    assert list(_validator("local_resources").iter_errors(invalid_local))
    assert list(_validator("web_mcp").iter_errors(invalid_mcp))


def test_final_review_verification_config_matches_runtime_contract() -> None:
    valid_payload = {
        "business_description": "Build an agent.",
        "duty_prompt": "Help the user.",
        "greeting_message": "Hello.",
        "verification_config": {
            "enabled": True,
            "strictness": "strict",
            "max_final_rounds": 3,
            "fail_policy": "warn",
            "critical_events": ["tool_result", "final_answer"],
        },
    }
    invalid_payload = {
        **valid_payload,
        "verification_config": {"enabled": False, "mode": "basic"},
    }

    assert list(_validator("final_review").iter_errors(valid_payload)) == []
    assert list(_validator("final_review").iter_errors(invalid_payload))


def test_card_limits_match_http_request_boundaries() -> None:
    requirements = {
        "goal": "x" * 501,
        "audience_or_scenario": "Office users",
        "primary_input": "DOCX files",
        "expected_output": "Presentation",
        "key_constraints": "Preserve facts",
    }
    local_resources = {
        "recommendation_batch_id": "x" * 129,
        "tools": [],
        "skills": [],
    }
    final_review = {
        "business_description": "Build an agent.",
        "duty_prompt": "Help the user.",
        "greeting_message": "Hello.",
        "max_steps": 31,
        "example_questions": [str(index) for index in range(7)],
    }

    assert list(_validator("requirements_summary").iter_errors(requirements))
    assert list(_validator("local_resources").iter_errors(local_resources))
    assert list(_validator("final_review").iter_errors(final_review))


def _non_null_schema(schema: dict) -> dict:
    return next(
        (item for item in schema.get("anyOf", []) if item.get("type") != "null"),
        schema,
    )


def test_card_constraints_equal_http_model_constraints() -> None:
    requirements_http = Nl2AgentRequirementsSummaryRequest.model_json_schema()
    batch_http = Nl2AgentRecommendationBatchRequest.model_json_schema()
    finalize_http = Nl2AgentFinalizeRequest.model_json_schema()

    for field_name in (
        "goal",
        "audience_or_scenario",
        "primary_input",
        "expected_output",
        "key_constraints",
    ):
        card_field = SCHEMA["$defs"]["requirements_summary"]["properties"][
            field_name
        ]
        http_field = requirements_http["properties"][field_name]
        assert {
            "minLength": card_field["minLength"],
            "maxLength": card_field["maxLength"],
        } == {
            "minLength": http_field["minLength"],
            "maxLength": http_field["maxLength"],
        }

    card_batch = SCHEMA["$defs"]["batchIdentifier"]
    http_batch = batch_http["properties"]["recommendation_batch_id"]
    assert {
        "minLength": card_batch["minLength"],
        "maxLength": card_batch["maxLength"],
    } == {
        "minLength": http_batch["minLength"],
        "maxLength": http_batch["maxLength"],
    }

    for field_name, constraints in {
        "description": ("maxLength",),
        "business_description": ("minLength", "maxLength"),
        "duty_prompt": ("minLength", "maxLength"),
        "constraint_prompt": ("maxLength",),
        "few_shots_prompt": ("maxLength",),
        "greeting_message": ("minLength", "maxLength"),
        "example_questions": ("maxItems",),
        "max_steps": ("minimum", "maximum"),
        "requested_output_tokens": ("minimum",),
    }.items():
        card_field = SCHEMA["$defs"]["final_review"]["properties"][field_name]
        http_field = _non_null_schema(finalize_http["properties"][field_name])
        assert {key: card_field[key] for key in constraints} == {
            key: http_field[key] for key in constraints
        }

    assert requirements_http["additionalProperties"] is False
    assert batch_http["additionalProperties"] is False
    assert finalize_http["additionalProperties"] is False


def test_bilingual_prompt_card_examples_follow_canonical_contract() -> None:
    language_to_type = {
        "nl2agent-requirements-summary": "requirements_summary",
        "nl2agent-model-selection": "model_selection",
        "nl2agent-local-resources": "local_resources",
        "nl2agent-agent-identity": "agent_identity",
        "nl2agent-finalize": "final_review",
    }
    for language in ("en", "zh"):
        prompt_path = (
            PROJECT_ROOT
            / "backend"
            / "prompts"
            / f"nl2agent_system_prompt_{language}.yaml"
        )
        prompt = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))["system_prompt"]
        assert "`revision_routing`" in prompt
        assert "`allowed_card_types`" in prompt
        examples = re.findall(r"```(nl2agent-[^\n]+)\n(.+?)\n```", prompt, re.DOTALL)
        assert examples
        for card_language, raw_payload in examples:
            card_type = language_to_type[card_language]
            _validator(card_type).validate(json.loads(raw_payload))
