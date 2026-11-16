# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual Agent factory accepts a tenant-owned resolved outlet snapshot."""

from threading import Event

import pytest
from nexent.core.agents.agent_model import ModelConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.model_service.compatibility.invocation_options import (
    LegacyInvocationOptions,
)
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.models.retry import DEFAULT_MODEL_RETRY
from nexent.core.utils.observer import MessageObserver


def agent_for(profile, scope=None):
    agent = NexentAgent.__new__(NexentAgent)
    agent.tenant_id = profile.identity.tenant_id
    agent.stop_event = Event()
    agent.cancellation_scope = scope
    agent.observer = MessageObserver()
    agent.model_config_list = [ModelConfig(
        cite_name='chosen', model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, api_key='controlled-key', resolved_profile=profile,
    )]
    return agent


@pytest.mark.parametrize('provided_scope', [False, True])
def test_agent_factory_uses_resolved_defaults_and_preserves_cancellation_owner(openai_profile, provided_scope):
    scope = RunCancellationScope() if provided_scope else None
    agent = agent_for(openai_profile, scope)
    model = agent.create_model('chosen')
    assert isinstance(model, LegacyChatModel)
    assert model.profile == openai_profile and model.profile is not openai_profile
    assert model.observer is agent.observer and model.service._policy is DEFAULT_MODEL_RETRY
    assert model.stop_event is (scope.stop_event if provided_scope else agent.stop_event)
    if provided_scope:
        assert model.cancellation_scope is scope
    agent.model_config_list[0].temperature = 0.9
    assert model.profile.parameter_values == openai_profile.parameter_values
    model.stop_event.set()
    assert model.cancellation_scope.cancelled


@pytest.mark.parametrize('field,value', [('tenant_id', 'other'), ('model_name', 'other'), ('url', 'https://other.test')])
def test_agent_factory_rejects_mismatched_tenant_model_or_endpoint(openai_profile, field, value):
    agent = agent_for(openai_profile)
    if field == 'tenant_id':
        agent.tenant_id = value
    else:
        setattr(agent.model_config_list[0], field, value)
    with pytest.raises(ValueError, match='outlet snapshot'):
        agent.create_model('chosen')


def test_factory_captures_credentials_before_configuration_object_changes(openai_profile):
    values = openai_profile.model_dump()
    values['bindings']['auth'] = {'ref': 'bearer_token_v1', 'version': 1}
    profile = ResolvedModelProfile.model_validate(values)
    agent = agent_for(profile)
    model = agent.create_model('chosen')
    agent.model_config_list[0].api_key = 'later-key'
    request, _ = model._request([{'role': 'user', 'content': 'hello'}], LegacyInvocationOptions({}), None)
    prepared = model.service._registry.resolve(profile.bindings.adapter).prepare_http_request(request, profile)
    sender = model.service._sender_factory(model.profile).freeze_credentials(prepared)
    assert sender._headers(prepared)['authorization'] == 'Bearer controlled-key'
