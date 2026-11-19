# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Internal run identity and root-only user interaction permissions."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal


RunRole = Literal["root", "subagent"]
_run_role: ContextVar[RunRole] = ContextVar("nexent_run_role", default="root")


def root_clarification_allowed(run_info=None, *, managed_context=False):
    """A nested run cannot promote itself through a copied/default root value."""
    return not managed_context and _run_role.get() == "root" and getattr(run_info, "run_role", "root") == "root"


@contextmanager
def run_identity_scope(role: RunRole):
    """Preserve a child's restrictions across recursive dispatch and restore callers."""
    if role not in {"root", "subagent"}:
        raise ValueError("Invalid internal run role")
    token = _run_role.set("subagent" if _run_role.get() == "subagent" else role)
    try:
        yield
    finally:
        _run_role.reset(token)
