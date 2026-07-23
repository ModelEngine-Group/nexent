"""Atomic persistence boundary for structured NL2AGENT assistant messages."""

from typing import Any, Dict

from agents.nl2agent_workflow import (
    WORKFLOW_SCHEMA_VERSION,
    Nl2AgentWorkflowState,
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


def finalize_nl2agent_message(
    *,
    tenant_id: str,
    user_id: str,
    runner_agent_id: int,
    draft_agent_id: int,
    conversation_id: int,
    message_index: int,
    expected_revision: int,
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
        if current_revision != int(expected_revision):
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
