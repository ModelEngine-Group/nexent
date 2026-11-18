# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lazy process-local database ownership for system configuration."""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from contracts.constants.environment import (
    NEXENT_POSTGRES_PASSWORD,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

CONFIGURATION_CONNECT_TIMEOUT_SECONDS = 5
CONFIGURATION_STATEMENT_TIMEOUT_MS = 15_000
CONFIGURATION_LOCK_TIMEOUT_MS = 5_000


class ConfigurationDatabase:
    """Create connections lazily and own their commit, rollback and disposal."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory
        self._engine = None
        self._lock = threading.Lock()

    def _get_session_factory(self) -> Callable[[], Session]:
        if self._session_factory is None:
            with self._lock:
                if self._session_factory is None:
                    self._engine = create_engine(
                        "postgresql://",
                        connect_args={
                            "host": POSTGRES_HOST,
                            "user": POSTGRES_USER,
                            "password": NEXENT_POSTGRES_PASSWORD,
                            "database": POSTGRES_DB,
                            "port": POSTGRES_PORT,
                            "client_encoding": "utf8",
                            "connect_timeout": CONFIGURATION_CONNECT_TIMEOUT_SECONDS,
                            "options": (
                                "-c "
                                f"statement_timeout={CONFIGURATION_STATEMENT_TIMEOUT_MS} "
                                f"-c lock_timeout={CONFIGURATION_LOCK_TIMEOUT_MS}"
                            ),
                        },
                        hide_parameters=True,
                        pool_pre_ping=True,
                        pool_timeout=30,
                    )
                    self._session_factory = sessionmaker(bind=self._engine)
        return self._session_factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._get_session_factory()()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            logger.error("System configuration database transaction failed")
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None


configuration_database = ConfigurationDatabase()
