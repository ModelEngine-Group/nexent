# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Strict sampling contracts, inheritance and root isolation."""

import pytest
from pydantic import ValidationError
from nexent.core.agents.agent_model import ModelConfig

from consts.model import WorkbenchGenerationConfig, RuntimeGenerationOverrides, NL2SkillRunRequest
from consts.exceptions import RunModelControlsError
from management.services.model.run_controls import overlay_root_model
from management.services.agent.stream import sampling_configuration_error_payload, safe_agent_stream_error_chunk


@pytest.mark.parametrize('config_type', [WorkbenchGenerationConfig, RuntimeGenerationOverrides])
@pytest.mark.parametrize('field,maximum', [('temperature', 2), ('top_p', 1)])
def test_sampling_presence_bounds_and_zero(config_type, field, maximum):
    assert field not in config_type().model_dump(exclude_unset=True)
    for value in [0, 0.7, maximum]:
        assert config_type(**{field: value}).model_dump(exclude_unset=True)[field] == value
    assert config_type(**{field: None}).model_dump(exclude_unset=True)[field] is None
    for invalid in [-0.1, maximum + 0.1, True, '0.7', float('nan'), float('inf')]:
        with pytest.raises(ValidationError):
            config_type(**{field: invalid})


def test_creator_sampling_snapshot_has_one_authority():
    snapshot = {'model_id': 2, 'generation_config': {'temperature': 0, 'top_p': 0.9}}
    request = NL2SkillRunRequest(query='fixture', workbench_config=snapshot)
    assert request.generation_config.model_dump(exclude_unset=True) == snapshot['generation_config']
    for key in ['temperature', 'top_p']:
        with pytest.raises(ValidationError, match='conflicting'):
            NL2SkillRunRequest(query='fixture', workbench_config=snapshot, generation_config={key: 0.5})
    with pytest.raises(ValidationError, match='conflicting'):
        NL2SkillRunRequest(query='fixture', workbench_config={'generation_config': {'temperature': None}},
                          generation_config={'temperature': 0.5})


def test_sampling_override_is_root_only_and_preserves_other_defaults():
    base = ModelConfig(cite_name='root',model_name='fixture',url='http://fixture.invalid',temperature=0.7,top_p=0.9,
                       extra_body={'temperature': 1.5, 'top_p': 1, 'custom': 'retained'})
    root = overlay_root_model(base, {'temperature': 0}, 'new-root')
    assert (root.temperature, root.top_p) == (0, 0.9)
    assert root.explicit_sampling == ['temperature']
    assert root.extra_body == {'top_p': 1, 'custom': 'retained'}
    assert base.temperature == 0.7 and base.explicit_sampling == []
    assert base.extra_body['temperature'] == 1.5
    inherited = overlay_root_model(base, {'temperature': None, 'top_p': None}, 'reset')
    assert (inherited.temperature,inherited.top_p) == (0.7,0.9)
    assert inherited.explicit_sampling == []
    for invalid in [True,'0.2',-0.1,3,float('nan'),float('inf')]:
        with pytest.raises(RunModelControlsError):
            overlay_root_model(base, {'temperature': invalid}, 'invalid')


def test_sampling_errors_are_actionable_and_sanitized_through_wrapped_causes():
    from nexent.core.models.openai_llm import SamplingConfigurationError
    inner = SamplingConfigurationError('provider-secret detail')
    outer = RuntimeError('private prompt'); outer.__cause__ = inner
    payload = sampling_configuration_error_payload(outer)
    assert payload['code'] == 'MODEL_SAMPLING_CONFIG_INVALID'
    chunk = safe_agent_stream_error_chunk(outer)
    assert 'MODEL_SAMPLING_CONFIG_INVALID' in chunk and 'provider-secret' not in chunk and 'private prompt' not in chunk
    assert sampling_configuration_error_payload(ValueError('unrelated')) is None
