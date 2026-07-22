"""Server-side validation for persisted NL2AGENT card messages."""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from jsonschema import Draft7Validator
from referencing import Registry, Resource


logger = logging.getLogger(__name__)

_CARD_OPENING_PATTERN = re.compile(
    r"```(nl2agent-[^\s`]+)[^\S\r\n]*\r?\n",
    re.IGNORECASE,
)
_CARD_CLOSING_PATTERN = re.compile(r"^```[ \t]*\r?$", re.MULTILINE)
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
_TRUSTED_CARD_TYPES = {"local_resources", "web_mcp", "web_skill"}
TrustedSearchBatchProvider = Callable[[], Dict[str, Dict[str, Any]]]


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


def _online_card_items(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    items = payload.get("items")
    return items if isinstance(items, list) else [payload]


def _web_skill_item_key(item: Dict[str, Any]) -> str:
    skill_id = item.get("skill_id")
    if isinstance(skill_id, int) and not isinstance(skill_id, bool):
        return f"skill:{skill_id}"
    return f"skill-name:{str(item.get('skill_name') or '').strip().casefold()}"


def _matches_trusted_search_batch(
    card_type: str,
    payload: Dict[str, Any],
    trusted_batch: Optional[Dict[str, Any]],
) -> bool:
    """Compare action-authorizing card fields with one immutable search proof."""
    if not isinstance(trusted_batch, dict):
        return False
    if card_type == "local_resources":
        return (
            trusted_batch.get("resource_type") == "local"
            and trusted_batch.get("tool_ids")
            == sorted({int(item["tool_id"]) for item in payload["tools"]})
            and trusted_batch.get("skill_ids")
            == sorted({int(item["skill_id"]) for item in payload["skills"]})
        )
    items = _online_card_items(payload)
    if card_type == "web_mcp":
        resource_type = "mcp"
        item_keys = sorted({str(item["recommendation_id"]).strip() for item in items})
    else:
        resource_type = "skill"
        item_keys = sorted({_web_skill_item_key(item) for item in items})
    return (
        trusted_batch.get("resource_type") == resource_type
        and trusted_batch.get("item_keys") == item_keys
    )


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
        closing_match = _CARD_CLOSING_PATTERN.search(message, match.end())
        closing_index = closing_match.start() if closing_match else -1
        position = len(message) if closing_match is None else closing_match.end()
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


def validate_nl2agent_final_answer(
    content: Any,
    draft_agent_id: int,
    trusted_search_batch_provider: Optional[TrustedSearchBatchProvider] = None,
) -> Optional[str]:
    """Return a repair instruction when an NL2AGENT card block is invalid."""
    message = "" if content is None else str(content)
    position = 0
    parsed_blocks = 0
    seen_types = set()
    trusted_batches: Optional[Dict[str, Dict[str, Any]]] = None
    while match := _CARD_OPENING_PATTERN.search(message, position):
        parsed_blocks += 1
        language = match.group(1).lower()
        card_type = _LANGUAGE_TO_TYPE.get(language)
        closing_match = _CARD_CLOSING_PATTERN.search(message, match.end())
        if closing_match is None:
            return f"Close the `{language}` fence and copy the complete card JSON."
        position = closing_match.end()
        if card_type is None:
            return f"Use a supported NL2AGENT card fence instead of `{language}`."
        try:
            payload = json.loads(message[match.end():closing_match.start()].strip())
        except (json.JSONDecodeError, TypeError):
            return f"Copy valid JSON into the `{language}` card without rewriting it."
        if not isinstance(payload, dict) or not _schema_validators()[card_type].is_valid(payload):
            return (
                f"The `{language}` payload does not match the card contract. "
                "Copy the complete tool Observation unchanged; arrays such as `skills` must stay flat."
            )
        if not _matches_agent(payload, draft_agent_id):
            return f"Use the Current Session draft agent ID in the `{language}` card."
        if card_type in _TRUSTED_CARD_TYPES and trusted_search_batch_provider is not None:
            if trusted_batches is None:
                try:
                    trusted_batches = trusted_search_batch_provider()
                except Exception:
                    logger.exception(
                        "Failed to load trusted NL2AGENT search batches: draft_agent_id=%s",
                        draft_agent_id,
                    )
                    return (
                        "The trusted search result could not be verified. "
                        "Do not render a recommendation card; rerun the required search action."
                    )
            card_key = _card_key(payload)
            if not _matches_trusted_search_batch(
                card_type,
                payload,
                trusted_batches.get(card_key) if card_key else None,
            ):
                return (
                    f"The `{language}` card does not match its trusted search result. "
                    "Rerun the required search action and copy its complete Observation unchanged "
                    "without adding, removing, filtering, or replacing resources."
                )
        if card_type in seen_types:
            return f"Render exactly one `{language}` card in the final answer."
        seen_types.add(card_type)
    marker_count = len(re.findall(r"```nl2agent-", message, re.IGNORECASE))
    if marker_count != parsed_blocks:
        return "Use a complete NL2AGENT card opening fence followed by a newline and valid JSON."
    return None
