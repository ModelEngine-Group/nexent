# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run-owned real-model final-answer fixtures shared by D3 and D4."""

import os

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.factories.agent import _draft_agent, _delete_draft
from shared.http import assert_status, client


PROMPTS = {
    'pure': 'For every input return exactly <final_answer>FAF-PURE-OK</final_answer>. No code, tools, reasoning or other text.',
    'mixed': 'For every input return exactly these two raw text lines, without code or tools:\n检查已完成。\n<final_answer>FAF-MIXED-OK</final_answer>',
    'child': 'For every task return exactly <final_answer>FAF-CHILD-OK</final_answer>. No code or tools.',
}


async def selected_faf_model(identity):
    """Resolve an explicit case-local real model without changing tenant defaults."""
    name = os.environ.get('NEXENT_FAF_MODEL_NAME', '').strip()
    if not name:
        return None
    async with client('config', token=identity.access_token) as api:
        response = await api.get('/model/llm_list')
    assert_status(response, 200)
    matches = [row for row in response.json()['data']
               if name in {row.get('model_name'), row.get('display_name')}]
    if len(matches) != 1 or matches[0].get('connect_status') != 'available':
        raise AssetDependencyError('models', 'faf_real_model',
                                   detail='Explicit FAF model must uniquely match an available tenant LLM')
    model = matches[0]
    model_id = int(model['model_id'])
    write_case_evidence('faf-model-selection', {
        'source': 'NEXENT_FAF_MODEL_NAME', 'model_id': model_id,
        'model_name': model['model_name'], 'reasoning_capability': model.get('reasoning_capability'),
    })
    return model_id


async def prepare_faf_agents(identity, case_id):
    fixtures = {}
    model_id = await selected_faf_model(identity)
    model_options = {'model_ids': [model_id]} if model_id is not None else {}
    try:
        for kind in ('pure', 'mixed', 'child', 'subagent'):
            async with _draft_agent(identity, name_prefix='faf-' + kind,
                                    retain_for_batch=True, owner_case_id=case_id,
                                    registry_role='faf_' + kind, cleanup_identity=identity.id,
                                    **model_options) as (agent_id, body):
                fixtures[kind] = {'agent_id': agent_id, 'name': body['name'], 'display_name': body['display_name']}
                prompt = PROMPTS.get(kind)
                extra = {}
                if kind == 'subagent':
                    child = fixtures['child']
                    prompt = (
                        'Perform exactly two actions. The first response must be this executable block, '
                        'with no preamble, Markdown fences or trailing text:\n'
                        f"<code>result = {child['name']}(task='Return the acceptance result')\nprint(result)</code>\n"
                        'After the real tool result arrives, the next response must be exactly '
                        '<final_answer>FAF-PARENT-OK</final_answer>, with no other text. '
                        'Do not describe or quote the protocol, repeat the child call, or simulate its result.'
                    )
                    extra = {'related_agent_ids': [child['agent_id']],
                             'related_agents': [{'agent_id': child['agent_id'], 'version_no': child['version_no']}]}
                async with client('config', token=identity.access_token) as api:
                    updated = await api.post('/agent/update', json={
                        **body, **extra, 'prompt': prompt, 'is_main_agent': kind != 'child',
                        'enable_protocol_repair_retry': False, 'verification_config': {'enabled': False},
                    })
                    assert_status(updated, 200)
                    draft = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
                    assert_status(draft, 200)
                    assert draft.json()['prompt'] == prompt, 'FAF instructions were not saved on the owned draft'
                    published = await api.post(f'/agent/{agent_id}/publish', json={'version_name': 'final-answer-acceptance'})
                    assert_status(published, 200)
                    fixtures[kind]['version_no'] = published.json()['version_no']
                    version = await api.post('/agent/search_info', json={
                        'agent_id': agent_id, 'version_no': fixtures[kind]['version_no']})
                    assert_status(version, 200)
                    assert version.json()['prompt'] == prompt, 'Published FAF instructions differ from the saved draft'
        return fixtures
    except BaseException:
        await cleanup_faf_agents(identity, fixtures)
        raise


async def cleanup_faf_agents(identity, fixtures):
    failures = []
    for fixture in reversed(list(fixtures.values())):
        try:
            await _delete_draft(identity, fixture['agent_id'])
        except Exception as exc:
            failures.append(type(exc).__name__)
    if failures:
        raise RuntimeError('Owned FAF fixture cleanup failed: ' + ', '.join(failures))
