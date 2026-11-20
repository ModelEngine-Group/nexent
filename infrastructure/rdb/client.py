# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional

import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contracts.constants.environment import NEXENT_POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER


logger = logging.getLogger("infrastructure.rdb.client")

# Session bound by an outer transaction owner. get_db_session() joins it when
# called without an explicit session; the binding lives here so the
# infrastructure layer never depends on higher-level transaction helpers.
_ambient_session: ContextVar[Optional[Any]] = ContextVar("rdb_ambient_session", default=None)


def current_ambient_session():
    """Return the ambient session bound by an outer transaction owner, if any."""
    return _ambient_session.get()


@contextmanager
def bound_ambient_session(session):
    """Bind a session as ambient so nested get_db_session() calls join it."""
    token = _ambient_session.set(session)
    try:
        yield session
    finally:
        _ambient_session.reset(token)


class PostgresClient:
    _instance: Optional["PostgresClient"] = None
    _conn: Optional[psycopg2.extensions.connection] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PostgresClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.host = POSTGRES_HOST
        self.user = POSTGRES_USER
        self.password = NEXENT_POSTGRES_PASSWORD
        self.database = POSTGRES_DB
        self.port = POSTGRES_PORT
        self.engine = create_engine(
            "postgresql://",
            connect_args={
                "host": self.host,
                "user": self.user,
                "password": self.password,
                "database": self.database,
                "port": self.port,
                "client_encoding": "utf8",
            },
            echo=False,
            hide_parameters=True,
            pool_size=10,
            pool_pre_ping=True,
            pool_timeout=30,
        )
        self.session_maker = sessionmaker(bind=self.engine)

    @staticmethod
    def clean_string_values(data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all strings are UTF-8 encoded"""
        cleaned_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                cleaned_data[key] = value.encode("utf-8", errors="ignore").decode("utf-8")
            else:
                cleaned_data[key] = value
        return cleaned_data


db_client = PostgresClient()


@contextmanager
def get_db_session(db_session=None):
    """
    param db_session: Optional session to use, if None, a new session will be
    created, or the ambient session bound by an outer transaction owner is
    joined. Provide a transactional scope around a series of operations.
    """
    shared_session = db_session if db_session is not None else current_ambient_session()
    owns_session = shared_session is None
    session = db_client.session_maker() if owns_session else shared_session
    try:
        yield session
        if owns_session:
            session.commit()
    except Exception as e:
        if owns_session:
            session.rollback()
        # SQL exception text may contain credential parameters from identity lookup.
        logger.error("Database operation failed (%s)", type(e).__name__)
        raise e
    finally:
        if owns_session:
            session.close()


# ---------------------------------------------------------------------------
# Monitoring-specific, isolated engine and session management
# ---------------------------------------------------------------------------
# Internal engine and session maker for monitoring data, isolated from main pool
_monitoring_engine = None
_monitoring_session_maker = None


def _get_monitoring_engine():
    global _monitoring_engine, _monitoring_session_maker
    if _monitoring_engine is None:
        _monitoring_engine = create_engine(
            "postgresql://",
            connect_args={
                "host": POSTGRES_HOST,
                "user": POSTGRES_USER,
                "password": NEXENT_POSTGRES_PASSWORD,
                "database": POSTGRES_DB,
                "port": POSTGRES_PORT,
                "client_encoding": "utf8",
            },
            echo=False,
            hide_parameters=True,
            pool_size=3,
            pool_pre_ping=True,
            pool_timeout=30,
        )
        _monitoring_session_maker = sessionmaker(bind=_monitoring_engine)
    return _monitoring_engine


@contextmanager
def get_monitoring_db_session(db_session=None):
    _get_monitoring_engine()
    session = _monitoring_session_maker() if db_session is None else db_session
    try:
        yield session
        if db_session is None:
            session.commit()
    except Exception as e:
        if db_session is None:
            session.rollback()
        logger.error(f"Monitoring database operation failed: {str(e)}")
        raise
    finally:
        if db_session is None:
            session.close()
