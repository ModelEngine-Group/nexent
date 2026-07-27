"""Unit tests for MCP community request models and content validators."""

import sys
import types
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

# Stub optional SDK deps and agent model imports used by consts.model.
sys.modules.setdefault("boto3", MagicMock())
sys.modules.setdefault("botocore", MagicMock())
sys.modules.setdefault("botocore.client", MagicMock())
sys.modules.setdefault("botocore.exceptions", MagicMock())

_agent_model_mod = types.ModuleType("nexent.core.agents.agent_model")
_agent_model_mod.AgentVerificationConfig = MagicMock()
_agent_model_mod.ToolConfig = MagicMock()
sys.modules.setdefault("nexent", MagicMock())
sys.modules.setdefault("nexent.core", MagicMock())
sys.modules.setdefault("nexent.core.agents", MagicMock())
sys.modules["nexent.core.agents.agent_model"] = _agent_model_mod

from backend.consts.model import (
    CommunityPublishRequest,
    CommunityReviewActionRequest,
    CommunityStatusUpdateRequest,
    CommunityUpdateRequest,
    SkillRepositoryListingCreateRequest,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  looks good  ", "looks good"),
        ("   ", None),
        ("", None),
        (None, None),
    ],
)
def test_community_review_action_content_validator(raw, expected):
    req = CommunityReviewActionRequest(review_id=1, content=raw)
    assert req.content == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  needs fixes  ", "needs fixes"),
        ("   ", None),
        ("", None),
        (None, None),
    ],
)
def test_community_status_update_content_validator(raw, expected):
    req = CommunityStatusUpdateRequest(status="rejected", content=raw)
    assert req.content == expected


def test_community_publish_request_strips_content():
    req = CommunityPublishRequest(mcp_id=1, content="  listing note  ")
    assert req.content == "listing note"

    blank = CommunityPublishRequest(mcp_id=1, content="   ")
    assert blank.content is None

    omitted = CommunityPublishRequest(mcp_id=1, content=None, name=None)
    assert omitted.content is None
    assert omitted.name is None


def test_community_update_request_strips_content():
    req = CommunityUpdateRequest(market_id=1, content="  resubmit note  ")
    assert req.content == "resubmit note"

    blank = CommunityUpdateRequest(market_id=1, content="")
    assert blank.content is None

    omitted = CommunityUpdateRequest(market_id=1, content=None, description=None)
    assert omitted.content is None
    assert omitted.description is None


def test_skill_repository_listing_create_request_accepts_content():
    req = SkillRepositoryListingCreateRequest(content="please review", icon="🔧")
    assert req.content == "please review"
    assert req.icon == "🔧"


def test_community_review_action_requires_positive_review_id():
    with pytest.raises(ValidationError):
        CommunityReviewActionRequest(review_id=0, content="x")
