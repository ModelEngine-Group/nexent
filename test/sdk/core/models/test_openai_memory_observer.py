# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import pytest

from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver


def test_openai_models_default_to_independent_observers():
    first = OpenAIModel(model_id="test", api_base="http://localhost", api_key="test")
    second = OpenAIModel(model_id="test", api_base="http://localhost", api_key="test")
    assert isinstance(first.observer, MessageObserver)
    assert first.observer is not second.observer
    assert first.temperature is None
    assert first.top_p is None
    first.observer.begin_model_attempt("test", 1)


@pytest.mark.parametrize("temperature,top_p", [(None, None), (0.0, 0.8)])
def test_openai_model_preserves_supplied_observer(temperature, top_p):
    observer = MessageObserver()
    model = OpenAIModel(
        observer=observer, temperature=temperature, top_p=top_p,
        model_id="test", api_base="http://localhost", api_key="test",
    )
    assert model.observer is observer
    assert model.temperature == temperature
    assert model.top_p == top_p


def test_openai_model_creates_default_for_explicit_none():
    model = OpenAIModel(observer=None, model_id="test", api_base="http://localhost", api_key="test")
    assert isinstance(model.observer, MessageObserver)


def test_openai_model_rejects_observer_class_during_construction():
    with pytest.raises(TypeError, match="observer must be an instance"):
        OpenAIModel(observer=MessageObserver, model_id="test", api_base="http://localhost", api_key="test")
