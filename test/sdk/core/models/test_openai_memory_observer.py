# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver


def test_openai_models_default_to_independent_observers():
    first = OpenAIModel(model_id="test", api_base="http://localhost", api_key="test")
    second = OpenAIModel(model_id="test", api_base="http://localhost", api_key="test")
    assert isinstance(first.observer, MessageObserver)
    assert first.observer is not second.observer
    first.observer.begin_model_attempt("test", 1)


def test_openai_model_preserves_supplied_observer():
    observer = MessageObserver()
    model = OpenAIModel(observer=observer, model_id="test", api_base="http://localhost", api_key="test")
    assert model.observer is observer
