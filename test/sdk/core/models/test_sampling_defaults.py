# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Omitted and null sampling inherit one SDK default without losing zero."""

from unittest.mock import MagicMock

import pytest
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.models.openai_long_context_model import OpenAILongContextModel


@pytest.mark.parametrize("sampling", [{}, {"temperature": None, "top_p": None}])
@pytest.mark.parametrize("model_type", [OpenAIModel, OpenAILongContextModel])
def test_config_and_openai_constructor_share_sampling_defaults(sampling, model_type):
    config = ModelConfig(cite_name="fixture", model_name="fixture", url="http://fixture.invalid", **sampling)
    model = model_type(observer=MagicMock(), model_id="fixture", api_key="fixture", **sampling)
    assert (config.temperature, config.top_p) == (1.0, 1.0)
    assert (model.temperature, model.top_p) == (1.0, 1.0)


@pytest.mark.parametrize("temperature,top_p", [(0, 0), (2, 1), (0.3, 0.87)])
def test_explicit_sampling_remains_unchanged(temperature, top_p):
    config = ModelConfig(cite_name="fixture", model_name="fixture", url="http://fixture.invalid",
                         temperature=temperature, top_p=top_p)
    model = OpenAIModel(observer=MagicMock(), model_id="fixture", api_key="fixture",
                        temperature=temperature, top_p=top_p)
    assert (config.temperature, config.top_p) == (temperature, top_p)
    assert (model.temperature, model.top_p) == (temperature, top_p)


def test_partial_null_only_inherits_missing_field():
    config = ModelConfig(cite_name="fixture", model_name="fixture", url="http://fixture.invalid",
                         temperature=0, top_p=None)
    model = OpenAIModel(observer=MagicMock(), model_id="fixture", api_key="fixture", temperature=None, top_p=0)
    assert (config.temperature, config.top_p) == (0, 1.0)
    assert (model.temperature, model.top_p) == (1.0, 0)
