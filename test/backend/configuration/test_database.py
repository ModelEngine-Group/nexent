# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Transaction ownership for the shared configuration database."""

from unittest.mock import Mock

import pytest


def test_session_commits_and_closes_on_success():
    from management.configuration.database import ConfigurationDatabase

    session = Mock()
    database = ConfigurationDatabase(session_factory=lambda: session)

    with database.session() as current:
        assert current is session

    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()


def test_session_rolls_back_without_logging_connection_secrets(caplog):
    from management.configuration.database import ConfigurationDatabase

    session = Mock()
    database = ConfigurationDatabase(session_factory=lambda: session)

    with pytest.raises(RuntimeError, match="failed"), database.session():
        raise RuntimeError("failed at postgres://user:secret@example.invalid")

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    assert "secret" not in caplog.text
    assert "example.invalid" not in caplog.text


def test_lazy_engine_creation_and_dispose(mocker):
    from management.configuration.database import ConfigurationDatabase

    session = Mock()
    engine = Mock()
    session_factory = Mock(return_value=session)
    create_engine = mocker.patch(
        "management.configuration.database.create_engine",
        return_value=engine,
    )
    sessionmaker = mocker.patch(
        "management.configuration.database.sessionmaker",
        return_value=session_factory,
    )
    database = ConfigurationDatabase()
    database.dispose()

    with database.session():
        pass
    database.dispose()
    database.dispose()

    create_engine.assert_called_once()
    sessionmaker.assert_called_once_with(bind=engine)
    session.commit.assert_called_once_with()
    session.close.assert_called_once_with()
    engine.dispose.assert_called_once_with()
    assert database._engine is None
    assert database._session_factory is None
