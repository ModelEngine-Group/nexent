# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Repository-owned transactions shared by existing CRUD collaborators."""

import hashlib
import inspect
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

logger = logging.getLogger(__name__)
_session = ContextVar("repository_session", default=None)
_callbacks = ContextVar("repository_after_commit", default=None)


def current_repository_session():
    return _session.get()


@contextmanager
def repository_unit_of_work():
    """Commit once; deliver queued notifications only after the owner commits."""
    if _session.get() is not None:
        yield _session.get()
        return
    from management.db.client import get_db_session

    pending = []
    with get_db_session() as session:
        session_token = _session.set(session)
        callback_token = _callbacks.set(pending)
        try:
            yield session
        finally:
            _session.reset(session_token)
            _callbacks.reset(callback_token)
    for callback, args, kwargs in pending:
        try:
            callback(*args, **kwargs)
        except Exception:
            logger.exception("Repository committed, but a notification failed")


def repository_transaction(operation):
    if inspect.iscoroutinefunction(operation):
        @wraps(operation)
        async def asynchronous(*args, **kwargs):
            with repository_unit_of_work():
                return await operation(*args, **kwargs)
        return asynchronous

    @wraps(operation)
    def synchronous(*args, **kwargs):
        with repository_unit_of_work():
            return operation(*args, **kwargs)
    return synchronous


def after_repository_commit(operation):
    @wraps(operation)
    def wrapped(*args, **kwargs):
        pending = _callbacks.get()
        if pending is not None:
            pending.append((operation, args, kwargs))
            return None
        return operation(*args, **kwargs)
    return wrapped


def lock_repository_source(session, resource_type: str, tenant_id: str, source_id) -> None:
    """Serialize peer-listing changes even when no listing exists yet."""
    if _session.get() is None:
        return
    from sqlalchemy import func, select

    raw = f"{resource_type}:{tenant_id}:{source_id}".encode()
    key = int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big", signed=True)
    session.execute(select(func.pg_advisory_xact_lock(key)))
