"""Unit tests for backend.services.recipe_service.

Tests variable extraction, placeholder substitution, dependency prechecking,
and template instantiation. Mocks get_market_agent_detail and
build_repository_import_precheck at the import site, and uses delayed-import
patches for agent_service functions.
"""

import sys
import os
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Mock infrastructure — only mock DB-related modules, not consts (which is a real package)
# ---------------------------------------------------------------------------

# Mock database.client to avoid real DB connections
client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock(side_effect=lambda obj: obj if isinstance(obj, dict) else {})
client_mock.db_client = MagicMock()
sys.modules.setdefault('database.client', client_mock)

# Mock database.db_models
db_models_mock = MagicMock()
sys.modules.setdefault('database.db_models', db_models_mock)

# Mock database.market_db — imported by recipe_service as `from database.market_db import get_market_agent_detail`
market_db_mock = MagicMock()
market_db_mock.get_market_agent_detail = MagicMock()
sys.modules.setdefault('database.market_db', market_db_mock)

# Mock database package
database_pkg = types.ModuleType("database")
database_pkg.__path__ = []
database_pkg.market_db = market_db_mock
sys.modules.setdefault('database', database_pkg)

# Mock services.repository_import_precheck — imported by recipe_service at module load
precheck_module = MagicMock()
precheck_module.build_repository_import_precheck = MagicMock()
sys.modules.setdefault('services.repository_import_precheck', precheck_module)
sys.modules.setdefault('backend.services.repository_import_precheck', precheck_module)

# Mock services.agent_service — imported lazily inside instantiate_from_template_impl
agent_service_mock = MagicMock()
agent_service_mock.import_agent_impl = MagicMock()
agent_service_mock.import_agent_with_skills_impl = MagicMock()
sys.modules.setdefault('services.agent_service', agent_service_mock)
sys.modules.setdefault('backend.services.agent_service', agent_service_mock)

# Mock services package
services_pkg = types.ModuleType("services")
services_pkg.__path__ = []
sys.modules.setdefault('services', services_pkg)

# Remove any stub from services.recipe_service that other test modules may have
# installed, so we import the real module here.
for _key in ('services.recipe_service', 'backend.services.recipe_service'):
    _existing = sys.modules.get(_key)
    if _existing is not None and not hasattr(_existing, 'apply_recipe_variables'):
        del sys.modules[_key]

# Now import the module under test
from backend.services import recipe_service
from backend.services.recipe_service import (
    extract_recipe_from_snapshot,
    apply_recipe_variables,
    precheck_dependencies,
    instantiate_from_template_impl,
)


# ---------------------------------------------------------------------------
# Tests: extract_recipe_from_snapshot
# ---------------------------------------------------------------------------

class TestExtractRecipeFromSnapshot:
    """Tests for recipe_service.extract_recipe_from_snapshot."""

    def test_extract_explicit_recipe(self):
        """Should return the explicit recipe when present in snapshot."""
        explicit = {
            "variables": [{"key": "model", "label": "Model", "type": "string"}],
            "layers": [{"layer_type": "agent", "entity_type": "agent", "entity_name": "my_agent"}],
            "post_actions": [{"action_type": "enable"}],
        }
        snapshot = {"agent_id": 1, "agent_info": {}, "mcp_info": [], "recipe": explicit}

        result = extract_recipe_from_snapshot(snapshot)

        assert result == explicit
        assert len(result["variables"]) == 1
        assert result["variables"][0]["key"] == "model"

    def test_extract_default_recipe_no_snapshot(self):
        """Should build default recipe when snapshot is not a dict."""
        result = extract_recipe_from_snapshot(None)

        assert "variables" in result
        assert "layers" in result
        assert "post_actions" in result
        assert len(result["variables"]) == 3  # model_name, output_language, search_depth
        assert result["post_actions"] == []

    def test_extract_default_recipe_no_explicit(self):
        """Should build default recipe from snapshot layers when no explicit recipe."""
        root_agent = {
            "name": "test_agent",
            "skill_names": ["skill1", "skill2"],
        }
        agent_info_json = {
            "agent_id": 100,
            "agent_info": {"100": root_agent},
            "mcp_info": [
                {"mcp_server_name": "weather"},
                {"mcp_server_name": "search"},
            ],
        }

        result = extract_recipe_from_snapshot(agent_info_json, root_agent)

        assert "variables" in result
        assert len(result["variables"]) == 3
        # Agent layer
        agent_layers = [l for l in result["layers"] if l["layer_type"] == "agent"]
        assert len(agent_layers) == 1
        assert agent_layers[0]["entity_name"] == "test_agent"
        # Skill layers
        skill_layers = [l for l in result["layers"] if l["layer_type"] == "skill"]
        assert len(skill_layers) == 2
        assert skill_layers[0]["entity_name"] == "skill1"
        # MCP layers
        mcp_layers = [l for l in result["layers"] if l["layer_type"] == "mcp"]
        assert len(mcp_layers) == 2
        assert mcp_layers[0]["entity_name"] == "weather"

    def test_extract_default_recipe_agent_name_fallback(self):
        """Should use display_name when name is missing for agent layer."""
        root_agent = {"display_name": "My Agent"}
        result = extract_recipe_from_snapshot({}, root_agent)

        agent_layers = [l for l in result["layers"] if l["layer_type"] == "agent"]
        assert len(agent_layers) == 1
        assert agent_layers[0]["entity_name"] == "My Agent"

    def test_extract_default_recipe_no_skills_no_mcp(self):
        """Should still build an agent layer when no skills or mcp servers."""
        root_agent = {"name": "simple"}
        result = extract_recipe_from_snapshot({}, root_agent)

        assert len(result["layers"]) == 1
        assert result["layers"][0]["layer_type"] == "agent"

    def test_extract_default_recipe_variables_format(self):
        """Default variables should have expected keys and format."""
        result = extract_recipe_from_snapshot(None)
        var_keys = [v["key"] for v in result["variables"]]
        assert "model_name" in var_keys
        assert "output_language" in var_keys
        assert "search_depth" in var_keys

        # search_depth should have options
        search_depth = next(v for v in result["variables"] if v["key"] == "search_depth")
        assert search_depth["type"] == "select"
        assert len(search_depth["options"]) == 2


# ---------------------------------------------------------------------------
# Tests: apply_recipe_variables
# ---------------------------------------------------------------------------

class TestApplyRecipeVariables:
    """Tests for recipe_service.apply_recipe_variables."""

    def test_replace_in_string(self):
        """Should replace <<TO_CONFIG:key>> placeholders in strings."""
        text = "Use model <<TO_CONFIG:model_name>> with depth <<TO_CONFIG:search_depth>>"
        variables = {"model_name": "gpt-4o", "search_depth": "quick"}

        result = apply_recipe_variables(text, variables)

        assert result == "Use model gpt-4o with depth quick"

    def test_replace_in_dict(self):
        """Should recursively replace placeholders in dict values."""
        data = {
            "model": "<<TO_CONFIG:model_name>>",
            "config": {
                "language": "<<TO_CONFIG:output_language>>",
                "nested": ["<<TO_CONFIG:search_depth>>", "static"],
            },
        }
        variables = {"model_name": "gpt-4o", "output_language": "English", "search_depth": "comprehensive"}

        result = apply_recipe_variables(data, variables)

        assert result["model"] == "gpt-4o"
        assert result["config"]["language"] == "English"
        assert result["config"]["nested"][0] == "comprehensive"
        assert result["config"]["nested"][1] == "static"

    def test_replace_in_list(self):
        """Should recursively replace placeholders in list items."""
        data = ["<<TO_CONFIG:model_name>>", {"inner": "<<TO_CONFIG:output_language>>"}]
        variables = {"model_name": "claude-3", "output_language": "中文"}

        result = apply_recipe_variables(data, variables)

        assert result[0] == "claude-3"
        assert result[1]["inner"] == "中文"

    def test_replace_no_value_leaves_placeholder(self):
        """Should leave placeholder unchanged when no value is provided."""
        text = "Model: <<TO_CONFIG:unknown_var>>"
        variables = {}

        result = apply_recipe_variables(text, variables)

        assert result == "Model: <<TO_CONFIG:unknown_var>>"

    def test_replace_non_string_types(self):
        """Should pass through non-string, non-dict, non-list values unchanged."""
        assert apply_recipe_variables(42, {}) == 42
        assert apply_recipe_variables(True, {}) is True
        assert apply_recipe_variables(None, {}) is None

    def test_replace_mixed_string(self):
        """Should replace multiple placeholders within a single string."""
        text = "<<TO_CONFIG:model_name>> and <<TO_CONFIG:model_name>>"
        variables = {"model_name": "gpt-4o"}

        result = apply_recipe_variables(text, variables)

        assert result == "gpt-4o and gpt-4o"


# ---------------------------------------------------------------------------
# Tests: precheck_dependencies
# ---------------------------------------------------------------------------

class TestPrecheckDependencies:
    """Tests for recipe_service.precheck_dependencies."""

    def test_precheck_success(self):
        """Should return missing=[], has_abnormal=False when all deps available."""
        from consts.model import RepositoryImportPrecheckResponse, RepositoryImportRequirementItem

        mock_response = RepositoryImportPrecheckResponse(
            agent_repository_id=1,
            display_name="Test",
            total_count=3,
            available_count=3,
            percent=100,
            has_abnormal=False,
            items=[
                RepositoryImportRequirementItem(type="model", key="m1", name="gpt-4o", available=True),
                RepositoryImportRequirementItem(type="mcp", key="mcp1", name="weather", available=True),
                RepositoryImportRequirementItem(type="knowledge_base", key="kb1", name="docs", available=True),
            ],
        )
        with patch("backend.services.recipe_service.build_repository_import_precheck", return_value=mock_response):
            result = precheck_dependencies({"agent_id": 1}, "tenant_1")

        assert result["missing"] == []
        assert result["has_abnormal"] is False
        assert result["total_count"] == 3
        assert result["available_count"] == 3

    def test_precheck_with_missing(self):
        """Should return missing items when some deps unavailable."""
        from consts.model import RepositoryImportPrecheckResponse, RepositoryImportRequirementItem

        mock_response = RepositoryImportPrecheckResponse(
            agent_repository_id=1,
            display_name="Test",
            total_count=3,
            available_count=1,
            percent=33,
            has_abnormal=True,
            items=[
                RepositoryImportRequirementItem(type="model", key="m1", name="gpt-4o", available=True),
                RepositoryImportRequirementItem(type="mcp", key="mcp1", name="weather", available=False, reason_code="mcp_not_found"),
                RepositoryImportRequirementItem(type="knowledge_base", key="kb1", name="docs", available=False, reason_code="kb_not_found"),
            ],
        )
        with patch("backend.services.recipe_service.build_repository_import_precheck", return_value=mock_response):
            result = precheck_dependencies({"agent_id": 1}, "tenant_1")

        assert len(result["missing"]) == 2
        assert result["has_abnormal"] is True
        assert result["total_count"] == 3
        assert result["available_count"] == 1
        # Verify missing item format
        missing_item = result["missing"][0]
        assert "type" in missing_item
        assert "key" in missing_item
        assert "name" in missing_item
        assert "reason_code" in missing_item

    def test_precheck_exception(self):
        """Should return error dict when precheck raises an exception."""
        with patch("backend.services.recipe_service.build_repository_import_precheck", side_effect=Exception("DB error")):
            result = precheck_dependencies({"agent_id": 1}, "tenant_1")

        assert result["missing"] == []
        assert result["has_abnormal"] is False
        assert result["total_count"] == 0
        assert result["available_count"] == 0
        assert "error" in result
        assert "DB error" in result["error"]


# ---------------------------------------------------------------------------
# Tests: instantiate_from_template_impl
# ---------------------------------------------------------------------------

class TestInstantiateFromTemplateImpl:
    """Tests for recipe_service.instantiate_from_template_impl."""

    @pytest.mark.anyio
    async def test_instantiate_not_found(self):
        """Should raise ValueError when template not found."""
        with patch("backend.services.recipe_service.get_market_agent_detail", return_value=None):
            with pytest.raises(ValueError, match="Template not found"):
                await instantiate_from_template_impl(
                    template_id=999,
                    variable_values={},
                    user_id="user_1",
                    tenant_id="tenant_1",
                    authorization="Bearer token",
                )

    @pytest.mark.anyio
    async def test_instantiate_invalid_snapshot(self):
        """Should raise ValueError when agent_info_json is not a dict."""
        with patch("backend.services.recipe_service.get_market_agent_detail", return_value={"agent_info_json": "not a dict"}):
            with pytest.raises(ValueError, match="Template snapshot is invalid"):
                await instantiate_from_template_impl(
                    template_id=1,
                    variable_values={},
                    user_id="user_1",
                    tenant_id="tenant_1",
                    authorization="Bearer token",
                )

    @pytest.mark.anyio
    async def test_instantiate_with_missing_deps_no_force(self):
        """Should return precheck info without proceeding when deps missing and force_import=False."""
        snapshot_data = {
            "agent_id": 100,
            "agent_info": {
                "100": {
                    "agent_id": 100,
                    "name": "test",
                    "description": "test",
                    "business_description": "test",
                    "max_steps": 20,
                    "provide_run_summary": True,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                    "model_names": ["nonexistent_model"],
                }
            },
            "mcp_info": [],
        }

        with patch("backend.services.recipe_service.get_market_agent_detail", return_value={"agent_info_json": snapshot_data, "display_name": "Test"}):
            with patch("backend.services.recipe_service.precheck_dependencies", return_value={"has_abnormal": True, "missing": [{"type": "model", "key": "m1", "name": "nonexistent_model"}]}):
                result = await instantiate_from_template_impl(
                    template_id=1,
                    variable_values={},
                    user_id="user_1",
                    tenant_id="tenant_1",
                    authorization="Bearer token",
                    force_import=False,
                )

        assert result["agent_id"] is None
        assert "precheck" in result
        assert result["precheck"]["has_abnormal"] is True

    @pytest.mark.anyio
    async def test_instantiate_success_with_skills(self):
        """Should call import_agent_with_skills_impl when snapshot has skills."""
        snapshot_data = {
            "agent_id": 100,
            "agent_info": {
                "100": {
                    "agent_id": 100,
                    "name": "test",
                    "description": "test",
                    "business_description": "test",
                    "max_steps": 20,
                    "provide_run_summary": True,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                    "model_names": [],
                    "skill_names": ["skill1"],
                }
            },
            "mcp_info": [],
            "skills": [{"skill_name": "skill1", "skill_zip_base64": "base64data"}],
        }

        mock_import = AsyncMock(return_value={"100": 200})

        with patch("backend.services.recipe_service.get_market_agent_detail", return_value={"agent_info_json": snapshot_data, "display_name": "Test"}):
            with patch("backend.services.recipe_service.precheck_dependencies", return_value={"has_abnormal": False, "missing": []}):
                with patch.object(agent_service_mock, "import_agent_with_skills_impl", mock_import):
                    with patch.object(agent_service_mock, "import_agent_impl", AsyncMock()):
                        result = await instantiate_from_template_impl(
                            template_id=1,
                            variable_values={"model_name": "gpt-4o"},
                            user_id="user_1",
                            tenant_id="tenant_1",
                            authorization="Bearer token",
                            force_import=True,
                        )

        assert result["agent_id"] == 200
        mock_import.assert_awaited_once()

    @pytest.mark.anyio
    async def test_instantiate_success_without_skills(self):
        """Should call import_agent_impl when snapshot has no skills."""
        snapshot_data = {
            "agent_id": 100,
            "agent_info": {
                "100": {
                    "agent_id": 100,
                    "name": "test",
                    "description": "test",
                    "business_description": "test",
                    "max_steps": 20,
                    "provide_run_summary": True,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                    "model_names": [],
                }
            },
            "mcp_info": [],
        }

        mock_import = AsyncMock(return_value={"100": 300})

        with patch("backend.services.recipe_service.get_market_agent_detail", return_value={"agent_info_json": snapshot_data, "display_name": "Test"}):
            with patch("backend.services.recipe_service.precheck_dependencies", return_value={"has_abnormal": False, "missing": []}):
                with patch.object(agent_service_mock, "import_agent_with_skills_impl", AsyncMock()):
                    with patch.object(agent_service_mock, "import_agent_impl", mock_import):
                        result = await instantiate_from_template_impl(
                            template_id=1,
                            variable_values={},
                            user_id="user_1",
                            tenant_id="tenant_1",
                            authorization="Bearer token",
                            force_import=True,
                        )

        assert result["agent_id"] == 300
        mock_import.assert_awaited_once()

    @pytest.mark.anyio
    async def test_instantiate_with_force_import_bypasses_missing_deps(self):
        """Should proceed with import when force_import=True even with missing deps."""
        snapshot_data = {
            "agent_id": 100,
            "agent_info": {
                "100": {
                    "agent_id": 100,
                    "name": "test",
                    "description": "test",
                    "business_description": "test",
                    "max_steps": 20,
                    "provide_run_summary": True,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                    "model_names": [],
                }
            },
            "mcp_info": [],
        }

        mock_import = AsyncMock(return_value={"100": 500})

        with patch("backend.services.recipe_service.get_market_agent_detail", return_value={"agent_info_json": snapshot_data, "display_name": "Test"}):
            with patch("backend.services.recipe_service.precheck_dependencies", return_value={"has_abnormal": True, "missing": [{"type": "model", "key": "m1", "name": "missing_model"}]}):
                with patch.object(agent_service_mock, "import_agent_with_skills_impl", AsyncMock()):
                    with patch.object(agent_service_mock, "import_agent_impl", mock_import):
                        result = await instantiate_from_template_impl(
                            template_id=1,
                            variable_values={},
                            user_id="user_1",
                            tenant_id="tenant_1",
                            authorization="Bearer token",
                            force_import=True,
                        )

        # Should proceed with import despite missing deps
        assert result["agent_id"] == 500
        assert "precheck" in result

    @pytest.mark.anyio
    async def test_instantiate_variable_substitution(self):
        """Should apply recipe variables before validating snapshot."""
        snapshot_data = {
            "agent_id": 100,
            "agent_info": {
                "100": {
                    "agent_id": 100,
                    "name": "test",
                    "description": "Use <<TO_CONFIG:output_language>>",
                    "business_description": "test",
                    "max_steps": 20,
                    "provide_run_summary": True,
                    "enabled": True,
                    "tools": [],
                    "managed_agents": [],
                    "model_names": ["<<TO_CONFIG:model_name>>"],
                }
            },
            "mcp_info": [],
        }

        mock_import = AsyncMock(return_value={"100": 600})

        with patch("backend.services.recipe_service.get_market_agent_detail", return_value={"agent_info_json": snapshot_data, "display_name": "Test"}):
            with patch("backend.services.recipe_service.precheck_dependencies", return_value={"has_abnormal": False, "missing": []}):
                with patch.object(agent_service_mock, "import_agent_with_skills_impl", AsyncMock()):
                    with patch.object(agent_service_mock, "import_agent_impl", mock_import):
                        result = await instantiate_from_template_impl(
                            template_id=1,
                            variable_values={"model_name": "gpt-4o", "output_language": "English"},
                            user_id="user_1",
                            tenant_id="tenant_1",
                            authorization="Bearer token",
                            force_import=True,
                        )

        assert result["agent_id"] == 600
