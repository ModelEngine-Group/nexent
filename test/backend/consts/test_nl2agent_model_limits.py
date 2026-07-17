"""Boundary validation for NL2AGENT request and durable workflow models."""

import pytest
from pydantic import ValidationError

from agents.nl2agent_workflow import Nl2AgentWorkflowState
from consts.model import (
    Nl2AgentApplyLocalResourcesRequest,
    Nl2AgentModelSelectionRequest,
)


def test_request_identifiers_reject_booleans() -> None:
    with pytest.raises(ValidationError):
        Nl2AgentModelSelectionRequest(primary_model_id=True)

    with pytest.raises(ValidationError):
        Nl2AgentApplyLocalResourcesRequest(
            recommendation_batch_id="batch",
            tool_ids=[True],
        )


def test_request_collections_are_bounded() -> None:
    with pytest.raises(ValidationError):
        Nl2AgentApplyLocalResourcesRequest(
            recommendation_batch_id="batch",
            tool_ids=list(range(1, 102)),
        )


def test_workflow_identifiers_and_batch_maps_are_bounded() -> None:
    with pytest.raises(ValidationError):
        Nl2AgentWorkflowState(conversation_id=True)

    batches = {
        f"batch-{index}": {
            "resource_type": "local",
            "tool_ids": [],
            "skill_ids": [],
            "item_keys": [],
        }
        for index in range(101)
    }
    with pytest.raises(ValidationError):
        Nl2AgentWorkflowState(
            conversation_id=1,
            trusted_search_batches=batches,
        )
