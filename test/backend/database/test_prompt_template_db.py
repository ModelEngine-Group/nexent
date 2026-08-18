from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from backend.database import prompt_template_db


def install_session(monkeypatch, session):
    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(prompt_template_db, "get_db_session", fake_session)


def test_upsert_prompt_template_by_id_uses_native_on_conflict(monkeypatch):
    prompt_template = MagicMock()
    result = MagicMock()
    result.scalar_one.return_value = prompt_template
    session = MagicMock()
    session.execute.return_value = result

    install_session(monkeypatch, session)
    monkeypatch.setattr(
        prompt_template_db,
        "filter_property",
        lambda data, _model: dict(data),
    )
    monkeypatch.setattr(
        prompt_template_db,
        "as_dict",
        lambda entity: {"entity": entity},
    )

    returned = prompt_template_db.upsert_prompt_template_by_id(
        template_id=0,
        template_data={
            "template_name": "system_default",
            "template_type": "agent_generate",
            "tenant_id": "",
            "user_id": "",
            "template_content_zh": {"system_prompt": "zh"},
            "template_content_en": {"system_prompt": "en"},
            "created_by": "system",
            "updated_by": "system",
        },
        user_id="system",
    )

    statement = session.execute.call_args.args[0]
    compiled_sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )
    assert "ON CONFLICT (template_id) DO UPDATE SET" in compiled_sql
    assert "SELECT" not in compiled_sql
    assert returned == {"entity": prompt_template}
    result.scalar_one.assert_called_once_with()


def test_create_prompt_template_sets_active_flag(monkeypatch):
    session = MagicMock()
    install_session(monkeypatch, session)
    monkeypatch.setattr(prompt_template_db, "filter_property", lambda data, _model: dict(data))
    monkeypatch.setattr(
        prompt_template_db,
        "as_dict",
        lambda entity: {"delete_flag": entity.delete_flag},
    )

    returned = prompt_template_db.create_prompt_template(
        {
            "template_name": "custom",
            "template_type": "agent_generate",
        }
    )

    assert returned == {"delete_flag": "N"}
    session.add.assert_called_once()
    session.flush.assert_called_once_with()


def test_update_prompt_template_updates_non_null_fields(monkeypatch):
    template = MagicMock()
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = template
    session = MagicMock()
    session.query.return_value = query
    install_session(monkeypatch, session)
    monkeypatch.setattr(
        prompt_template_db,
        "filter_property",
        lambda _data, _model: {"template_name": "renamed", "description": None},
    )
    monkeypatch.setattr(
        prompt_template_db,
        "as_dict",
        lambda entity: {"entity": entity},
    )

    returned = prompt_template_db.update_prompt_template(7, {}, "user-1")

    assert template.template_name == "renamed"
    assert template.updated_by == "user-1"
    assert returned == {"entity": template}
    session.flush.assert_called_once_with()


def test_update_prompt_template_rejects_missing_template(monkeypatch):
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = None
    session = MagicMock()
    session.query.return_value = query
    install_session(monkeypatch, session)

    with pytest.raises(ValueError, match="prompt template not found"):
        prompt_template_db.update_prompt_template(404, {}, "user-1")


def test_delete_prompt_template_returns_affected_rows(monkeypatch):
    result = MagicMock(rowcount=1)
    session = MagicMock()
    session.execute.return_value = result
    install_session(monkeypatch, session)

    assert prompt_template_db.delete_prompt_template(7, "user-1") == 1
    session.execute.assert_called_once()


def test_query_prompt_templates_by_user_returns_dicts(monkeypatch):
    templates = [object(), object()]
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = templates
    session = MagicMock()
    session.query.return_value = query
    install_session(monkeypatch, session)
    monkeypatch.setattr(prompt_template_db, "as_dict", lambda entity: {"entity": entity})

    assert prompt_template_db.query_prompt_templates_by_user("tenant", "user") == [
        {"entity": templates[0]},
        {"entity": templates[1]},
    ]


@pytest.mark.parametrize(
    ("function_name", "arguments"),
    [
        ("get_prompt_template_by_id", (7, "tenant", "user")),
        ("get_prompt_template_by_name", ("name", "tenant", "user")),
    ],
)
def test_owner_scoped_prompt_template_queries(monkeypatch, function_name, arguments):
    template = object()
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = template
    session = MagicMock()
    session.query.return_value = query
    install_session(monkeypatch, session)
    monkeypatch.setattr(prompt_template_db, "as_dict", lambda entity: {"entity": entity})

    function = getattr(prompt_template_db, function_name)
    assert function(*arguments) == {"entity": template}

    query.first.return_value = None
    assert function(*arguments) is None


@pytest.mark.parametrize("include_deleted", [False, True])
def test_get_prompt_template_by_template_id_handles_deleted_filter(monkeypatch, include_deleted):
    template = object()
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = template
    session = MagicMock()
    session.query.return_value = query
    install_session(monkeypatch, session)
    monkeypatch.setattr(prompt_template_db, "as_dict", lambda entity: {"entity": entity})

    returned = prompt_template_db.get_prompt_template_by_template_id(
        7,
        include_deleted=include_deleted,
    )

    assert returned == {"entity": template}
    expected_filter_calls = 1 if include_deleted else 2
    assert query.filter.call_count == expected_filter_calls


def test_query_prompt_template_names_filters_empty_rows(monkeypatch):
    result = MagicMock()
    result.all.return_value = [("first",), (None,), (), ("second",)]
    session = MagicMock()
    session.execute.return_value = result
    install_session(monkeypatch, session)

    assert prompt_template_db.query_prompt_template_names("tenant", "user") == {
        "first",
        "second",
    }
