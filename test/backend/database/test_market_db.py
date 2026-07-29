"""Unit tests for backend.database.market_db.

Tests the unified market database query layer with mocked SQLAlchemy sessions,
verifying that list_market_agents, get_market_agent_detail, list_featured_agents,
list_categories, list_tags, create_review, list_reviews, and get_rating_summary
return data structures matching the frontend API contract.
"""

import sys
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

# ---------------------------------------------------------------------------
# Mock infrastructure — prevent real DB / external service connections
# Only mock DB-related modules; consts is a real package and must not be mocked.
# ---------------------------------------------------------------------------

# Mock database.client to avoid real DB connections
client_mock = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock(side_effect=lambda obj: obj if isinstance(obj, dict) else MagicMock())
client_mock.db_client = MagicMock()
sys.modules.setdefault('database.client', client_mock)
sys.modules.setdefault('backend.database.client', client_mock)

# Mock database.db_models with real-ish column names
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, ARRAY, JSON,
    TIMESTAMP, Numeric, SmallInteger, Sequence, UniqueConstraint,
    Index, PrimaryKeyConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase


class _TestBase(DeclarativeBase):
    pass


class _AgentRepository(_TestBase):
    __tablename__ = "ag_agent_repository_t"
    agent_repository_id = Column(BigInteger, primary_key=True)
    agent_id = Column(Integer)
    name = Column(String(100))
    display_name = Column(String(100))
    description = Column(Text)
    author = Column(String(100))
    tags = Column(ARRAY(Text))
    tool_count = Column(Integer)
    icon = Column(String(100))
    downloads = Column(Integer, default=0)
    agent_info_json = Column(JSON)
    status = Column(String(30), default="not_shared")
    delete_flag = Column(String(1), default="N")
    source = Column(String(30), default="community")
    is_official_template = Column(Boolean, default=False)
    expert_type = Column(String(10), default="agent")
    category_id = Column(String(30))
    is_featured = Column(Boolean, default=False)
    featured_weight = Column(Integer, default=0)
    create_time = Column(TIMESTAMP)
    update_time = Column(TIMESTAMP)


class _MarketCategory(_TestBase):
    __tablename__ = "market_category_t"
    category_id = Column(Integer, primary_key=True)
    entity_type = Column(String(20), default="agent")
    name = Column(String(100))
    display_name = Column(String(100))
    display_name_zh = Column(String(100))
    description = Column(Text)
    description_zh = Column(Text)
    icon = Column(String(50))
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    delete_flag = Column(String(1), default="N")
    create_time = Column(TIMESTAMP)


class _MarketTag(_TestBase):
    __tablename__ = "market_tag_t"
    tag_id = Column(Integer, primary_key=True)
    name = Column(String(100))
    display_name = Column(String(100))
    description = Column(Text)
    delete_flag = Column(String(1), default="N")
    create_time = Column(TIMESTAMP)


class _MarketReview(_TestBase):
    __tablename__ = "market_review_t"
    review_id = Column(BigInteger, primary_key=True)
    entity_type = Column(String(20))
    entity_id = Column(BigInteger)
    tenant_id = Column(String(36))
    user_id = Column(String(64))
    rating = Column(SmallInteger)
    comment = Column(Text)
    status = Column(String(20), default="visible")
    delete_flag = Column(String(1), default="N")
    create_time = Column(TIMESTAMP)
    created_by = Column(String(100))
    updated_by = Column(String(100))


class _MarketRatingSummary(_TestBase):
    __tablename__ = "market_rating_summary_t"
    entity_type = Column(String(20), primary_key=True)
    entity_id = Column(BigInteger, primary_key=True)
    avg_rating = Column(Numeric(3, 2), default=0.00)
    rating_count = Column(Integer, default=0)
    review_count = Column(Integer, default=0)


class _UserTenant(_TestBase):
    __tablename__ = "user_tenant_t"
    user_id = Column(String(64), primary_key=True)
    user_email = Column(String(100))
    delete_flag = Column(String(1), default="N")


class _McpMarketRecord(_TestBase):
    __tablename__ = "mcp_market_record_t"
    market_id = Column(Integer, primary_key=True)
    tags = Column(ARRAY(Text))
    delete_flag = Column(String(1), default="N")
    review_status = Column(String(30), default="not_shared")


# Install mocks in sys.modules so market_db imports use our fake classes
db_models_mock = MagicMock()
db_models_mock.AgentRepository = _AgentRepository
db_models_mock.MarketCategory = _MarketCategory
db_models_mock.MarketTag = _MarketTag
db_models_mock.MarketReview = _MarketReview
db_models_mock.MarketRatingSummary = _MarketRatingSummary
db_models_mock.UserTenant = _UserTenant
db_models_mock.McpMarketRecord = _McpMarketRecord
sys.modules['database.db_models'] = db_models_mock

# Now import the module under test
from backend.database import market_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRow:
    """A lightweight fake ORM row that returns attributes as dict keys."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _make_agent_row(**overrides):
    """Create a fake AgentRepository row with sensible defaults."""
    defaults = dict(
        agent_repository_id=1,
        agent_id=100,
        name="test_agent",
        display_name="Test Agent",
        description="A test agent",
        author="test_author",
        tags=["ai", "chatbot"],
        tool_count=3,
        icon="🤖",
        downloads=50,
        agent_info_json={"agent_id": 100, "agent_info": {}, "mcp_info": []},
        status="shared",
        delete_flag="N",
        source="community",
        is_official_template=False,
        expert_type="agent",
        category_id="1",
        is_featured=False,
        featured_weight=0,
        create_time=datetime(2024, 1, 1, 12, 0, 0),
        update_time=datetime(2024, 1, 2, 12, 0, 0),
    )
    defaults.update(overrides)
    return FakeRow(**defaults)


def _make_category_row(**overrides):
    defaults = dict(
        category_id=1,
        entity_type="agent",
        name="productivity",
        display_name="Productivity",
        display_name_zh="效率工具",
        description="Productivity agents",
        description_zh="效率类智能体",
        icon="⚡",
        sort_order=1,
        is_active=True,
        delete_flag="N",
        create_time=datetime(2024, 1, 1, 12, 0, 0),
    )
    defaults.update(overrides)
    return FakeRow(**defaults)


def _make_tag_row(**overrides):
    defaults = dict(
        tag_id=1,
        name="ai",
        display_name="AI",
        description="Artificial Intelligence",
        delete_flag="N",
        create_time=datetime(2024, 1, 1, 12, 0, 0),
    )
    defaults.update(overrides)
    return FakeRow(**defaults)


def _make_review_row(**overrides):
    defaults = dict(
        review_id=1,
        entity_type="agent",
        entity_id=1,
        tenant_id="tenant_1",
        user_id="user_1",
        rating=5,
        comment="Great agent!",
        status="visible",
        delete_flag="N",
        create_time=datetime(2024, 1, 1, 12, 0, 0),
    )
    defaults.update(overrides)
    return FakeRow(**defaults)


def _make_summary_row(**overrides):
    defaults = dict(
        entity_type="agent",
        entity_id=1,
        avg_rating=4.5,
        rating_count=2,
        review_count=2,
    )
    defaults.update(overrides)
    return FakeRow(**defaults)


def _make_user_tenant_row(**overrides):
    defaults = dict(
        user_id="user_1",
        user_email="test@example.com",
        delete_flag="N",
    )
    defaults.update(overrides)
    return FakeRow(**defaults)


def _make_mock_session_ctx(session):
    """Create a context manager mock that yields the given session.

    get_db_session is used as `with get_db_session() as session:`,
    so the mock must be callable and return a context manager.
    """
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    mock_callable = MagicMock(return_value=mock_ctx)
    return mock_callable


# ---------------------------------------------------------------------------
# Tests: list_market_agents
# ---------------------------------------------------------------------------

class TestListMarketAgents:
    """Tests for market_db.list_market_agents."""

    def test_list_market_agents_basic(self, monkeypatch):
        """Should return items and total with default parameters."""
        session = MagicMock()
        row = _make_agent_row()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        session.query.return_value = mock_query

        # _resolve_category_for_agent also calls session.query — make it return None
        mock_cat_query = MagicMock()
        mock_cat_query.filter.return_value.first.return_value = None
        # session.query is called for AgentRepository and MarketCategory
        # Both return mock_query in the real code, but filter chain differs.
        # Since session.query is called with different model classes,
        # we use side_effect to return different query objects.
        session.query.side_effect = [mock_query, mock_cat_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents()

        assert "items" in result
        assert "total" in result
        assert result["total"] == 1
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["id"] == 1
        assert item["agent_id"] == 100
        assert item["name"] == "test_agent"
        assert item["display_name"] == "Test Agent"
        assert item["description"] == "A test agent"
        assert item["author"] == "test_author"
        assert item["download_count"] == 50
        assert item["tool_count"] == 3
        assert item["is_featured"] is False
        assert item["source"] == "community"
        assert item["is_official_template"] is False

    def test_list_market_agents_pagination(self, monkeypatch):
        """Should apply offset and limit for pagination."""
        session = MagicMock()
        rows = [_make_agent_row(agent_repository_id=i) for i in range(5)]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 10
        mock_query.offset.return_value.limit.return_value.all.return_value = rows
        # Each row also triggers _resolve_category_for_agent → session.query(MarketCategory)
        cat_query = MagicMock()
        cat_query.filter.return_value.first.return_value = None
        session.query.side_effect = [mock_query] + [cat_query] * 5

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents(page=2, page_size=5)

        assert result["total"] == 10
        assert len(result["items"]) == 5
        # Verify offset was called with (2-1)*5 = 5
        mock_query.offset.assert_called_once_with(5)

    def test_list_market_agents_search(self, monkeypatch):
        """Should apply search filter on name/display_name/description/tags."""
        session = MagicMock()
        row = _make_agent_row()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        cat_query = MagicMock()
        cat_query.filter.return_value.first.return_value = None
        session.query.side_effect = [mock_query, cat_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents(search="test")

        assert result["total"] == 1
        # filter should have been called at least twice (base filter + search filter)
        assert mock_query.filter.call_count >= 2

    def test_list_market_agents_category_filter(self, monkeypatch):
        """Should apply category_id filter when category is provided."""
        session = MagicMock()
        row = _make_agent_row()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        cat_query = MagicMock()
        cat_query.filter.return_value.first.return_value = None
        session.query.side_effect = [mock_query, cat_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents(category="productivity")

        assert result["total"] == 1

    def test_list_market_agents_tag_filter(self, monkeypatch):
        """Should apply tag filter when tag is provided."""
        session = MagicMock()
        row = _make_agent_row()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        cat_query = MagicMock()
        cat_query.filter.return_value.first.return_value = None
        session.query.side_effect = [mock_query, cat_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents(tag="ai")

        assert result["total"] == 1

    def test_list_market_agents_sort_popular(self, monkeypatch):
        """Should order by downloads desc when sort=popular."""
        session = MagicMock()
        row = _make_agent_row(downloads=100)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        cat_query = MagicMock()
        cat_query.filter.return_value.first.return_value = None
        session.query.side_effect = [mock_query, cat_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents(sort="popular")

        assert result["items"][0]["download_count"] == 100
        # order_by should have been called
        assert mock_query.order_by.called

    def test_list_market_agents_sort_name(self, monkeypatch):
        """Should order by display_name when sort=name."""
        session = MagicMock()
        row = _make_agent_row()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        cat_query = MagicMock()
        cat_query.filter.return_value.first.return_value = None
        session.query.side_effect = [mock_query, cat_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents(sort="name")

        assert result["items"][0]["display_name"] == "Test Agent"

    def test_list_market_agents_source_filter(self, monkeypatch):
        """Should apply source filter when source is provided."""
        session = MagicMock()
        row = _make_agent_row(source="official")

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        session.query.side_effect = [mock_query, MagicMock(filter_return_value=MagicMock(first_return_value=None))]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents(source="official")

        assert result["items"][0]["source"] == "official"

    def test_list_market_agents_item_format(self, monkeypatch):
        """Items should match the frontend API contract field names."""
        session = MagicMock()
        row = _make_agent_row(tags=["ai", "chatbot"])

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value.limit.return_value.all.return_value = [row]
        session.query.side_effect = [mock_query, MagicMock(filter_return_value=MagicMock(first_return_value=None))]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_market_agents()
        item = result["items"][0]

        # Verify all expected fields exist
        expected_keys = {"id", "agent_id", "name", "display_name", "description",
                        "author", "category", "tags", "download_count",
                        "created_at", "tool_count", "is_featured", "icon",
                        "source", "is_official_template"}
        assert expected_keys.issubset(item.keys())
        # tags should be a list of dicts with id and display_name
        assert isinstance(item["tags"], list)
        assert len(item["tags"]) == 2
        assert "id" in item["tags"][0]
        assert "display_name" in item["tags"][0]


# ---------------------------------------------------------------------------
# Tests: get_market_agent_detail
# ---------------------------------------------------------------------------

class TestGetMarketAgentDetail:
    """Tests for market_db.get_market_agent_detail."""

    def test_get_market_agent_detail_found(self, monkeypatch):
        """Should return a dict (via as_dict) when record exists."""
        record = {"agent_repository_id": 1, "name": "test", "agent_info_json": {}}

        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = record
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))
        monkeypatch.setattr(market_db, "as_dict", lambda obj: obj)

        result = market_db.get_market_agent_detail(1)

        assert result is not None
        assert result["agent_repository_id"] == 1
        assert result["name"] == "test"

    def test_get_market_agent_detail_not_found(self, monkeypatch):
        """Should return None when record does not exist."""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.get_market_agent_detail(999)

        assert result is None


# ---------------------------------------------------------------------------
# Tests: list_featured_agents
# ---------------------------------------------------------------------------

class TestListFeaturedAgents:
    """Tests for market_db.list_featured_agents."""

    def test_list_featured_agents_returns_featured(self, monkeypatch):
        """Should return agents with is_featured=True."""
        session = MagicMock()
        row1 = _make_agent_row(agent_repository_id=1, is_featured=True, downloads=100)
        row2 = _make_agent_row(agent_repository_id=2, is_featured=True, downloads=50)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value.all.return_value = [row1, row2]
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_featured_agents(limit=6)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["is_featured"] is True
        assert result[1]["id"] == 2
        assert result[1]["download_count"] == 50

    def test_list_featured_agents_empty(self, monkeypatch):
        """Should return empty list when no featured agents exist."""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value.all.return_value = []
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_featured_agents()

        assert result == []

    def test_list_featured_agents_format(self, monkeypatch):
        """Featured items should match the expected format."""
        session = MagicMock()
        row = _make_agent_row(agent_repository_id=10, is_featured=True)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value.all.return_value = [row]
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_featured_agents()

        item = result[0]
        expected_keys = {"id", "agent_id", "name", "display_name",
                        "description", "author", "icon", "download_count",
                        "is_featured"}
        assert expected_keys.issubset(item.keys())


# ---------------------------------------------------------------------------
# Tests: list_categories
# ---------------------------------------------------------------------------

class TestListCategories:
    """Tests for market_db.list_categories."""

    def test_list_categories_basic(self, monkeypatch):
        """Should return list of category dicts with expected fields."""
        session = MagicMock()
        cat = _make_category_row()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [cat]
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_categories()

        assert len(result) == 1
        cat_dict = result[0]
        assert cat_dict["id"] == 1
        assert cat_dict["name"] == "productivity"
        assert cat_dict["display_name"] == "Productivity"
        assert cat_dict["display_name_zh"] == "效率工具"
        assert cat_dict["description"] == "Productivity agents"
        assert cat_dict["description_zh"] == "效率类智能体"
        assert cat_dict["icon"] == "⚡"
        assert cat_dict["sort_order"] == 1

    def test_list_categories_with_entity_type_filter(self, monkeypatch):
        """Should filter by entity_type when provided."""
        session = MagicMock()
        cat = _make_category_row(entity_type="agent")

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [cat]
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_categories(entity_type="agent")

        assert len(result) == 1
        # filter called at least twice (delete_flag + is_active + entity_type)
        assert mock_query.filter.call_count >= 2

    def test_list_categories_empty(self, monkeypatch):
        """Should return empty list when no categories exist."""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_categories()

        assert result == []


# ---------------------------------------------------------------------------
# Tests: list_tags
# ---------------------------------------------------------------------------

class TestListTags:
    """Tests for market_db.list_tags."""

    def test_list_tags_returns_tags(self, monkeypatch):
        """Should return a list of tag dicts with id, name, display_name, count."""
        session = MagicMock()

        # Mock the agent tag query
        agent_tag_query = MagicMock()
        agent_tag_row = MagicMock()
        agent_tag_row.tag = "ai"
        agent_tag_row.count = 3
        agent_tag_query.filter.return_value = agent_tag_query
        agent_tag_query.group_by.return_value = agent_tag_query
        agent_tag_query.all.return_value = [agent_tag_row]

        # Mock the mcp tag query
        mcp_tag_query = MagicMock()
        mcp_tag_row = MagicMock()
        mcp_tag_row.tag = "search"
        mcp_tag_row.count = 2
        mcp_tag_query.filter.return_value = mcp_tag_query
        mcp_tag_query.group_by.return_value = mcp_tag_query
        mcp_tag_query.all.return_value = [mcp_tag_row]

        # Mock the defined tags query
        defined_tag_query = MagicMock()
        defined_tag_query.filter.return_value = defined_tag_query
        defined_tag_query.all.return_value = []

        session.query.side_effect = [agent_tag_query, mcp_tag_query, defined_tag_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_tags()

        assert len(result) == 2
        # Tags sorted by count desc
        tag_names = [t["name"] for t in result]
        assert "ai" in tag_names
        assert "search" in tag_names
        ai_tag = next(t for t in result if t["name"] == "ai")
        assert ai_tag["count"] == 3
        assert "id" in ai_tag
        assert "display_name" in ai_tag


# ---------------------------------------------------------------------------
# Tests: create_review
# ---------------------------------------------------------------------------

class TestCreateReview:
    """Tests for market_db.create_review."""

    def test_create_review_new(self, monkeypatch):
        """Should insert a new review and update rating summary."""
        session = MagicMock()

        # existing review query returns None (no existing review)
        existing_query = MagicMock()
        existing_query.filter.return_value = existing_query
        existing_query.first.return_value = None

        # summary query returns None (no existing summary)
        summary_query = MagicMock()
        summary_query.filter.return_value = summary_query
        summary_query.first.return_value = None

        session.query.side_effect = [existing_query, summary_query]

        # Simulate flush assigning a review_id to the newly created MarketReview object
        def _flush_side_effect():
            for args in session.add.call_args_list:
                review_obj = args[0][0]
                if hasattr(review_obj, "review_id"):
                    review_obj.review_id = 42
        session.flush.side_effect = _flush_side_effect

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.create_review(
            entity_type="agent",
            entity_id=1,
            tenant_id="tenant_1",
            user_id="user_1",
            rating=5,
            comment="Excellent!",
        )

        assert result["review_id"] == 42
        assert result["status"] == "visible"
        # session.add should have been called for the new review
        assert session.add.called
        # session.flush should have been called
        assert session.flush.called

    def test_create_review_update_existing(self, monkeypatch):
        """Should update an existing review and adjust rating summary."""
        session = MagicMock()
        existing_review = _make_review_row(rating=3, comment="Old comment")

        existing_query = MagicMock()
        existing_query.filter.return_value = existing_query
        existing_query.first.return_value = existing_review

        # summary query returns an existing summary
        summary_row = _make_summary_row(avg_rating=3.0, rating_count=1, review_count=1)
        summary_query = MagicMock()
        summary_query.filter.return_value = summary_query
        summary_query.first.return_value = summary_row

        session.query.side_effect = [existing_query, summary_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.create_review(
            entity_type="agent",
            entity_id=1,
            tenant_id="tenant_1",
            user_id="user_1",
            rating=5,
            comment="Updated comment!",
        )

        assert result["status"] == "visible"
        # existing review should be updated
        assert existing_review.rating == 5
        assert existing_review.comment == "Updated comment!"
        # session.flush should have been called
        assert session.flush.called


# ---------------------------------------------------------------------------
# Tests: list_reviews
# ---------------------------------------------------------------------------

class TestListReviews:
    """Tests for market_db.list_reviews."""

    def test_list_reviews_basic(self, monkeypatch):
        """Should return summary and reviews list with user_name."""
        session = MagicMock()

        # Summary query
        summary_row = _make_summary_row(avg_rating=4.5, rating_count=2, review_count=2)
        summary_query = MagicMock()
        summary_query.filter.return_value = summary_query
        summary_query.first.return_value = summary_row

        # Reviews query with join
        review = _make_review_row()
        user_tenant = _make_user_tenant_row()
        review_query = MagicMock()
        review_query.outerjoin.return_value = review_query
        review_query.filter.return_value = review_query
        review_query.order_by.return_value = review_query
        review_query.count.return_value = 1
        review_query.offset.return_value.limit.return_value.all.return_value = [
            (review, user_tenant)
        ]

        session.query.side_effect = [summary_query, review_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_reviews(entity_type="agent", entity_id=1)

        assert "summary" in result
        assert "reviews" in result
        assert result["summary"]["average_rating"] == 4.5
        assert result["summary"]["total_reviews"] == 2
        assert len(result["reviews"]) == 1
        rev = result["reviews"][0]
        assert rev["id"] == 1
        assert rev["user_name"] == "test@example.com"
        assert rev["rating"] == 5
        assert rev["content"] == "Great agent!"

    def test_list_reviews_anonymous_user(self, monkeypatch):
        """Should show '匿名用户' when user_tenant is None."""
        session = MagicMock()

        summary_query = MagicMock()
        summary_query.filter.return_value = summary_query
        summary_query.first.return_value = None

        review = _make_review_row()
        review_query = MagicMock()
        review_query.outerjoin.return_value = review_query
        review_query.filter.return_value = review_query
        review_query.order_by.return_value = review_query
        review_query.count.return_value = 1
        review_query.offset.return_value.limit.return_value.all.return_value = [
            (review, None)
        ]

        session.query.side_effect = [summary_query, review_query]

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.list_reviews(entity_type="agent", entity_id=1)

        assert result["reviews"][0]["user_name"] == "匿名用户"
        assert result["summary"]["average_rating"] == 0.0
        assert result["summary"]["total_reviews"] == 0


# ---------------------------------------------------------------------------
# Tests: get_rating_summary
# ---------------------------------------------------------------------------

class TestGetRatingSummary:
    """Tests for market_db.get_rating_summary."""

    def test_get_rating_summary_found(self, monkeypatch):
        """Should return average_rating and total_reviews when summary exists."""
        session = MagicMock()
        summary_row = _make_summary_row(avg_rating=4.5, rating_count=10, review_count=8)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = summary_row
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.get_rating_summary("agent", 1)

        assert result["average_rating"] == 4.5
        assert result["total_reviews"] == 8
        assert result["rating_count"] == 10

    def test_get_rating_summary_not_found(self, monkeypatch):
        """Should return zeros when summary does not exist."""
        session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        session.query.return_value = mock_query

        monkeypatch.setattr(market_db, "get_db_session", _make_session_cm(session))

        result = market_db.get_rating_summary("agent", 999)

        assert result["average_rating"] == 0.0
        assert result["total_reviews"] == 0
        assert result["rating_count"] == 0


# ---------------------------------------------------------------------------
# Tests: _serialize_dt helper
# ---------------------------------------------------------------------------

class TestSerializeDt:
    """Tests for the _serialize_dt internal helper."""

    def test_serialize_naive_datetime(self):
        """Should append 'Z' suffix for naive datetime."""
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = market_db._serialize_dt(dt)
        assert result is not None
        assert result.endswith("Z")

    def test_serialize_none(self):
        """Should return None for None input."""
        assert market_db._serialize_dt(None) is None

    def test_serialize_aware_datetime(self):
        """Should not append 'Z' for timezone-aware datetime."""
        from datetime import timezone
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = market_db._serialize_dt(dt)
        assert result is not None
        assert not result.endswith("Z") or "+" in result


# ---------------------------------------------------------------------------
# Tests: _format_tags helper
# ---------------------------------------------------------------------------

class TestFormatTags:
    """Tests for the _format_tags internal helper."""

    def test_format_tags_basic(self):
        """Should format a list of tag strings into dicts."""
        result = market_db._format_tags(["ai", "chatbot"])
        assert len(result) == 2
        assert result[0]["display_name"] == "ai"
        assert result[1]["display_name"] == "chatbot"
        assert "id" in result[0]

    def test_format_tags_empty(self):
        """Should return empty list for None or empty input."""
        assert market_db._format_tags(None) == []
        assert market_db._format_tags([]) == []

    def test_format_tags_with_empty_string(self):
        """Should skip empty strings in the tags array."""
        result = market_db._format_tags(["ai", "", "chatbot"])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Helper function
# ---------------------------------------------------------------------------

def _make_session_cm(session):
    """Create a callable that returns a context manager yielding the given session.

    get_db_session is used as `with get_db_session() as session:`,
    so the mock must be callable and return a context manager.
    """
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    return MagicMock(return_value=mock_ctx)
