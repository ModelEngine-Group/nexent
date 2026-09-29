from __future__ import annotations

import json
import uuid

import pytest

from shared.asset_registry import register_asset
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.sse import read_sse

CASE_ID = 'AGT-AUTO-6A6BC7594487E771'

SAVE_TOOL = 'save_agent_draft_fields'
SEARCH_INSTALLED = 'search_installed_resources'
SEARCH_UNINSTALLED = 'search_uninstalled_resources'
RECOMMEND = 'recommend_resources'


def _new_run_id():
    return uuid.uuid4().hex[:8]


def _normalize_example_questions(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return value


def _snapshot(info):
    return {
        'name': info.get('name'),
        'display_name': info.get('display_name'),
        'description': info.get('description'),
        'duty_prompt': info.get('duty_prompt'),
        'constraint_prompt': info.get('constraint_prompt'),
        'few_shots_prompt': info.get('few_shots_prompt'),
        'greeting_message': info.get('greeting_message'),
        'example_questions': _normalize_example_questions(info.get('example_questions')),
    }


async def _read_agent(identity, agent_id):
    async with client('config', token=identity.access_token) as api:
        response = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
    assert_status(response, 200)
    return response.json()


async def _create_draft(identity):
    run_id = _new_run_id()
    name = 'nl2a_' + run_id + '_assistant'
    payload = {
        'agent_id': None,
        'name': name,
        'display_name': 'NL2A 最小流程测试 ' + run_id,
        'description': '我是一个负责处理天气查询并生成简洁报告的助手。',
        'duty_prompt': '我负责根据用户提供的地点查询天气信息并生成简洁报告。',
        'constraint_prompt': '1. 只使用真实的天气数据。',
        'few_shots_prompt': '示例：用户询问北京天气时，我先查询再汇总输出。',
        'greeting_message': '你好，我是天气助手，请告诉我你想查询的城市。',
        'example_questions': ['今天北京的天气怎么样？', '上海明天会下雨吗？'],
        'enabled': True,
    }
    async with client('config', token=identity.access_token) as api:
        response = await api.post('/agent/update', json=payload)
    assert_status(response, 200)
    agent_id = response.json().get('agent_id')
    assert agent_id, 'agent create returned no agent_id'
    register_asset('owned_agents', str(agent_id), int(agent_id), owner_case_id=CASE_ID,
                   cleanup={'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                            'path': '/agent', 'json': {'agent_id': int(agent_id)},
                            'allowed_statuses': [200, 404]})
    return int(agent_id)


async def _delete_draft(identity, agent_id):
    try:
        async with client('config', token=identity.access_token) as api:
            await api.request('DELETE', '/agent', json={'agent_id': agent_id})
    except Exception:
        pass


async def _run_turn(identity, agent_id, query):
    body = {'query': query, 'agent_id': agent_id}
    async with client('runtime', token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        async with api.stream('POST', '/agent/nl2agent/run', json=body) as response:
            assert_status(response, 200)
            events = await read_sse(response, limit=2000)
    tool_names = []
    nl2a_payloads = []
    state_events = []
    final_answer_parts = []
    for event in events:
        data = event.get('data')
        if not isinstance(data, dict):
            continue
        ctype = data.get('type')
        content = data.get('content')
        tool_name = data.get('tool_name')
        if tool_name:
            tool_names.append(str(tool_name))
        if ctype == 'nl2a' and isinstance(content, str):
            try:
                nl2a_payloads.append(json.loads(content))
            except json.JSONDecodeError:
                pass
        elif ctype == 'nl2a_state' and isinstance(content, str):
            try:
                state_events.append(json.loads(content))
            except json.JSONDecodeError:
                pass
        elif ctype == 'final_answer' and isinstance(content, str):
            final_answer_parts.append(content)
    return {
        'tool_names': tool_names,
        'nl2a_payloads': nl2a_payloads,
        'state_events': state_events,
        'final_text': ' '.join(final_answer_parts),
    }


def _saved_fields(result):
    fields = []
    for event in result['state_events']:
        if event.get('event') == 'agent_draft_fields_saved':
            fields.extend(event.get('updated_fields') or [])
    return fields


def _has_completion(result):
    return any(event.get('event') == 'agent_generation_completed' for event in result['state_events'])


def _has_tool(result, needle):
    return any(needle in name for name in result['tool_names'])


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_local_tasks_do_not_enter_full_generation(tenant_a_admin):
    agent_id = await _create_draft(tenant_a_admin)
    try:
        base_snapshot = _snapshot(await _read_agent(tenant_a_admin, agent_id))

        clarify = await _run_turn(tenant_a_admin, agent_id, '在继续之前，请先向我澄清这个智能体的需求。')
        clarify_cards = [p for p in clarify['nl2a_payloads'] if p.get('subtype') == 'requirement_clarification']
        assert clarify_cards, 'clarify_requirements should return a requirement_clarification card'
        assert not clarify['state_events'], 'clarify_requirements must not save any field'
        assert not _has_tool(clarify, SAVE_TOOL), 'clarify_requirements must not call save_agent_draft_fields'
        assert not _has_tool(clarify, SEARCH_INSTALLED), 'clarify_requirements must not search installed resources'
        assert not _has_tool(clarify, SEARCH_UNINSTALLED), 'clarify_requirements must not search uninstalled resources'
        for card in clarify_cards:
            questions = card.get('questions') or []
            assert questions, 'clarification card must contain questions'
            for question in questions:
                assert question.get('question_id'), 'clarification question missing question_id'
                assert question.get('question_type') in ('single_choice', 'multiple_choice', 'text')
                assert question.get('title'), 'clarification question missing title'
                assert 'required' in question, 'clarification question missing required'
                if question.get('question_type') != 'text':
                    assert question.get('options'), 'choice clarification question missing options'
        assert _snapshot(await _read_agent(tenant_a_admin, agent_id)) == base_snapshot, 'clarify_requirements must not modify any field'

        before_update = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        update = await _run_turn(tenant_a_admin, agent_id, '请把职责（duty_prompt）修改为：我负责为用户提供专业的数据分析并输出可视化报告，只修改职责这一个字段，不要改动其他字段。')
        saved = _saved_fields(update)
        assert saved and set(saved) == {'duty_prompt'}, 'update_fields must only save the requested duty_prompt field'
        assert not _has_completion(update), 'update_fields must not emit agent_generation_completed'
        assert not any(p.get('subtype') == 'requirement_clarification' for p in update['nl2a_payloads']), 'update_fields must not open a clarification card'
        assert _has_tool(update, SAVE_TOOL), 'update_fields must call save_agent_draft_fields'
        after_update = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        assert after_update['duty_prompt'] != before_update['duty_prompt'], 'duty_prompt was not changed'
        for field in ('name', 'display_name', 'description', 'constraint_prompt', 'few_shots_prompt', 'greeting_message', 'example_questions'):
            assert after_update[field] == before_update[field], 'update_fields must not change ' + field

        before_opt = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        optimize = await _run_turn(tenant_a_admin, agent_id, '请帮我优化欢迎语和推荐问题。')
        opt_fields = _saved_fields(optimize)
        assert set(opt_fields) == {'greeting_message', 'example_questions'}, 'optimize_conversation must only save greeting_message and example_questions'
        assert not _has_completion(optimize), 'optimize_conversation must not emit agent_generation_completed'
        after_opt = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        assert after_opt['greeting_message'] != before_opt['greeting_message'], 'greeting_message was not changed'
        assert after_opt['example_questions'] != before_opt['example_questions'], 'example_questions were not changed'
        for field in ('name', 'display_name', 'description', 'duty_prompt', 'constraint_prompt', 'few_shots_prompt'):
            assert after_opt[field] == before_opt[field], 'optimize_conversation must not change ' + field

        before_res = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        resources = await _run_turn(tenant_a_admin, agent_id, '请帮我新增一个可以查询天气的工具。')
        assert not _has_tool(resources, SAVE_TOOL), 'manage_resources must not save description or Prompt fields'
        assert not resources['state_events'], 'manage_resources must not emit any draft field state event'
        assert not _has_completion(resources), 'manage_resources must not emit agent_generation_completed'
        engaged = (
            _has_tool(resources, 'parallel')
            or _has_tool(resources, SEARCH_INSTALLED)
            or _has_tool(resources, SEARCH_UNINSTALLED)
            or _has_tool(resources, RECOMMEND)
            or any(p.get('subtype') in ('suggested_resource_installation', 'installed_resource_binding', 'requirement_clarification') for p in resources['nl2a_payloads'])
        )
        assert engaged, 'manage_resources should run the resource search workflow or return a card'
        assert _snapshot(await _read_agent(tenant_a_admin, agent_id)) == before_res, 'manage_resources must not modify any Prompt or description field'

        before_violation = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        violation = await _run_turn(tenant_a_admin, agent_id, '请把智能体的显示名称改成：新名字。')
        assert not _has_tool(violation, SAVE_TOOL), 'display_name change must not call save_agent_draft_fields'
        assert not violation['state_events'], 'display_name change must not emit a state event'
        assert _snapshot(await _read_agent(tenant_a_admin, agent_id)) == before_violation, 'whitelist-violating request must not modify any field'
    finally:
        await _delete_draft(tenant_a_admin, agent_id)
