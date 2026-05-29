"""Unit tests for ASSET_OWNER visibility helpers."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from consts.const import (
    ASSET_OWNER_ROLE,
    ASSET_OWNER_TENANT_ID,
    PERMISSION_EDIT,
    PERMISSION_READ,
)

PROMPTS_HIDDEN_FLAG = "prompts_hidden"
from consts.exceptions import ValidationError
from backend.services import asset_owner_visibility as aov

ASSET_OWNER_RESOURCES_ROUTE = aov.ASSET_OWNER_RESOURCES_ROUTE


class TestRequireAssetOwnerEnabled:
    @patch("backend.services.asset_owner_visibility.ENABLE_ASSET_OWNER_ROLE", False)
    def test_raises_when_feature_disabled(self):
        with pytest.raises(ValidationError, match="ASSET_OWNER feature is not enabled"):
            aov.require_asset_owner_enabled()

    @patch("backend.services.asset_owner_visibility.ENABLE_ASSET_OWNER_ROLE", True)
    def test_no_op_when_feature_enabled(self):
        aov.require_asset_owner_enabled()


class TestFilterAccessibleRoutes:
    @patch("backend.services.asset_owner_visibility.ENABLE_ASSET_OWNER_ROLE", True)
    def test_returns_routes_unchanged_when_enabled(self):
        routes = ["/home", ASSET_OWNER_RESOURCES_ROUTE, "/settings"]
        assert aov.filter_accessible_routes_for_asset_owner_feature(routes) == routes

    @patch("backend.services.asset_owner_visibility.ENABLE_ASSET_OWNER_ROLE", False)
    def test_removes_asset_owner_route_when_disabled(self):
        routes = ["/home", ASSET_OWNER_RESOURCES_ROUTE, "/settings"]
        result = aov.filter_accessible_routes_for_asset_owner_feature(routes)
        assert ASSET_OWNER_RESOURCES_ROUTE not in result
        assert result == ["/home", "/settings"]


class TestCanViewSkill:
    def test_asset_owner_skill_visible_to_asset_owner_tenant(self):
        assert aov.can_view_skill(ASSET_OWNER_TENANT_ID, ASSET_OWNER_TENANT_ID) is True

    def test_asset_owner_skill_hidden_from_other_tenants(self):
        assert aov.can_view_skill("regular_tenant", ASSET_OWNER_TENANT_ID) is False

    def test_regular_skill_visible_to_any_tenant(self):
        assert aov.can_view_skill("regular_tenant", "other_tenant") is True
        assert aov.can_view_skill(None, "other_tenant") is True


class TestResolveAgentListPermission:
    def test_asset_owner_agent_read_only_for_non_asset_owner_role(self):
        agent = {"tenant_id": ASSET_OWNER_TENANT_ID, "created_by": "user1", "ingroup_permission": PERMISSION_EDIT}
        result = aov.resolve_agent_list_permission(
            user_role="ADMIN",
            agent=agent,
            user_id="user1",
            can_edit_all=True,
        )
        assert result == PERMISSION_READ

    def test_asset_owner_role_creator_gets_edit_on_asset_owner_agent(self):
        agent = {"tenant_id": ASSET_OWNER_TENANT_ID, "created_by": "user1", "ingroup_permission": PERMISSION_READ}
        result = aov.resolve_agent_list_permission(
            user_role=ASSET_OWNER_ROLE,
            agent=agent,
            user_id="user1",
            can_edit_all=False,
        )
        assert result == PERMISSION_EDIT

    def test_regular_agent_creator_gets_edit(self):
        agent = {"tenant_id": "tenant_a", "created_by": "user1", "ingroup_permission": PERMISSION_READ}
        result = aov.resolve_agent_list_permission(
            user_role="USER",
            agent=agent,
            user_id="user1",
            can_edit_all=False,
        )
        assert result == PERMISSION_EDIT

    def test_regular_agent_uses_ingroup_permission_when_not_creator(self):
        agent = {"tenant_id": "tenant_a", "created_by": "other", "ingroup_permission": PERMISSION_READ}
        result = aov.resolve_agent_list_permission(
            user_role="USER",
            agent=agent,
            user_id="user1",
            can_edit_all=False,
        )
        assert result == PERMISSION_READ


class TestApplyAgentDetailPromptVisibility:
    def test_masks_prompts_for_non_asset_owner_viewer(self):
        agent_info = {
            "tenant_id": ASSET_OWNER_TENANT_ID,
            "duty_prompt": "duty",
            "constraint_prompt": "constraint",
            "few_shots_prompt": "few",
        }
        result = aov.apply_agent_detail_prompt_visibility("regular_tenant", agent_info)
        assert result["duty_prompt"] is None
        assert result["constraint_prompt"] is None
        assert result["few_shots_prompt"] is None
        assert result[PROMPTS_HIDDEN_FLAG] is True
        assert agent_info["duty_prompt"] == "duty"

    def test_no_mask_for_asset_owner_tenant_viewer(self):
        agent_info = {
            "tenant_id": ASSET_OWNER_TENANT_ID,
            "duty_prompt": "duty",
            "constraint_prompt": "constraint",
            "few_shots_prompt": "few",
        }
        result = aov.apply_agent_detail_prompt_visibility(ASSET_OWNER_TENANT_ID, agent_info)
        assert result["duty_prompt"] == "duty"
        assert PROMPTS_HIDDEN_FLAG not in result

    def test_no_mask_for_regular_agent(self):
        agent_info = {
            "tenant_id": "tenant_a",
            "duty_prompt": "duty",
            "constraint_prompt": "constraint",
            "few_shots_prompt": "few",
        }
        result = aov.apply_agent_detail_prompt_visibility("regular_tenant", agent_info)
        assert result["duty_prompt"] == "duty"
        assert PROMPTS_HIDDEN_FLAG not in result


class TestPostprocessKnowledgeVisibility:
    def test_passthrough_items(self):
        items = [{"knowledge_id": 1}, {"knowledge_id": 2}]
        result = aov.postprocess_knowledge_visibility(items, "ADMIN", "tenant_a")
        assert result is items
        assert result == items
