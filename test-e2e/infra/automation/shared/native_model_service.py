# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compose real-model acceptance outlets through develop's registered profiles."""

from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.profiles.composition import compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_resolution import (
    construct_resolved_model_profile,
)
from nexent.core.model_service.profiles.parameter_rules import (
    overlay_profile_parameters,
)
from nexent.core.model_service.profiles.protocol_parameters import (
    openai_chat_parameter_rules,
)
from nexent.core.model_service.profiles.resolved_profile import (
    ConnectionRules,
    ContextConfiguration,
    OutletConnection,
)
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references

MODEL_KEYS = {'qwen3.8-flash':'alibaba/qwen3.8-flash', 'glm-5.3':'zhipuai/glm-5.3',
              'deepseek-v4.1-flash':'deepseek/deepseek-v4.1-flash', 'MiniMax-M3':'minimax/MiniMax-M3'}


def create_service_model(*, model_id, api_base, api_key, observer=None, cancellation_scope=None,
                         max_output_tokens=2048, timeout_seconds=60, concurrency_limit=1,
                         model_profile_key=None, provider_key='tokenpony', enable_thinking=False, **kwargs):
    catalog = load_profile_catalog()
    refs = model_service_references()
    bindings = {key: values[0].model_dump() for key, values in refs.items() if key != 'parameter_transform'}
    bindings['auth'] = {'ref':'bearer_token_v1','version':1}
    policy = compose_provider_model_policy(
        catalog, provider_key=provider_key, request_model_id=model_id,
        model_profile_key=model_profile_key or MODEL_KEYS[model_id], base_bindings=bindings,
        base_instruction=VersionedReference(ref='system_only_v1',version=1), registered_references=refs,
        submitted_values={}, protocol_parameter_rules=openai_chat_parameter_rules(),
    )
    profile = construct_resolved_model_profile(
        policy, catalog, tenant_id='native-acceptance', display_name=model_id, model_type='llm',
        provider_id=provider_key or 'custom',
        connection=OutletConnection(base_url=api_base, ssl_verify=True, timeout_seconds=timeout_seconds,
                                    concurrency_limit=concurrency_limit,
                                    credential_ref={'kind':'model_record','model_id':None}),
        connection_rules=ConnectionRules(credential_kind='model_record',relative_path='chat/completions',
                                         method='POST',headers={}),
        context_configuration=ContextConfiguration(output_reserve_tokens=None,tokenizer_family=None,
                                                   capacity_source='profile',capability_profile_version=None),
        registered_references=refs,
    )
    declared = {rule['key'] for rule in profile.parameter_rules}
    values = {key:max_output_tokens for key in ['max_tokens'] if key in declared}
    if 'max_output_tokens' in declared and not values:
        values['max_output_tokens'] = max_output_tokens
    if enable_thinking and profile.capabilities.reasoning.status == 'supported' and 'enable_thinking' in declared:
        values['enable_thinking'] = True
    if values:
        profile = overlay_profile_parameters(profile,values,scope='outlet')
    return LegacyChatModel.from_profile(profile, api_key, observer=observer,cancellation_scope=cancellation_scope)
