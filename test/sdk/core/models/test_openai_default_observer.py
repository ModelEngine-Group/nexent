# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PR4249 AC-001/002: real wrapper/observer collaboration, mocked provider only."""

from types import SimpleNamespace

from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver


def make_model(**kwargs):
    return OpenAIModel(model_id="test-model", api_base="http://localhost:1/v1",
                       api_key="test-only", **kwargs)


def test_ac001_default_observers_are_instances_and_do_not_share_state():
    first, second = make_model(), make_model()
    assert isinstance(first.observer, MessageObserver)
    assert first.observer is not second.observer
    first.observer.begin_model_attempt("first-attempt", 1)
    assert first.observer.message_query
    assert second.observer.message_query == []


def test_ac001_model_without_explicit_observer_completes_provider_stream(monkeypatch):
    model = make_model(stream=False)
    chunk = SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content="<summary>## Preferences\n\n- Chinese</summary>",
                              role="assistant", reasoning_content=None, tool_calls=None),
        finish_reason="stop")], usage=None)
    calls = []

    def provider(**kwargs):
        calls.append(kwargs)
        return iter([chunk])

    monkeypatch.setattr(model, "_dispatch_chat_completion", provider)
    result = model([{"role": "user", "content": "Summarize confirmed preferences."}])
    assert result.content == "<summary>## Preferences\n\n- Chinese</summary>"
    assert len(calls) == 1
    assert model.last_attempt_number == 1


def test_ac002_explicit_observer_identity_and_legacy_class_argument():
    observer = MessageObserver()
    assert make_model(observer=observer).observer is observer
    assert isinstance(make_model(observer=MessageObserver).observer, MessageObserver)
