"""D1 unit test for system-prompt header identity (UT-BE-AUTO-3B69B045EA9A318F)."""

import inspect
import logging

import pytest

from nexent.core.agents.context import ContextItemType
from utils.context_utils import _build_header_text, build_context_inputs


CASE_ID = "UT-BE-AUTO-3B69B045EA9A318F"

_ZH_HEADING = "### 基本信息"
_EN_HEADING = "### Basic Information"

_TENANT_IDENTITY_PARAMS = ("app_name", "app_description", "user_id")

_SECRET_NEEDLES = ("api_key", "access_key", "password", "secret", "bearer")


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D1")
def test_system_header_is_static_nexent_identity_with_platform_authority(caplog):
    header_params = inspect.signature(_build_header_text).parameters
    assert list(header_params) == ["language"]
    assert header_params["language"].default == "zh"

    build_params = inspect.signature(build_context_inputs).parameters
    for param in _TENANT_IDENTITY_PARAMS:
        assert param not in header_params
        assert param not in build_params

    zh = _build_header_text("zh")
    assert zh.startswith(_ZH_HEADING)
    assert "你是 Nexent" in zh
    assert "Nexent 是一个开源智能体平台" in zh
    assert "[Current time:" in zh

    en = _build_header_text("en")
    assert en.startswith(_EN_HEADING)
    assert "You are Nexent." in en
    assert "Nexent is an open-source agent platform" in en
    assert "[Current time:" in en

    for text in (zh, en):
        for token in _TENANT_IDENTITY_PARAMS:
            assert token not in text

    caplog.set_level(logging.DEBUG)
    inputs = build_context_inputs()

    header_items = [item for item in inputs if item.id == "system:header"]
    assert len(header_items) == 1
    header = header_items[0]

    assert header.type == ContextItemType.SYSTEM
    assert header.priority == 100
    assert header.source == ("agent_prompt:header",)
    assert header.metadata["authority"] == "platform"
    assert header.content["text"] == zh

    tenant_headers = [
        item
        for item in inputs
        if item.id == "system:header" and item.metadata.get("authority") == "tenant"
    ]
    assert tenant_headers == []

    for record in caplog.records:
        message = record.getMessage().lower()
        for needle in _SECRET_NEEDLES:
            assert needle not in message
