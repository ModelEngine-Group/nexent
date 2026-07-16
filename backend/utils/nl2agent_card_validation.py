"""Server-side validation for persisted NL2AGENT card messages."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from jsonschema import Draft7Validator
from referencing import Registry, Resource


_CARD_OPENING_PATTERN = re.compile(
    r"```(nl2agent-[^\s`]+)[^\S\r\n]*\r?\n",
    re.IGNORECASE,
)
_LANGUAGE_TO_TYPE = {
    "nl2agent-requirements-summary": "requirements_summary",
    "nl2agent-model-selection": "model_selection",
    "nl2agent-local-resources": "local_resources",
    "nl2agent-web-mcp": "web_mcp",
    "nl2agent-web-mcps": "web_mcp",
    "nl2agent-web-skill": "web_skill",
    "nl2agent-web-skills": "web_skill",
    "nl2agent-agent-identity": "agent_identity",
    "nl2agent-finalize": "final_review",
}
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "nl2agent-card.schema.json"
)


@lru_cache(maxsize=1)
def _schema_validators() -> Dict[str, Draft7Validator]:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_id = str(schema["$id"])
    registry = Registry().with_resource(schema_id, Resource.from_contents(schema))
    return {
        card_type: Draft7Validator(
            {"$ref": f"{schema_id}#/$defs/{card_type}"},
            registry=registry,
        )
        for card_type in set(_LANGUAGE_TO_TYPE.values())
    }


def _matches_agent(payload: Dict[str, Any], draft_agent_id: int) -> bool:
    candidate_ids = []
    if "agent_id" in payload:
        candidate_ids.append(payload["agent_id"])
    if isinstance(payload.get("items"), list):
        candidate_ids.extend(
            item["agent_id"]
            for item in payload["items"]
            if isinstance(item, dict) and "agent_id" in item
        )
    return all(
        isinstance(candidate_id, int)
        and not isinstance(candidate_id, bool)
        and candidate_id == draft_agent_id
        for candidate_id in candidate_ids
    )


def _card_key(payload: Dict[str, Any]) -> Optional[str]:
    value = payload.get("recommendation_batch_id")
    return value if isinstance(value, str) and value.strip() else None


def message_contains_valid_card(
    content: str,
    card_type: str,
    draft_agent_id: int,
    card_key: Optional[str],
) -> bool:
    """Return whether a message contains exactly one matching valid card."""
    message = content or ""
    target_count = 0
    valid_count = 0
    position = 0
    while match := _CARD_OPENING_PATTERN.search(message, position):
        resolved_type = _LANGUAGE_TO_TYPE.get(match.group(1).lower())
        closing_index = message.find("```", match.end())
        position = len(message) if closing_index < 0 else closing_index + 3
        if resolved_type != card_type:
            continue
        target_count += 1
        if closing_index < 0:
            continue
        try:
            payload = json.loads(message[match.end():closing_index].strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            not isinstance(payload, dict)
            or not _schema_validators()[card_type].is_valid(payload)
            or not _matches_agent(payload, draft_agent_id)
            or _card_key(payload) != card_key
        ):
            continue
        valid_count += 1
    return target_count == 1 and valid_count == 1
