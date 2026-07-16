"""Cross-runtime checks for the canonical NL2AGENT card contract."""

import json
import re
from pathlib import Path

from jsonschema import Draft7Validator, RefResolver
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (PROJECT_ROOT / "contracts" / "nl2agent-card.schema.json").read_text(
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
                        {"option_id": "remote", "type": "remote"}
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


def test_bilingual_prompt_card_examples_follow_canonical_contract() -> None:
    language_to_type = {
        "nl2agent-requirements-summary": "requirements_summary",
        "nl2agent-model-selection": "model_selection",
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
        examples = re.findall(r"```(nl2agent-[^\n]+)\n(.+?)\n```", prompt, re.DOTALL)
        assert examples
        for card_language, raw_payload in examples:
            card_type = language_to_type[card_language]
            _validator(card_type).validate(json.loads(raw_payload))
