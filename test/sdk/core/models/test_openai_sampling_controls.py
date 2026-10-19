# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit sampling reaches the provider unchanged and cannot silently fall back."""

from unittest.mock import MagicMock, patch

import pytest

from nexent.core.models.openai_llm import OpenAIModel, SamplingConfigurationError


class ProviderBadRequest(Exception):
    pass


@pytest.fixture
def model():
    return OpenAIModel(observer=MagicMock(), model_id='fixture', api_key='fixture', api_base='http://fixture.invalid',
                       explicit_sampling=['temperature'])


def test_unset_sampling_is_omitted_and_explicit_zero_beats_custom_body(model):
    create = MagicMock(); model.client.chat.completions.create = create
    model._dispatch_chat_completion(messages=[], temperature=0, top_p=None, extra_body={'temperature': 1, 'custom': 7})
    sent = create.call_args.kwargs
    assert sent['temperature'] == 0 and 'top_p' not in sent
    assert sent['extra_body'] == {'custom': 7}


def test_explicit_provider_sampling_error_is_not_retried(model):
    create = MagicMock(side_effect=ProviderBadRequest('temperature is unsupported'))
    model.client.chat.completions.create = create
    with patch('nexent.core.models.openai_llm._bad_request_error_type', return_value=ProviderBadRequest):
        with pytest.raises(SamplingConfigurationError, match='restore defaults'):
            model._dispatch_chat_completion(messages=[], temperature=0.2, top_p=0.9)
    assert create.call_count == 1


def test_legacy_inherited_sampling_keeps_existing_compatibility_retry(model):
    model.explicit_sampling=()
    create=MagicMock(side_effect=[ProviderBadRequest('top_p is unsupported'),object()])
    model.client.chat.completions.create=create
    with patch('nexent.core.models.openai_llm._bad_request_error_type', return_value=ProviderBadRequest):
        model._dispatch_chat_completion(messages=[],temperature=0.2,top_p=0.9,stream=True)
    assert create.call_count==2
    assert 'temperature' not in create.call_args.kwargs and 'top_p' not in create.call_args.kwargs
    assert create.call_args.kwargs['stream'] is True
