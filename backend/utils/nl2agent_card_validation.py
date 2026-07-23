"""Authoritative parsing and validation for NL2AGENT card messages."""

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, Optional

from pydantic import TypeAdapter, ValidationError

from consts.nl2agent_card import (
    CARD_MODELS,
    CARD_PAYLOAD_MODELS,
    Nl2AgentCardEnvelope,
)
from utils.nl2agent_observability import record_card_parse


logger = logging.getLogger(__name__)

_CARD_OPENING_PATTERN = re.compile(
    r"```(nl2agent-[^\s`]+)[^\S\r\n]*\r?\n",
    re.IGNORECASE,
)
_CARD_CLOSING_PATTERN = re.compile(r"^```[ \t]*\r?$", re.MULTILINE)
_CARD_MARKER_PATTERN = re.compile(r"```nl2agent-", re.IGNORECASE)
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
_TRUSTED_CARD_TYPES = {"local_resources", "web_mcp", "web_skill"}
TrustedSearchBatchProvider = Callable[[], Dict[str, Dict[str, Any]]]


class Nl2AgentCardValidationError(ValueError):
    """Raised when a complete assistant answer violates the card contract."""

    def __init__(self, repair_instruction: str):
        super().__init__(repair_instruction)
        self.repair_instruction = repair_instruction


@dataclass(frozen=True)
class ParsedNl2AgentFinalAnswer:
    """Validated metadata and user-visible text extracted from one final answer."""

    envelope: Nl2AgentCardEnvelope
    display_text: str


@lru_cache(maxsize=1)
def _payload_adapters() -> Dict[str, TypeAdapter]:
    return {
        card_type: TypeAdapter(payload_model)
        for card_type, payload_model in CARD_PAYLOAD_MODELS.items()
    }


def _payload_dict(payload: Any) -> Dict[str, Any]:
    return payload.model_dump(mode="json", exclude_none=True)


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


def _card_key(card_type: str, payload: Dict[str, Any]) -> str:
    if card_type in _TRUSTED_CARD_TYPES:
        value = payload.get("recommendation_batch_id")
        return value if isinstance(value, str) else ""
    return card_type


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


def _strip_card_fences(message: str, spans: list[tuple[int, int]]) -> str:
    visible_parts = []
    position = 0
    for start, end in spans:
        visible_parts.append(message[position:start])
        position = end
    visible_parts.append(message[position:])
    display_text = "".join(visible_parts).strip()
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", display_text)


def _parse_nl2agent_final_answer(
    content: Any,
    *,
    draft_agent_id: int,
    workflow_revision: int,
    trusted_search_batch_provider: Optional[TrustedSearchBatchProvider] = None,
) -> ParsedNl2AgentFinalAnswer:
    """Parse one complete answer into a validated envelope and display text."""
    message = "" if content is None else str(content)
    position = 0
    spans: list[tuple[int, int]] = []
    cards = []
    seen_types = set()
    trusted_batches: Optional[Dict[str, Dict[str, Any]]] = None

    while match := _CARD_OPENING_PATTERN.search(message, position):
        language = match.group(1).lower()
        card_type = _LANGUAGE_TO_TYPE.get(language)
        closing_match = _CARD_CLOSING_PATTERN.search(message, match.end())
        if closing_match is None:
            raise Nl2AgentCardValidationError(
                f"Close the `{language}` fence and copy the complete card JSON."
            )
        position = closing_match.end()
        spans.append((match.start(), closing_match.end()))
        if card_type is None:
            raise Nl2AgentCardValidationError(
                f"Use a supported NL2AGENT card fence instead of `{language}`."
            )
        try:
            raw_payload = json.loads(
                message[match.end() : closing_match.start()].strip()
            )
        except (json.JSONDecodeError, TypeError) as exc:
            raise Nl2AgentCardValidationError(
                f"Copy valid JSON into the `{language}` card without rewriting it."
            ) from exc
        try:
            payload_model = _payload_adapters()[card_type].validate_python(
                raw_payload, strict=True
            )
        except ValidationError as exc:
            raise Nl2AgentCardValidationError(
                f"The `{language}` payload does not match the card contract. "
                "Copy the complete tool Observation unchanged; arrays such as `skills` must stay flat."
            ) from exc
        payload = _payload_dict(payload_model)
        if not _matches_agent(payload, draft_agent_id):
            raise Nl2AgentCardValidationError(
                f"Use the Current Session draft agent ID in the `{language}` card."
            )
        card_key = _card_key(card_type, payload)
        if (
            card_type in _TRUSTED_CARD_TYPES
            and trusted_search_batch_provider is not None
        ):
            if trusted_batches is None:
                try:
                    trusted_batches = trusted_search_batch_provider()
                except Exception as exc:
                    logger.exception(
                        "Failed to load trusted NL2AGENT search batches: draft_agent_id=%s",
                        draft_agent_id,
                    )
                    raise Nl2AgentCardValidationError(
                        "The trusted search result could not be verified. "
                        "Do not render a recommendation card; rerun the required search action."
                    ) from exc
            if not _matches_trusted_search_batch(
                card_type,
                payload,
                trusted_batches.get(card_key) if card_key else None,
            ):
                raise Nl2AgentCardValidationError(
                    f"The `{language}` card does not match its trusted search result. "
                    "Rerun the required search action and copy its complete Observation unchanged "
                    "without adding, removing, filtering, or replacing resources."
                )
        if card_type in seen_types:
            raise Nl2AgentCardValidationError(
                f"Render exactly one `{language}` card in the final answer."
            )
        seen_types.add(card_type)
        try:
            cards.append(
                CARD_MODELS[card_type].model_validate(
                    {
                        "card_type": card_type,
                        "card_key": card_key,
                        "payload": payload_model,
                    }
                )
            )
        except ValidationError as exc:
            raise Nl2AgentCardValidationError(
                f"The `{language}` payload does not match the card contract."
            ) from exc

    if len(_CARD_MARKER_PATTERN.findall(message)) != len(spans):
        raise Nl2AgentCardValidationError(
            "Use a complete NL2AGENT card opening fence followed by a newline and valid JSON."
        )
    try:
        envelope = Nl2AgentCardEnvelope(
            schema_version=1,
            draft_agent_id=draft_agent_id,
            workflow_revision=workflow_revision,
            cards=cards,
        )
    except ValidationError as exc:
        raise Nl2AgentCardValidationError(
            "The NL2AGENT card envelope does not match the current Session."
        ) from exc
    return ParsedNl2AgentFinalAnswer(
        envelope=envelope,
        display_text=_strip_card_fences(message, spans),
    )


def parse_nl2agent_final_answer(
    content: Any,
    *,
    draft_agent_id: int,
    workflow_revision: int,
    trusted_search_batch_provider: Optional[TrustedSearchBatchProvider] = None,
) -> ParsedNl2AgentFinalAnswer:
    """Parse one complete answer and record only its validation outcome."""
    try:
        parsed = _parse_nl2agent_final_answer(
            content,
            draft_agent_id=draft_agent_id,
            workflow_revision=workflow_revision,
            trusted_search_batch_provider=trusted_search_batch_provider,
        )
    except Nl2AgentCardValidationError:
        record_card_parse("failure")
        raise
    record_card_parse("success")
    return parsed
