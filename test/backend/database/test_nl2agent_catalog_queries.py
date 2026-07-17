"""Focused database-boundary tests for bounded NL2AGENT catalogs."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.database import skill_db, tool_db


@contextmanager
def _session_context(session):
    yield session


def test_skill_catalog_projection_uses_one_bounded_query(monkeypatch):
    query = MagicMock()
    for method_name in ("filter", "order_by", "limit"):
        getattr(query, method_name).return_value = query
    query.all.return_value = [
        SimpleNamespace(
            skill_id=7,
            skill_name="brief-writer",
            skill_description="Write briefs",
            skill_tags=["writing"],
        )
    ]
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        skill_db,
        "get_db_session",
        lambda: _session_context(session),
    )
    relation_lookup = MagicMock()
    monkeypatch.setattr(skill_db, "_get_tool_ids", relation_lookup)

    result = skill_db.list_skills_for_catalog("tenant-a", limit=2_000)

    assert result == [
        {
            "skill_id": 7,
            "name": "brief-writer",
            "description": "Write briefs",
            "tags": ["writing"],
        }
    ]
    session.query.assert_called_once()
    query.limit.assert_called_once_with(2_000)
    relation_lookup.assert_not_called()


def test_tool_catalog_query_applies_requested_limit(monkeypatch):
    query = MagicMock()
    query.filter.return_value = query
    query.limit.return_value = query
    query.all.return_value = [SimpleNamespace(tool_id=1)]
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(
        tool_db,
        "get_db_session",
        lambda: _session_context(session),
    )
    monkeypatch.setattr(tool_db, "as_dict", lambda value: vars(value))

    assert tool_db.query_all_tools("tenant-a", limit=2_000) == [{"tool_id": 1}]
    query.limit.assert_called_once_with(2_000)
