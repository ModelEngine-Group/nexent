"""D2 contract test for KNOWLEDGE_DELETE_BLOCKED (060109) error code and HTTP 409 mapping consistency between backend and frontend."""

from __future__ import annotations

import re

import pytest

from shared.config import repo_root

from consts.error_code import ERROR_CODE_HTTP_STATUS, ErrorCode
from consts.error_message import ErrorMessage
from consts.exceptions import AppException

CASE_ID = "API-AUTO-6A4110F4BD10BA0F"
EXPECTED_CODE = "060109"
EXPECTED_HTTP_STATUS = 409
EXPECTED_MESSAGE = "Knowledge base deletion is blocked while files are being processed."

SECRET_PATTERN = re.compile(r"(?i)\b(api[_-]?key|access[_-]?key|password|secret|token)\b\s*[:=]")


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
def test_knowledge_delete_blocked_error_contract():
    backend_code = ErrorCode.KNOWLEDGE_DELETE_BLOCKED.value
    assert isinstance(backend_code, str)
    assert len(backend_code) == 6
    assert backend_code == EXPECTED_CODE

    assert list(ERROR_CODE_HTTP_STATUS.keys()).count(ErrorCode.KNOWLEDGE_DELETE_BLOCKED) == 1
    assert ERROR_CODE_HTTP_STATUS[ErrorCode.KNOWLEDGE_DELETE_BLOCKED] == EXPECTED_HTTP_STATUS

    message = ErrorMessage.get_message(ErrorCode.KNOWLEDGE_DELETE_BLOCKED)
    assert message == EXPECTED_MESSAGE

    exception = AppException(ErrorCode.KNOWLEDGE_DELETE_BLOCKED)
    assert exception.http_status == EXPECTED_HTTP_STATUS
    assert exception.http_status != 500

    frontend_path = repo_root() / "frontend" / "const" / "errorCode.ts"
    content = frontend_path.read_text(encoding="utf-8")
    match = re.search(r'\bKNOWLEDGE_DELETE_BLOCKED\s*:\s*"(\d+)"', content)
    assert match is not None, "frontend ErrorCode.KNOWLEDGE_DELETE_BLOCKED constant not found"
    frontend_code = match.group(1)

    assert frontend_code == backend_code == EXPECTED_CODE
    assert len(re.findall(r'\bKNOWLEDGE_DELETE_BLOCKED\s*:', content)) == 1
    assert content.count(f'"{EXPECTED_CODE}"') == 1

    assert not SECRET_PATTERN.search(message)
    assert not SECRET_PATTERN.search(content)
