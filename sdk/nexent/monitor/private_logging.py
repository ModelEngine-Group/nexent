# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep private evaluation content out of normal service logs."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar


private_evaluation_active: ContextVar[bool] = ContextVar("private_evaluation_active", default=False)


@contextmanager
def private_evaluation_logging(enabled: bool):
    if not enabled:
        yield
        return
    token = private_evaluation_active.set(True)
    try:
        yield
    finally:
        private_evaluation_active.reset(token)


class PrivateEvaluationLogFilter(logging.Filter):
    def filter(self, record):
        return not private_evaluation_active.get()
