# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from contracts.models import ToolValidateRequest
from pydantic import ValidationError


@pytest.mark.parametrize("language", ["zh", "en"])
def test_tool_validation_accepts_frontend_language(language):
    request = ToolValidateRequest(name="deepseek_search", source="local", language=language, inputs={"query": "topic"})
    assert request.language == language
    assert request.inputs == {"query": "topic"}


def test_existing_validation_request_defaults_to_chinese():
    assert ToolValidateRequest(name="tavily_search", source="local").language == "zh"


@pytest.mark.parametrize("language", ["fr", "zh-CN", "", None, 1])
def test_invalid_language_is_rejected_at_request_boundary(language):
    with pytest.raises(ValidationError):
        ToolValidateRequest(name="deepseek_search", source="local", language=language)
