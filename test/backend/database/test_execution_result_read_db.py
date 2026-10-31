# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped persisted execution reads reject missing, ambiguous and malformed units."""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from management.db.conversation import repository as db


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(db, 'get_db_session', sessions)
    return value


def read():
    return db.load_execution_result_content('owner', 'tenant', 1, 10, 3)


def test_ac010_ac016_scoped_query_returns_original_instead_of_summary(session):
    session.execute.return_value.scalars.return_value.all.return_value = [
        json.dumps({'content': '<STDOUT>*** safe text</STDOUT>', 'summary': 'facts'}),
    ]
    assert read() == '<STDOUT>*** safe text</STDOUT>'
    statement = session.execute.call_args.args[0]
    query = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    for expected in ["created_by = 'owner'", "tenant_id = 'tenant'", "user_id = 'owner'",
                     'conversation_record_t.conversation_id = 1', 'conversation_message_t.message_id = 10',
                     'conversation_message_unit_t.conversation_id = 1', 'unit_index = 3',
                     "unit_type = 'execution_result'", 'EXISTS']:
        assert expected in query
    assert query.count("delete_flag = 'N'") == 4


@pytest.mark.parametrize('rows,exception', [
    ([], PermissionError),
    (['{}', '{}'], ValueError),
    (['[]'], ValueError),
    (['{"content": null}'], ValueError),
    (['not-json'], ValueError),
])
def test_ac010_missing_ambiguous_or_invalid_record_is_not_read(rows, exception, session):
    session.execute.return_value.scalars.return_value.all.return_value = rows
    with pytest.raises(exception):
        read()
