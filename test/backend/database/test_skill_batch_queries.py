# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Skill list predicate, relation equivalence and query-count regressions."""

from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import JSON, Column, Table, create_engine, event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import registry, sessionmaker

from management.db.skill import repository as db


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://")
    mappings = registry()
    models = {}
    for name in ("SkillInfo", "SkillToolRelation"):
        original = getattr(db, name)
        columns = [Column(c.name, JSON() if isinstance(c.type, (ARRAY, JSONB)) else c.type.copy(),
                          primary_key=c.primary_key, nullable=True) for c in original.__table__.columns]
        table = Table(original.__tablename__, mappings.metadata, *columns)
        models[name] = type(name, (), {})
        mappings.map_imperatively(models[name], table)
        monkeypatch.setattr(db, name, models[name])
    mappings.metadata.create_all(engine)
    factory = sessionmaker(engine)

    @contextmanager
    def session_scope():
        with factory() as session:
            yield session

    monkeypatch.setattr(db, "get_db_session", session_scope)
    queries = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, sql, params, context, many:
                 queries.append((sql, params)) if sql.lstrip().upper().startswith("SELECT") else None)

    def insert(name, **values):
        with factory.begin() as session:
            session.add(models[name](**values))

    yield insert, queries, session_scope
    mappings.dispose()
    engine.dispose()


@pytest.mark.parametrize("count", [0, 1, 50])
def test_list_matches_single_relation_lookups_with_constant_queries(database, count):
    insert, queries, session_scope = database
    for number in range(1, count + 1):
        insert("SkillInfo", skill_id=number, skill_name=f"skill-{number}", tenant_id="a", delete_flag="N",
               create_time=datetime(2026, 1, 1), skill_tags=[" tag ", None], skill_content="full content",
               config_values={"db": True}, config_schemas=[{"name": "db"}], group_ids="10,20")
    insert("SkillInfo", skill_id=1001, tenant_id="b", delete_flag="N")
    insert("SkillInfo", skill_id=1002, tenant_id="a", delete_flag="Y")
    insert("SkillInfo", skill_id=1003, tenant_id="a", delete_flag=None)
    if count:
        for tool_id, deleted in [(7, "N"), (2, "Y"), (7, None)]:
            insert("SkillToolRelation", skill_id=1, tool_id=tool_id, delete_flag=deleted)
        insert("SkillToolRelation", skill_id=1001, tool_id=99)
    with session_scope() as session:
        expected = {number: db._get_tool_ids(session, number) for number in range(1, count + 1)}
    assert len(queries) == count
    queries.clear()
    result = db.list_skills("a")
    assert [skill["skill_id"] for skill in result] == list(range(count, 0, -1))
    assert {skill["skill_id"]: skill["tool_ids"] for skill in result} == expected
    assert len(queries) == (2 if count else 1)
    if count:
        assert result[-1]["tags"] == ["tag"]
        assert result[-1]["content"] == "full content"
        assert result[-1]["group_ids"] == [10, 20]
        assert result[-1]["config_values"] == {"db": True}
    queries.clear()
    metadata = db.list_skills("a", include_tool_ids=False)
    assert metadata == [{k: v for k, v in row.items() if k != "tool_ids"} for row in result]
    assert len(queries) == 1


def test_batch_only_queries_selected_ids_and_skips_empty(database):
    insert, queries, _ = database
    insert("SkillToolRelation", skill_id=1, tool_id=7)
    insert("SkillToolRelation", skill_id=2, tool_id=8)
    assert db.get_tool_ids_by_skill_ids([1, 3, 1]) == {1: [7], 3: []}
    assert len(queries) == 1
    assert 2 not in queries[0][1]
    queries.clear()
    assert db.get_tool_ids_by_skill_ids([]) == {}
    assert queries == []


def test_database_failures_propagate(monkeypatch):
    def fail():
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(db, "get_db_session", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        db.get_tool_ids_by_skill_ids([1])


@pytest.mark.parametrize("body", [None, "", "中文 skill body\n" * 4096], ids=["null", "empty", "large"])
@pytest.mark.parametrize("include_tool_ids", [False, True])
def test_content_can_be_omitted_in_sql_without_lazy_queries(database, body, include_tool_ids):
    insert, queries, _ = database
    insert("SkillInfo", skill_id=1, skill_name="body-skill", tenant_id="a", delete_flag="N",
           skill_content=body, config_values={"value": 1}, config_schemas=[{"name": "value"}])
    insert("SkillToolRelation", skill_id=1, tool_id=7)
    summary = db.list_skills("a", include_tool_ids=include_tool_ids, include_content=False)
    assert "content" not in summary[0]
    assert len(queries) == (2 if include_tool_ids else 1)
    assert all("skill_content" not in sql for sql, _ in queries)
    queries.clear()
    full = db.list_skills("a", include_tool_ids=include_tool_ids, include_content=True)
    assert full[0]["content"] == (body or "")
    assert "skill_content" in queries[0][0]
    assert summary == [{key: value for key, value in row.items() if key != "content"} for row in full]
    assert db.get_skill_by_id(1, "a")["content"] == (body or "")
