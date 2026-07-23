from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.consts.model import AgentRequest


ACTION_ID = "2f8567b1-7080-4d7e-9f57-fac9db39cd20"


def test_agent_request_accepts_bound_nl2agent_action_context() -> None:
    request = AgentRequest(
        query="Requirements confirmed",
        draft_agent_id=7,
        nl2agent_action_context={
            "action_id": ACTION_ID,
            "action": "confirm_requirements",
            "display_text": "Requirements confirmed",
            "workflow_revision": 4,
        },
    )

    assert request.nl2agent_action_context is not None
    assert request.nl2agent_action_context.action_id == UUID(ACTION_ID)


@pytest.mark.parametrize(
    "overrides",
    [
        {"draft_agent_id": None},
        {"query": "Different text"},
        {"minio_files": [{"object_name": "secret.txt"}]},
    ],
)
def test_agent_request_rejects_invalid_nl2agent_action_context(overrides) -> None:
    payload = {
        "query": "Requirements confirmed",
        "draft_agent_id": 7,
        "nl2agent_action_context": {
            "action_id": ACTION_ID,
            "action": "confirm_requirements",
            "display_text": "Requirements confirmed",
            "workflow_revision": 4,
        },
        **overrides,
    }

    with pytest.raises(ValidationError):
        AgentRequest(**payload)
