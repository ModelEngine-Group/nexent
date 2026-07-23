"""Atomic persistence boundary for structured NL2AGENT assistant messages."""

import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, Optional

from agents.nl2agent_workflow import (
    WORKFLOW_SCHEMA_VERSION,
    Nl2AgentWorkflowState,
    RequirementsReview,
    evaluate_workflow,
    state_to_dict,
)
from consts.exceptions import (
    Nl2AgentValidationError,
    Nl2AgentWorkflowConflictError,
)
from database.client import get_db_session
from database.conversation_db import create_nl2agent_assistant_message
from database.nl2agent_session_db import (
    Nl2AgentSessionIdentity,
    get_nl2agent_session_snapshot_by_identity,
    update_nl2agent_workflow_state_by_identity,
)
from utils.nl2agent_card_validation import (
    Nl2AgentCardValidationError,
    parse_nl2agent_final_answer,
)


def _trusted_search_batches(state: Nl2AgentWorkflowState) -> Dict[str, Dict[str, Any]]:
    return {
        batch_id: batch.model_dump(mode="json")
        for batch_id, batch in state.recommendations.items()
    }


_REQUIREMENTS_FIELDS = (
    "goal",
    "audience_or_scenario",
    "primary_input",
    "expected_output",
    "key_constraints",
)


def _normalize_requirement(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", normalized)


def _requirements_fingerprint(summary: Dict[str, str]) -> str:
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_card_stage(state: Nl2AgentWorkflowState, card_types: set[str]) -> None:
    summary = evaluate_workflow(state)
    if summary.current_stage == "requirements_collecting":
        allowed = {"requirements_summary"}
        required: set[str] = set()
    elif summary.current_stage == "revision_routing":
        allowed = set(summary.allowed_card_types)
        required = set()
    else:
        allowed = set(summary.allowed_card_types)
        required = set(summary.expected_card_types)
    unexpected = card_types - allowed
    if unexpected:
        raise Nl2AgentCardValidationError(
            "The completed answer contains a card that is not allowed by the current workflow stage."
        )
    if required and card_types != required:
        raise Nl2AgentCardValidationError(
            "The completed answer must contain exactly the card types required by the current workflow stage."
        )


def _apply_card_transitions(state: Nl2AgentWorkflowState, cards: list[Any]) -> None:
    """Apply only presentation state that is inseparable from message persistence."""
    _validate_card_stage(state, {card.card_type for card in cards})
    for card in cards:
        if card.card_type == "requirements_summary":
            raw_summary = card.payload.model_dump(mode="json", exclude={"agent_id"})
            normalized_summary = {
                field_name: _normalize_requirement(raw_summary.get(field_name))
                for field_name in _REQUIREMENTS_FIELDS
            }
            if any(not value for value in normalized_summary.values()):
                raise Nl2AgentCardValidationError(
                    "Every requirements summary field must contain an explicit value."
                )
            state.requirements_review = RequirementsReview(
                status="awaiting_confirmation",
                summary=normalized_summary,
                fingerprint=_requirements_fingerprint(normalized_summary),
            )
        elif card.card_type in {"local_resources", "web_mcp", "web_skill"}:
            batch = state.recommendations.get(card.card_key)
            if batch is None:
                raise Nl2AgentCardValidationError(
                    "The recommendation card is not backed by this Session's trusted search result."
                )
            if batch.status == "searched":
                batch.status = "presented"
            if card.card_type in {"web_mcp", "web_skill"}:
                state.online_configuration_confirmed = False
        elif card.card_type == "final_review" and state.revision_mode:
            state.revision_mode = False


def finalize_nl2agent_message(
    *,
    tenant_id: str,
    user_id: str,
    runner_agent_id: int,
    draft_agent_id: int,
    conversation_id: int,
    message_index: Optional[int] = None,
    expected_revision: Optional[int] = None,
    assistant_answer: str,
) -> Dict[str, Any]:
    """Validate, version, and persist one NL2AGENT answer in one transaction."""
    identity = Nl2AgentSessionIdentity(
        tenant_id=tenant_id,
        user_id=user_id,
        runner_agent_id=int(runner_agent_id),
        draft_agent_id=int(draft_agent_id),
        conversation_id=int(conversation_id),
    )
    with get_db_session() as session:
        snapshot = get_nl2agent_session_snapshot_by_identity(
            identity,
            db_session=session,
        )
        if snapshot is None:
            raise Nl2AgentWorkflowConflictError(
                "The active NL2AGENT Session does not match this conversation."
            )
        current_revision = int(snapshot.get("workflow_revision", -1))
        if expected_revision is not None and current_revision != int(expected_revision):
            raise Nl2AgentWorkflowConflictError(
                "The NL2AGENT workflow revision changed before the message was finalized."
            )
        state = Nl2AgentWorkflowState.model_validate(snapshot["workflow_state"])
        try:
            parsed = parse_nl2agent_final_answer(
                assistant_answer,
                draft_agent_id=identity.draft_agent_id,
                workflow_revision=current_revision,
                trusted_search_batch_provider=lambda: _trusted_search_batches(state),
            )
        except Nl2AgentCardValidationError as exc:
            raise Nl2AgentValidationError(exc.repair_instruction) from exc

        try:
            _apply_card_transitions(state, parsed.envelope.cards)
        except Nl2AgentCardValidationError as exc:
            raise Nl2AgentValidationError(exc.repair_instruction) from exc
        state.revision += 1
        next_revision = state.revision
        envelope = parsed.envelope.model_copy(
            update={"workflow_revision": next_revision}
        )
        if not update_nl2agent_workflow_state_by_identity(
            identity=identity,
            expected_revision=current_revision,
            workflow_schema_version=WORKFLOW_SCHEMA_VERSION,
            workflow_state=state_to_dict(state),
            db_session=session,
        ):
            raise Nl2AgentWorkflowConflictError(
                "The NL2AGENT workflow revision changed before the message was finalized."
            )
        message = create_nl2agent_assistant_message(
            conversation_id=identity.conversation_id,
            message_index=message_index,
            display_text=parsed.display_text,
            envelope=envelope.model_dump(mode="json", exclude_none=True),
            user_id=user_id,
            db_session=session,
        )
        return {
            **message,
            "envelope": envelope.model_dump(mode="json", exclude_none=True),
            "workflow_revision": next_revision,
        }
