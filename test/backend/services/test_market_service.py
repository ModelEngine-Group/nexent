"""Unit tests for backend.services.market_service.

Tests the business orchestration layer that translates database results into
the frontend API response format. Mocks market_db at the import site to
verify list_market_agents_impl, get_market_agent_detail_impl,
list_categories_impl, get_agent_mcp_servers_impl, create_review_impl,
and list_reviews_impl.
"""

import sys
import os
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

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

# Mock database.market_db — imported by market_service as `from database import market_db`
market_db_mock = MagicMock()
sys.modules.setdefault('database.market_db', market_db_mock)

# Mock database package
database_pkg = types.ModuleType("database")
database_pkg.__path__ = []
database_pkg.market_db = market_db_mock
sys.modules.setdefault('database', database_pkg)

# Provide a lightweight stub for services.recipe_service so that
# market_service can import extract_recipe_from_snapshot at module load.
# We use a real ModuleType (not MagicMock) so it doesn't interfere with
# other test modules that import the real recipe_service.
_recipe_stub = types.ModuleType("services.recipe_service")
_recipe_stub.extract_recipe_from_snapshot = MagicMock(return_value={"variables": [], "layers": [], "post_actions": []})
# Only install if the real recipe_service hasn't been imported yet
if 'services.recipe_service' not in sys.modules:
    sys.modules['services.recipe_service'] = _recipe_stub
if 'backend.services.recipe_service' not in sys.modules:
    sys.modules['backend.services.recipe_service'] = _recipe_stub

# Now import the module under test
from backend.services import market_service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_market_db():
    """Create a mock for the market_db module used by market_service."""
    with patch.object(market_service, "market_db") as m:
        yield m


@pytest.fixture
def mock_recipe_extract():
    """Mock extract_recipe_from_snapshot to avoid testing recipe logic here."""
    with patch.object(market_service, "extract_recipe_from_snapshot", return_value={"variables": [], "layers": [], "post_actions": []}) as m:
        yield m


# ---------------------------------------------------------------------------
# Tests: list_market_agents_impl
# ---------------------------------------------------------------------------

class TestListMarketAgentsImpl:
    """Tests for market_service.list_market_agents_impl."""

    def test_list_market_agents_impl_basic(self, mock_market_db):
        """Should return {items, pagination, featured_items}."""
        mock_market_db.list_market_agents.return_value = {
            "items": [
                {"id": 1, "name": "agent1", "category": {"name": "cat1", "display_name": "Cat1", "display_name_zh": "类别1"}},
            ],
            "total": 1,
        }
        mock_market_db.list_featured_agents.return_value = [
            {"id": 10, "name": "featured1", "is_featured": True}
        ]

        result = market_service.list_market_agents_impl(page=1, page_size=20, lang="zh")

        assert "items" in result
        assert "pagination" in result
        assert "featured_items" in result
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["page_size"] == 20
        assert result["pagination"]["total"] == 1
        assert result["pagination"]["total_pages"] == 1
        assert len(result["featured_items"]) == 1
        assert result["featured_items"][0]["id"] == 10

    def test_list_market_agents_impl_total_pages_calculation(self, mock_market_db):
        """Should correctly calculate total_pages from total and page_size."""
        mock_market_db.list_market_agents.return_value = {
            "items": [],
            "total": 55,
        }
        mock_market_db.list_featured_agents.return_value = []

        result = market_service.list_market_agents_impl(page=2, page_size=20)

        # 55 items / 20 per page = 3 pages
        assert result["pagination"]["total_pages"] == 3
        assert result["pagination"]["total"] == 55

    def test_list_market_agents_impl_localize_zh(self, mock_market_db):
        """Should add display_label using display_name_zh when lang=zh."""
        category = {"name": "cat1", "display_name": "Cat1", "display_name_zh": "类别1"}
        mock_market_db.list_market_agents.return_value = {
            "items": [{"id": 1, "category": category}],
            "total": 1,
        }
        mock_market_db.list_featured_agents.return_value = []

        result = market_service.list_market_agents_impl(lang="zh")

        # _localize_category mutates in place — check display_label
        assert result["items"][0]["category"]["display_label"] == "类别1"

    def test_list_market_agents_impl_localize_en(self, mock_market_db):
        """Should add display_label using display_name when lang=en."""
        category = {"name": "cat1", "display_name": "Cat1", "display_name_zh": "类别1"}
        mock_market_db.list_market_agents.return_value = {
            "items": [{"id": 1, "category": category}],
            "total": 1,
        }
        mock_market_db.list_featured_agents.return_value = []

        result = market_service.list_market_agents_impl(lang="en")

        assert result["items"][0]["category"]["display_label"] == "Cat1"

    def test_list_market_agents_impl_no_category(self, mock_market_db):
        """Should handle items without a category dict."""
        mock_market_db.list_market_agents.return_value = {
            "items": [{"id": 1, "category": None}],
            "total": 1,
        }
        mock_market_db.list_featured_agents.return_value = []

        result = market_service.list_market_agents_impl(lang="zh")

        # Should not crash, category stays None
        assert result["items"][0]["category"] is None

    def test_list_market_agents_impl_passes_filters(self, mock_market_db):
        """Should pass all filter parameters to market_db.list_market_agents."""
        mock_market_db.list_market_agents.return_value = {"items": [], "total": 0}
        mock_market_db.list_featured_agents.return_value = []

        market_service.list_market_agents_impl(
            page=2,
            page_size=10,
            category="productivity",
            tag="ai",
            search="test",
            sort="popular",
            source="official",
            lang="zh",
        )

        mock_market_db.list_market_agents.assert_called_once_with(
            page=2, page_size=10, category="productivity",
            tag="ai", search="test", sort="popular", source="official",
        )


# ---------------------------------------------------------------------------
# Tests: get_market_agent_detail_impl
# ---------------------------------------------------------------------------

class TestGetMarketAgentDetailImpl:
    """Tests for market_service.get_market_agent_detail_impl."""

    def test_get_market_agent_detail_impl_not_found(self, mock_market_db):
        """Should raise ValueError when agent not found."""
        mock_market_db.get_market_agent_detail.return_value = None

        with pytest.raises(ValueError, match="not found"):
            market_service.get_market_agent_detail_impl(999, "tenant_1")

    def test_get_market_agent_detail_impl_basic(self, mock_market_db, mock_recipe_extract):
        """Should return detail dict with all expected fields."""
        # Build a realistic snapshot
        root_agent = {
            "business_description": "A business agent",
            "max_steps": 30,
            "provide_run_summary": True,
            "duty_prompt": "You are a helpful agent",
            "constraint_prompt": "Do not hallucinate",
            "few_shots_prompt": "Example: ...",
            "enabled": True,
            "model_ids": [1, 2],
            "model_names": ["gpt-4o", "claude-3"],
            "tools": [
                {"id": 1, "class_name": "SearchTool", "name": "search", "description": "Search the web"}
            ],
            "skill_names": ["skill1"],
        }
        agent_info_json = {
            "agent_id": 100,
            "agent_info": {"100": root_agent},
            "mcp_info": [
                {"id": 1, "mcp_server_name": "weather", "mcp_url": "http://mcp.example.com"}
            ],
        }

        mock_market_db.get_market_agent_detail.return_value = {
            "agent_repository_id": 1,
            "agent_id": 100,
            "name": "test_agent",
            "display_name": "Test Agent",
            "description": "A test agent",
            "author": "author1",
            "downloads": 42,
            "is_featured": True,
            "create_time": datetime(2024, 1, 1, 12, 0, 0),
            "update_time": datetime(2024, 1, 2, 12, 0, 0),
            "icon": "🤖",
            "source": "community",
            "is_official_template": False,
            "agent_info_json": agent_info_json,
            "category_id": None,
            "tags": ["ai", "chatbot"],
            "default_init_prompt": "Hello",
            "quick_prompts": [{"text": "Quick action"}],
            "members_info": {},
            "expert_type": "agent",
        }
        mock_market_db.list_categories.return_value = []
        mock_market_db.get_rating_summary.return_value = {"average_rating": 4.5, "total_reviews": 3}

        result = market_service.get_market_agent_detail_impl(1, "tenant_1", lang="zh")

        # Verify top-level fields
        assert result["id"] == 1
        assert result["agent_id"] == 100
        assert result["name"] == "test_agent"
        assert result["display_name"] == "Test Agent"
        assert result["description"] == "A test agent"
        assert result["author"] == "author1"
        assert result["download_count"] == 42
        assert result["is_featured"] is True
        assert result["source"] == "community"
        assert result["is_official_template"] is False

        # Verify snapshot-extracted fields
        assert result["business_description"] == "A business agent"
        assert result["max_steps"] == 30
        assert result["provide_run_summary"] is True
        assert result["duty_prompt"] == "You are a helpful agent"
        assert result["constraint_prompt"] == "Do not hallucinate"
        assert result["few_shots_prompt"] == "Example: ..."
        assert result["enabled"] is True
        assert result["model_id"] == 1
        assert result["model_name"] == "gpt-4o"

        # Verify tools
        assert len(result["tools"]) == 1
        assert result["tools"][0]["class_name"] == "SearchTool"
        assert result["tools"][0]["name"] == "search"

        # Verify mcp_servers
        assert len(result["mcp_servers"]) == 1
        assert result["mcp_servers"][0]["mcp_server_name"] == "weather"
        assert result["mcp_servers"][0]["mcp_url"] == "http://mcp.example.com"

        # Verify recipe
        assert "recipe" in result

        # Verify rating
        assert result["average_rating"] == 4.5
        assert result["total_reviews"] == 3

    def test_get_market_agent_detail_impl_with_category(self, mock_market_db, mock_recipe_extract):
        """Should resolve and localize category when category_id is set."""
        root_agent = {"business_description": "", "max_steps": 20, "provide_run_summary": True}
        agent_info_json = {"agent_id": 100, "agent_info": {"100": root_agent}, "mcp_info": []}

        mock_market_db.get_market_agent_detail.return_value = {
            "agent_repository_id": 1,
            "agent_id": 100,
            "name": "test",
            "display_name": "Test",
            "description": "desc",
            "author": "a",
            "downloads": 0,
            "is_featured": False,
            "create_time": datetime(2024, 1, 1),
            "update_time": datetime(2024, 1, 1),
            "agent_info_json": agent_info_json,
            "category_id": "1",
            "tags": [],
            "expert_type": "agent",
            "source": "community",
            "is_official_template": False,
        }
        mock_market_db.list_categories.return_value = [
            {"id": 1, "name": "productivity", "display_name": "Productivity", "display_name_zh": "效率"}
        ]
        mock_market_db.get_rating_summary.return_value = {"average_rating": 0.0, "total_reviews": 0}

        result = market_service.get_market_agent_detail_impl(1, "tenant_1", lang="zh")

        assert result["category"] is not None
        assert result["category"]["name"] == "productivity"
        assert result["category"]["display_label"] == "效率"

    def test_get_market_agent_detail_impl_no_snapshot(self, mock_market_db, mock_recipe_extract):
        """Should handle missing or invalid agent_info_json gracefully."""
        mock_market_db.get_market_agent_detail.return_value = {
            "agent_repository_id": 1,
            "agent_id": 100,
            "name": "test",
            "display_name": "Test",
            "description": "desc",
            "author": "a",
            "downloads": 0,
            "is_featured": False,
            "create_time": datetime(2024, 1, 1),
            "update_time": datetime(2024, 1, 1),
            "agent_info_json": None,
            "category_id": None,
            "tags": [],
            "expert_type": "agent",
            "source": "community",
            "is_official_template": False,
        }
        mock_market_db.get_rating_summary.return_value = {"average_rating": 0.0, "total_reviews": 0}

        result = market_service.get_market_agent_detail_impl(1, "tenant_1")

        # Should not crash, should return defaults
        assert result["business_description"] == ""
        assert result["max_steps"] == 20
        assert result["tools"] == []
        assert result["mcp_servers"] == []
        assert result["agent_json"] == {}


# ---------------------------------------------------------------------------
# Tests: list_categories_impl
# ---------------------------------------------------------------------------

class TestListCategoriesImpl:
    """Tests for market_service.list_categories_impl."""

    def test_list_categories_impl_zh(self, mock_market_db):
        """Should localize categories with display_name_zh when lang=zh."""
        mock_market_db.list_categories.return_value = [
            {"id": 1, "name": "cat1", "display_name": "Cat1", "display_name_zh": "类别1"},
            {"id": 2, "name": "cat2", "display_name": "Cat2", "display_name_zh": "类别2"},
        ]

        result = market_service.list_categories_impl(lang="zh")

        assert len(result) == 2
        assert result[0]["display_label"] == "类别1"
        assert result[1]["display_label"] == "类别2"

    def test_list_categories_impl_en(self, mock_market_db):
        """Should localize categories with display_name when lang=en."""
        mock_market_db.list_categories.return_value = [
            {"id": 1, "name": "cat1", "display_name": "Cat1", "display_name_zh": "类别1"},
        ]

        result = market_service.list_categories_impl(lang="en")

        assert result[0]["display_label"] == "Cat1"

    def test_list_categories_impl_empty(self, mock_market_db):
        """Should return empty list when no categories."""
        mock_market_db.list_categories.return_value = []

        result = market_service.list_categories_impl()

        assert result == []

    def test_list_categories_impl_with_entity_type(self, mock_market_db):
        """Should pass entity_type to market_db.list_categories."""
        mock_market_db.list_categories.return_value = []

        market_service.list_categories_impl(entity_type="agent")

        mock_market_db.list_categories.assert_called_once_with(entity_type="agent")


# ---------------------------------------------------------------------------
# Tests: get_agent_mcp_servers_impl
# ---------------------------------------------------------------------------

class TestGetAgentMcpServersImpl:
    """Tests for market_service.get_agent_mcp_servers_impl."""

    def test_get_agent_mcp_servers_impl_found(self, mock_market_db):
        """Should extract mcp_info list from the agent snapshot."""
        mock_market_db.get_market_agent_detail.return_value = {
            "agent_info_json": {
                "mcp_info": [
                    {"id": 1, "mcp_server_name": "weather", "mcp_url": "http://mcp1.example.com"},
                    {"id": 2, "mcp_server_name": "search", "mcp_url": "http://mcp2.example.com"},
                ]
            }
        }

        result = market_service.get_agent_mcp_servers_impl(1)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["mcp_server_name"] == "weather"
        assert result[0]["mcp_url"] == "http://mcp1.example.com"
        assert result[1]["id"] == 2

    def test_get_agent_mcp_servers_impl_not_found(self, mock_market_db):
        """Should raise ValueError when agent not found."""
        mock_market_db.get_market_agent_detail.return_value = None

        with pytest.raises(ValueError, match="not found"):
            market_service.get_agent_mcp_servers_impl(999)

    def test_get_agent_mcp_servers_impl_no_mcp(self, mock_market_db):
        """Should return empty list when snapshot has no mcp_info."""
        mock_market_db.get_market_agent_detail.return_value = {
            "agent_info_json": {"mcp_info": []}
        }

        result = market_service.get_agent_mcp_servers_impl(1)

        assert result == []

    def test_get_agent_mcp_servers_impl_no_snapshot(self, mock_market_db):
        """Should return empty list when agent_info_json is not a dict."""
        mock_market_db.get_market_agent_detail.return_value = {
            "agent_info_json": None
        }

        result = market_service.get_agent_mcp_servers_impl(1)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: create_review_impl
# ---------------------------------------------------------------------------

class TestCreateReviewImpl:
    """Tests for market_service.create_review_impl."""

    def test_create_review_impl_success(self, mock_market_db):
        """Should delegate to market_db.create_review after verifying listing exists."""
        mock_market_db.get_market_agent_detail.return_value = {"agent_repository_id": 1}
        mock_market_db.create_review.return_value = {"review_id": 42, "status": "visible"}

        result = market_service.create_review_impl(
            1, rating=5, comment="Great!", user_id="user_1", tenant_id="tenant_1"
        )

        assert result["review_id"] == 42
        assert result["status"] == "visible"
        mock_market_db.create_review.assert_called_once_with(
            entity_type="agent", entity_id=1, tenant_id="tenant_1",
            user_id="user_1", rating=5, comment="Great!",
        )

    def test_create_review_impl_not_found(self, mock_market_db):
        """Should raise ValueError when listing not found."""
        mock_market_db.get_market_agent_detail.return_value = None

        with pytest.raises(ValueError, match="not found"):
            market_service.create_review_impl(
                999, rating=5, comment="Great!", user_id="user_1", tenant_id="tenant_1"
            )


# ---------------------------------------------------------------------------
# Tests: list_reviews_impl
# ---------------------------------------------------------------------------

class TestListReviewsImpl:
    """Tests for market_service.list_reviews_impl."""

    def test_list_reviews_impl_success(self, mock_market_db):
        """Should delegate to market_db.list_reviews after verifying listing exists."""
        mock_market_db.get_market_agent_detail.return_value = {"agent_repository_id": 1}
        mock_market_db.list_reviews.return_value = {
            "summary": {"average_rating": 4.5, "total_reviews": 3},
            "reviews": [{"id": 1, "user_name": "test", "rating": 5, "content": "Great!"}],
        }

        result = market_service.list_reviews_impl(1, page=1, page_size=20)

        assert result["summary"]["average_rating"] == 4.5
        assert len(result["reviews"]) == 1
        mock_market_db.list_reviews.assert_called_once_with(
            entity_type="agent", entity_id=1, page=1, page_size=20,
        )

    def test_list_reviews_impl_not_found(self, mock_market_db):
        """Should raise ValueError when listing not found."""
        mock_market_db.get_market_agent_detail.return_value = None

        with pytest.raises(ValueError, match="not found"):
            market_service.list_reviews_impl(999)


# ---------------------------------------------------------------------------
# Tests: internal helpers
# ---------------------------------------------------------------------------

class TestExtractRootAgent:
    """Tests for _extract_root_agent_from_snapshot."""

    def test_extract_root_agent_found(self):
        """Should resolve root agent from agent_info map."""
        snapshot = {
            "agent_id": 100,
            "agent_info": {"100": {"name": "root", "duty_prompt": "test"}},
        }
        result = market_service._extract_root_agent_from_snapshot(snapshot)
        assert result["name"] == "root"
        assert result["duty_prompt"] == "test"

    def test_extract_root_agent_not_dict(self):
        """Should return empty dict when snapshot is not a dict."""
        assert market_service._extract_root_agent_from_snapshot(None) == {}
        assert market_service._extract_root_agent_from_snapshot("string") == {}

    def test_extract_root_agent_missing_agent_id(self):
        """Should return empty dict when agent_id is missing."""
        assert market_service._extract_root_agent_from_snapshot({"agent_info": {}}) == {}

    def test_extract_root_agent_not_in_map(self):
        """Should return empty dict when agent_id not in agent_info map."""
        snapshot = {"agent_id": 999, "agent_info": {"100": {"name": "root"}}}
        assert market_service._extract_root_agent_from_snapshot(snapshot) == {}


class TestExtractTools:
    """Tests for _extract_tools_from_snapshot."""

    def test_extract_tools_basic(self):
        """Should format tool dicts from raw tools list."""
        root_agent = {
            "tools": [
                {"id": 1, "class_name": "SearchTool", "name": "search", "description": "Search"},
                {"id": 2, "class_name": "CalcTool", "origin_name": "calc", "description": "Calculate"},
            ]
        }
        result = market_service._extract_tools_from_snapshot(root_agent)
        assert len(result) == 2
        assert result[0]["class_name"] == "SearchTool"
        assert result[0]["name"] == "search"
        # When 'name' is missing, should fall back to 'origin_name'
        assert result[1]["name"] == "calc"

    def test_extract_tools_empty(self):
        """Should return empty list when no tools."""
        assert market_service._extract_tools_from_snapshot({}) == []
        assert market_service._extract_tools_from_snapshot({"tools": "not a list"}) == []

    def test_extract_tools_skip_non_dict(self):
        """Should skip non-dict entries in tools list."""
        root_agent = {"tools": [{"name": "ok"}, "not a dict", 123]}
        result = market_service._extract_tools_from_snapshot(root_agent)
        assert len(result) == 1


class TestExtractMcpServers:
    """Tests for _extract_mcp_servers_from_snapshot."""

    def test_extract_mcp_servers_basic(self):
        """Should format mcp_info from snapshot."""
        snapshot = {
            "mcp_info": [
                {"id": 1, "mcp_server_name": "weather", "mcp_url": "http://w.example.com"},
                {"id": 2, "mcp_server_name": "search", "mcp_url": "http://s.example.com"},
            ]
        }
        result = market_service._extract_mcp_servers_from_snapshot(snapshot)
        assert len(result) == 2
        assert result[0]["mcp_server_name"] == "weather"
        assert result[1]["mcp_url"] == "http://s.example.com"

    def test_extract_mcp_servers_empty(self):
        """Should return empty list when no mcp_info."""
        assert market_service._extract_mcp_servers_from_snapshot({}) == []
        assert market_service._extract_mcp_servers_from_snapshot(None) == []
        assert market_service._extract_mcp_servers_from_snapshot({"mcp_info": "not a list"}) == []

    def test_extract_mcp_servers_defaults(self):
        """Should use default values when fields are missing."""
        snapshot = {"mcp_info": [{}]}
        result = market_service._extract_mcp_servers_from_snapshot(snapshot)
        assert len(result) == 1
        assert result[0]["id"] == 0
        assert result[0]["mcp_server_name"] == ""
        assert result[0]["mcp_url"] == ""


class TestLocalizeCategory:
    """Tests for _localize_category."""

    def test_localize_zh(self):
        """Should set display_label to display_name_zh for zh."""
        cat = {"name": "cat", "display_name": "Cat", "display_name_zh": "类别"}
        market_service._localize_category(cat, "zh")
        assert cat["display_label"] == "类别"

    def test_localize_en(self):
        """Should set display_label to display_name for en."""
        cat = {"name": "cat", "display_name": "Cat", "display_name_zh": "类别"}
        market_service._localize_category(cat, "en")
        assert cat["display_label"] == "Cat"

    def test_localize_none(self):
        """Should do nothing when category is None."""
        market_service._localize_category(None, "zh")

    def test_localize_fallback_to_name(self):
        """Should fall back to name when display fields are missing."""
        cat = {"name": "cat"}
        market_service._localize_category(cat, "zh")
        assert cat["display_label"] == "cat"


class TestFirstOrNone:
    """Tests for _first_or_none."""

    def test_first_or_none_list(self):
        assert market_service._first_or_none([1, 2, 3]) == 1

    def test_first_or_none_empty(self):
        assert market_service._first_or_none([]) is None

    def test_first_or_none_none(self):
        assert market_service._first_or_none(None) is None

    def test_first_or_none_non_list(self):
        assert market_service._first_or_none("string") is None
