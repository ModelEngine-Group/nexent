"""D1 unit test for system-prompt header identity (UT-BE-AUTO-3B69B045EA9A318F)."""

import inspect
import logging

import pytest

from nexent.core.agents.context import ContextItemType
from nexent.core.agents.prompt import AgentPromptBundle
from utils.context_utils import build_context_inputs


CASE_ID = "UT-BE-AUTO-3B69B045EA9A318F"

_ZH_HEADING = "### 平台身份"
_EN_HEADING = "### Platform Identity"

_TENANT_IDENTITY_PARAMS = ("app_name", "app_description", "user_id")

_SECRET_NEEDLES = ("api_key", "access_key", "password", "secret", "bearer")


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D1")
def test_system_header_is_static_nexent_identity_with_platform_authority(caplog):
    build_params = inspect.signature(build_context_inputs).parameters
    for param in _TENANT_IDENTITY_PARAMS:
        assert param not in build_params
    caplog.set_level(logging.DEBUG)
    for language, heading, identity, description in (
        ("zh", _ZH_HEADING, "你是 Nexent", "Nexent 是一个开源智能体平台"),
        ("en", _EN_HEADING, "You are Nexent.", "Nexent is an open-source agent platform"),
    ):
        bundle = AgentPromptBundle.from_resource(role="manager", language=language)
        inputs = build_context_inputs(language=language, prompt_bundle=bundle)
        header_items = [item for item in inputs if item.id == "system:header"]
        assert len(header_items) == 1
        header = header_items[0]
        text = header.content["text"]
        assert heading in text
        assert identity in text
        assert description in text
        assert ("[当前时间:" if language == "zh" else "[Current time:") in text
        for token in _TENANT_IDENTITY_PARAMS:
            assert token not in text
        assert header.type == ContextItemType.SYSTEM
        assert header.priority == 100
        assert header.source == ("agent_prompt:header",)
        assert header.metadata["authority"] == "platform"
        assert not any(item.id == "system:header" and item.metadata.get("authority") == "tenant"
                       for item in inputs)

    for record in caplog.records:
        message = record.getMessage().lower()
        for needle in _SECRET_NEEDLES:
            assert needle not in message
