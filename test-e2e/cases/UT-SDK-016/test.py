"""D1 SDK unit contracts. All I/O clients are fakes owned by the test."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import sys
import types
from io import BytesIO

import pytest


STAGE = pytest.mark.stage("D1")


def _data_process_classes():
    """Import focused processors without loading optional OCR/image dependencies."""
    from shared.config import repo_root

    package_name = "nexent.data_process"
    package = types.ModuleType(package_name)
    package.__path__ = [str(repo_root() / "sdk" / "nexent" / "data_process")]
    sys.modules[package_name] = package
    json_module = importlib.import_module(f"{package_name}.json_chunk_processor")
    excel_module = importlib.import_module(f"{package_name}.openpyxl_processor")
    return json_module.JSONChunkProcessor, excel_module.OpenPyxlProcessor


def _reset_skill_manager() -> None:
    from nexent.skills.skill_manager import SkillManager

    SkillManager._instance = None












def _schedule(rule_type, *, start, interval=None, cron=None, max_count=None, zone="UTC"):
    from nexent.scheduler.triggers import ScheduleMode, ScheduleSpec

    return ScheduleSpec(
        mode=ScheduleMode.ONCE if rule_type.value == "AT" else ScheduleMode.RECURRING,
        rule_type=rule_type, timezone=zone, start_at=start,
        interval_seconds=interval, cron_expr=cron, max_fire_count=max_count,
    )










class _FakeStorage:
    def __init__(self, payload: bytes = b"payload"):
        self.payload = payload
        self.uploads: list[tuple[str, str, bytes]] = []

    def get_file_stream(self, object_name, bucket):
        return True, BytesIO(self.payload)

    def upload_fileobj(self, file_obj, object_name, bucket):
        self.uploads.append((bucket, object_name, file_obj.read()))
        return True, f"s3://{bucket}/{object_name}"














@STAGE
@pytest.mark.case_id("UT-SDK-016")
def test_gateway_context_and_final_context_contract() -> None:
    from nexent.core.context_runtime.contracts import ContextEvidence, FinalContext
    from nexent.core.gateway.model_context import EmbeddingContext, LLMContext, ModelContext
    from nexent.core.gateway.modality.rerank.openai import OpenAICompatibleRerankAdapter
    from nexent.core.models.openai_llm import OpenAIModel

    context = LLMContext(
        model_name="m", base_url="http://model", api_key="secret", modality="llm",
        factory="openai", tenant_id="t1", temperature=0.2,
        extra_body={"enable_thinking": False, "provider_option": {"nested": True}},
    )
    assert context.tenant_id == "t1"
    assert context.modality == "llm"
    assert context.model_name == "m"
    assert context.factory == "openai"
    assert context.extra_body == {
        "enable_thinking": False,
        "provider_option": {"nested": True},
    }
    # extra_body is now a base ModelContext contract, not LLM-only.  Verify
    # provider-specific values reach embedding/rerank contexts as well.
    embedding = EmbeddingContext(
        model_name="embedding", base_url="http://model", api_key="secret",
        modality="embedding", factory="openai", extra_body={"dimensions": 1024},
    )
    assert embedding.extra_body == {"dimensions": 1024}
    rerank = OpenAICompatibleRerankAdapter(ModelContext(
        model_name="reranker", base_url="https://dashscope.example/v1/rerank",
        api_key="secret", modality="rerank", factory="openai",
        extra_body={"parameters": {"return_documents": True}, "tenant_hint": "t1"},
    ))
    payload = rerank._prepare_request("query", ["one", "two"], top_n=1)
    assert payload["parameters"] == {"return_documents": True, "top_n": 1}
    assert payload["tenant_hint"] == "t1"
    # Wire translation is provider-specific and must preserve nested custom
    # fields without mutating the caller's object.
    qwen = object.__new__(OpenAIModel)
    qwen.model_id = "qwen3.7-plus"
    qwen.reasoning_capability = None
    qwen.model_factory = "openai"
    qwen.api_base_url = "http://model"
    source = {"enable_thinking": False, "provider_option": {"nested": True}}
    translated = qwen._translate_thinking_flag(source)
    assert translated == {
        "chat_template_kwargs": {"enable_thinking": False},
        "provider_option": {"nested": True},
    }
    assert source["enable_thinking"] is False
    final = FinalContext(messages=[{"role": "user", "content": "hello"}], evidence=ContextEvidence())
    assert final.messages[0]["role"] == "user" and final.tools == []


