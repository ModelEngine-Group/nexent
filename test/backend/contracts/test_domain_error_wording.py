# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The domain-error registry never copies exception text into responses.

CodeQL flagged information exposure through exception messages reaching the
northbound error body. Exception text is untrusted data (SQL fragments, object
paths, stack detail); the client-facing wording must always be the static,
reviewed spec message. These tests pin that contract for every spec that
historically opted into exception-owned wording.
"""

import pytest

from contracts.errors.domain import (
    DOMAIN_ERROR_SPECS,
    domain_error_body,
    domain_error_message,
)
from contracts.errors.exceptions import (
    ForbiddenError,
    LimitExceededError,
    NotFoundException,
    UnauthorizedError,
    ValidationError,
)

LEAKY_TEXT = "SELECT * FROM nexent.conversation_record_t WHERE id=42 -- /var/lib/secret"


@pytest.mark.parametrize(
    "exc",
    [
        ForbiddenError(LEAKY_TEXT),
        NotFoundException(LEAKY_TEXT),
        UnauthorizedError(LEAKY_TEXT),
        ValidationError(LEAKY_TEXT),
        LimitExceededError(LEAKY_TEXT),
    ],
)
def test_exception_text_never_reaches_the_message(exc):
    spec = DOMAIN_ERROR_SPECS[type(exc)]
    assert domain_error_message(exc, spec) == spec.message
    assert LEAKY_TEXT not in domain_error_message(exc, spec)


def test_error_body_carries_static_wording_only():
    body = domain_error_body(NotFoundException(LEAKY_TEXT), "req-1")
    assert body["code"] == "NOT_FOUND"
    assert body["status"] == 404
    assert body["message"] == "Resource not found"
    assert body["requestId"] == "req-1"
    assert LEAKY_TEXT not in str(body)


def test_long_exception_text_also_stays_out():
    body = domain_error_body(ForbiddenError("x" * 5000), "req-2")
    assert body["message"] == "Forbidden"
    assert "xxxx" not in str(body)


def test_unregistered_exception_has_no_body():
    assert domain_error_body(RuntimeError(LEAKY_TEXT), "req-3") is None