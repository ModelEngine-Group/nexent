# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Storage contracts after removal of the legacy Agent prompt columns."""

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.dialects import postgresql

from database.db_models import AgentInfo


def test_agent_orm_queries_and_writes_use_only_the_unified_prompt():
    columns = AgentInfo.__table__.columns
    assert "prompt" in columns
    assert columns["prompt"].name == "prompt"
    assert "duty_prompt" not in columns
    assert "constraint_prompt" not in columns
    assert "few_shots_prompt" not in columns
    values = {"prompt": "Complete prompt"}
    for statement in (select(AgentInfo), insert(AgentInfo).values(**values), update(AgentInfo).values(**values)):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "prompt" in sql
        assert "duty_prompt" not in sql
        assert "constraint_prompt" not in sql
        assert "few_shots_prompt" not in sql
    agent = AgentInfo(**values)
    assert agent.prompt == "Complete prompt"


@pytest.mark.parametrize("legacy", ["duty_prompt", "constraint_prompt", "few_shots_prompt"])
def test_removed_fields_are_not_valid_orm_constructor_arguments(legacy):
    with pytest.raises(TypeError, match=legacy):
        AgentInfo(**{legacy: "Legacy section"})
