# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing long-text entry points use the saved outlet sender."""

import pytest
from nexent.core.gateway.modality.llm.openai import OpenAILongContextLLMAdapter
from nexent.core.gateway.model_context import LongContextLLMContext
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel


def context(profile, context_type, modality):
    return context_type(model_name=profile.identity.request_model_id, base_url=profile.connection.base_url,
        api_key="controlled-key", tenant_id=profile.identity.tenant_id, modality=modality,
        factory="openai", resolved_profile=profile)


def test_long_text_preserves_preparation_and_calls_same_model(openai_profile, mocker):
    adapter = OpenAILongContextLLMAdapter(context(openai_profile, LongContextLLMContext, "llm_long_context"))
    adapter._build_model()
    assert isinstance(adapter._model, LegacyChatModel)
    assert adapter.max_context_tokens == openai_profile.capabilities.context.combined_window
    mocker.patch.object(adapter, "_get_tokenizer", return_value=None)
    generate = mocker.patch.object(adapter._model, "generate", return_value="answer")
    result, percent = adapter.analyze_long_text("text", "system", "analyze")
    assert (result, percent) == ("answer", "100")
    assert generate.call_args.args[0] == [
        {"role": "system", "content": "system"}, {"role": "user", "content": "analyze\n\ntext"},
    ]


def test_long_text_missing_capacity_does_not_guess_legacy_limit(openai_profile):
    data = openai_profile.model_dump()
    data["capabilities"]["context"]["combined_window"] = None
    data["capabilities"]["context"]["input_limit"] = None
    profile = openai_profile.__class__.model_validate(data)
    ctx = context(profile, LongContextLLMContext, "llm_long_context")
    ctx.max_tokens = 128000
    with pytest.raises(ValueError, match="positive integer"):
        OpenAILongContextLLMAdapter(ctx)._build_model()


def test_long_text_insufficient_capacity_fails_before_model(openai_profile, mocker):
    adapter = OpenAILongContextLLMAdapter(context(openai_profile, LongContextLLMContext, "llm_long_context"))
    adapter._build_model()
    adapter.max_context_tokens = 1
    mocker.patch.object(adapter, "_get_tokenizer", return_value=None)
    generate = mocker.patch.object(adapter._model, "generate")
    with pytest.raises(ValueError, match="Insufficient tokens"):
        adapter.analyze_long_text("text", "system", "analyze")
    generate.assert_not_called()
