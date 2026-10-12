from __future__ import annotations

import json
import re
import uuid

import pytest

from shared.asset_registry import register_asset, mark_asset_state
from shared.case_evidence import read_sse_with_evidence, stream_diagnostics, write_case_evidence
from shared.http import MODEL_TIMEOUT, assert_status, client

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


def assert_requested_duty(value):
    # Sentence-ending punctuation is not a different functional requirement.
    expected = '我负责为用户提供专业的数据分析并输出可视化报告'
    assert isinstance(value, str) and value.strip().rstrip('。.!！') == expected, 'Requested duty content was not preserved'


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
        'model_ids': info.get('model_ids'),
        'tools': info.get('tools'),
        'skills': info.get('skills'),
        'related_agent_ids': info.get('related_agent_ids'),
    }


def assert_complete_draft(snapshot):
    """Prove the persisted local-task prerequisite, not a historical SSE marker."""
    assert re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,59}', snapshot.get('name') or ''), 'Invalid draft name'
    for field in ('description', 'duty_prompt', 'greeting_message'):
        assert isinstance(snapshot.get(field), str) and snapshot[field].strip(), f'Missing draft field: {field}'
    questions = snapshot.get('example_questions')
    assert isinstance(questions, list) and questions and all(
        isinstance(question, str) and question.strip() for question in questions), 'Missing example questions'
    if any(snapshot.get(field) for field in ('tools', 'skills', 'related_agent_ids')):
        for field in ('constraint_prompt', 'few_shots_prompt'):
            assert isinstance(snapshot.get(field), str) and snapshot[field].strip(), f'Missing resource Prompt: {field}'


async def _read_agent(identity, agent_id):
    async with client('config', token=identity.access_token) as api:
        response = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
    assert_status(response, 200)
    body = response.json()
    assert int(body.get('agent_id') or 0) == agent_id, 'Read-back returned another draft'
    return body


async def _create_draft(identity):
    run_id = _new_run_id()
    name = 'nl2a_' + run_id + '_assistant'
    payload = {
        'agent_id': None,
        'name': name,
        'display_name': 'NL2A 最小流程测试 ' + run_id,
        'description': '我是一个根据用户提供的天气文字生成简洁报告的助手。',
        'duty_prompt': '我负责根据用户直接提供的天气文字生成简洁报告，不查询外部天气。',
        'constraint_prompt': '仅使用用户提供的数据，不调用外部工具、技能或子智能体。',
        'few_shots_prompt': '示例：用户提供晴天和二十度信息时，我汇总这些已提供的信息。',
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
    try:
        async with client('config', token=identity.access_token) as api:
            released = await api.put(f'/agent/clear_new/{agent_id}')
        assert_status(released, 200)
    except BaseException:
        await _delete_draft(identity, int(agent_id))
        raise
    return int(agent_id)


async def _delete_draft(identity, agent_id):
    async with client('config', token=identity.access_token) as api:
        response = await api.request('DELETE', '/agent', json={'agent_id': agent_id})
    assert_status(response, (200, 404))
    mark_asset_state('owned_agents', str(agent_id), 'DELETED')


async def _run_turn(identity, agent_id, query, *, phase, history=None):
    body = {'query': query, 'agent_id': agent_id, 'history': history or []}
    async with client('runtime', token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        async with api.stream('POST', '/agent/nl2agent/run', json=body) as response:
            assert_status(response, 200)
            events = await read_sse_with_evidence(response, CASE_ID + '-' + phase + '-stream', limit=2000,
                                                  secrets=(identity.access_token, identity.refresh_token))
    tool_names = []
    nl2a_payloads = []
    state_events = []
    save_results = []
    final_answer_parts = []
    errors = []
    for event in events:
        data = event.get('data')
        if not isinstance(data, dict):
            continue
        ctype = data.get('type')
        if ctype == 'error':
            errors.append(data)
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
        elif ctype == 'execution_logs' and isinstance(content, str):
            # The trusted tool result retains updated_fields even when its
            # state marker reports that the existing draft remains complete.
            try:
                receipt = json.loads(content)
            except json.JSONDecodeError:
                continue
            if isinstance(receipt, dict) and receipt.get('created') is False and 'updated_fields' in receipt:
                save_results.append(receipt)
    result = {
        'tool_names': tool_names,
        'nl2a_payloads': nl2a_payloads,
        'state_events': state_events,
        'final_text': ' '.join(final_answer_parts),
        'save_results': save_results,
        'errors': errors,
    }
    write_case_evidence(CASE_ID + '-' + phase, {**result, **stream_diagnostics(events)},
                        secrets=(identity.access_token, identity.refresh_token))
    assert not errors, f'NL2Agent {phase} emitted an error; inspect sanitized protocol evidence'
    return result


def assert_local_save(result, before, after, agent_id, requested_fields, *, require_change=True):
    receipts = result['save_results']
    assert len(receipts) == 1, 'Local revision must have exactly one successful save receipt'
    receipt = receipts[0]
    assert receipt.get('status') == 'success' and receipt.get('agent_id') == agent_id
    fields = receipt.get('updated_fields')
    assert isinstance(fields, list) and len(fields) == len(set(fields))
    assert set(fields) == set(requested_fields), 'Tool saved fields outside the requested revision'
    assert sum(SAVE_TOOL in name for name in result['tool_names']) == 1, 'Revision must call the save tool once'
    assert result['state_events'], 'Save emitted no trusted state event'
    for event in result['state_events']:
        assert event.get('agent_id') == agent_id, 'State event refers to another draft'
        assert event.get('event') in {'agent_draft_fields_saved', 'agent_generation_completed'}
        if event['event'] == 'agent_draft_fields_saved':
            assert set(event.get('updated_fields') or []) == set(requested_fields)
    for field in before:
        if field in requested_fields:
            assert after[field], f'Requested field was not persisted: {field}'
            if require_change:
                assert after[field] != before[field], f'Requested field did not change: {field}'
        else:
            assert after[field] == before[field], f'Unrequested field or resource changed: {field}'
    assert result['final_text'].strip(), 'Local revision returned no final result'
    assert not any(_has_tool(result, tool) for tool in (SEARCH_INSTALLED, SEARCH_UNINSTALLED, RECOMMEND))
    assert not result['nl2a_payloads'], 'Explicit field-only revision opened a resource or clarification card'


def _has_completion(result):
    return any(event.get('event') == 'agent_generation_completed' for event in result['state_events'])


def _has_tool(result, needle):
    return any(needle in name for name in result['tool_names'])


def no_sync_answers(questions):
    answers = []
    for question in questions:
        assert question.get('question_type') == 'multiple_choice'
        assert isinstance(question.get('required'), bool)
        selected = []
        other_text = ''
        if question['required']:
            # Respect the real UI's required-answer rule. Never forge an empty
            # submission that a developer could not send from the card.
            tokens = ('不需要同步', '无需同步', '保持其他', '仅修改职责', '仅更新职责',
                      '不更新其他', '都不', 'none', 'no synchronization', 'no additional')
            options = [option for option in question.get('options', [])
                       if any(token in str(option.get('label', '')).lower() for token in tokens)]
            if not options and question.get('allow_other') is True:
                # The current card supports an open "Other" answer; the UI
                # accepts its nonempty text for a required multiple choice.
                other_text = '不需要同步其他字段，仅修改职责。'
            else:
                assert len(options) == 1, 'Required synchronization question has no unambiguous no-sync choice'
                assert options[0].get('option_id'), 'No-sync choice has no actual option identifier'
                selected = [options[0]['option_id']]
        answers.append({'question_id': question['question_id'], 'value': selected, 'other_text': other_text})
    return answers


def confirmation_history(query, result):
    # The web adapter uses extractTextContent for assistant history, not the
    # structured nl2a data card. Replaying raw card JSON as assistant prose
    # gave the model an invented transcript and could elicit a card echo.
    return [{'role': 'user', 'content': query},
            {'role': 'assistant', 'content': result['final_text']}]


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_local_tasks_do_not_enter_full_generation(tenant_a_admin):
    agent_id = await _create_draft(tenant_a_admin)
    try:
        base_snapshot = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        assert_complete_draft(base_snapshot)
        write_case_evidence(CASE_ID + '-prepare-readback', {
            'agent_id': agent_id, 'preparation': 'owned_api_draft', 'snapshot': base_snapshot})

        clarify = await _run_turn(tenant_a_admin, agent_id, '在继续之前，请先向我澄清这个智能体的需求。', phase='clarify')
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
        update = await _run_turn(tenant_a_admin, agent_id, '请把职责（duty_prompt）修改为：我负责为用户提供专业的数据分析并输出可视化报告，只修改职责这一个字段，不要改动其他字段。', phase='update')
        after_update = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        write_case_evidence(CASE_ID + '-update-readback', {
            'before': before_update, 'after': after_update, 'state_events': update['state_events'],
        }, secrets=(tenant_a_admin.access_token, tenant_a_admin.refresh_token))
        assert_local_save(update, before_update, after_update, agent_id, {'duty_prompt'})
        assert_requested_duty(after_update['duty_prompt'])
        assert not any(p.get('subtype') == 'requirement_clarification' for p in update['nl2a_payloads']), 'update_fields must not open a clarification card'
        assert _has_tool(update, SAVE_TOOL), 'update_fields must call save_agent_draft_fields'
        assert after_update['duty_prompt'] != before_update['duty_prompt'], 'duty_prompt was not changed'
        for field in ('name', 'display_name', 'description', 'constraint_prompt', 'few_shots_prompt', 'greeting_message', 'example_questions'):
            assert after_update[field] == before_update[field], 'update_fields must not change ' + field

        before_opt = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        optimize = await _run_turn(tenant_a_admin, agent_id,
            '请只优化欢迎语 greeting_message 和推荐问题 example_questions，两个字段都保存。'
            '欢迎语明确为：你好，我是数据分析助手，请提供待分析的数据和报告目标。'
            '推荐问题明确为以下三项：如何分析这份销售数据？如何比较两个时期的数据趋势？如何组织可视化报告？'
            '我已经确认这些文案，无需再次澄清，不修改其他字段或资源。', phase='optimize')
        after_opt = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        write_case_evidence(CASE_ID + '-optimize-readback', {
            'before': before_opt, 'after': after_opt, 'state_events': optimize['state_events'],
        }, secrets=(tenant_a_admin.access_token, tenant_a_admin.refresh_token))
        # Optimizing an already good question list can legitimately be
        # idempotent. Still prove one real save, nonempty readback and no cascade.
        assert_local_save(optimize, before_opt, after_opt, agent_id,
                          {'greeting_message', 'example_questions'}, require_change=False)
        for field in ('name', 'display_name', 'description', 'duty_prompt', 'constraint_prompt', 'few_shots_prompt'):
            assert after_opt[field] == before_opt[field], 'optimize_conversation must not change ' + field

        before_res = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        resources = await _run_turn(tenant_a_admin, agent_id,
            '请先只搜索和推荐一个可以查询天气的工具，让我选择；本轮还没有授权安装或绑定资源。'
            '我明确限定为搜索和推荐步骤，不修改 description、任何 Prompt、欢迎语、推荐问题或资源绑定。'
            '如果没有可用候选，请返回澄清卡让我决定下一步，不生成或保存任何字段。', phase='resources')
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

        before_related = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        related_query = ('把职责 duty_prompt 改成：我只根据用户直接提供的天气文字输出简明报告。'
                         '这可能影响其他 Prompt，但我还没有决定同步哪些字段，请先让我选择。')
        related = await _run_turn(tenant_a_admin, agent_id, related_query, phase='related-clarify')
        cards = [card for card in related['nl2a_payloads'] if card.get('subtype') == 'requirement_clarification']
        assert len(cards) == 1, 'Dependent field revision did not ask for synchronization choices'
        card = cards[0]
        assert card.get('agent_id') == agent_id, 'Dependent field card targets another draft'
        questions = card.get('questions') or []
        assert questions and all(question.get('question_type') == 'multiple_choice' and question.get('options')
                                 for question in questions), 'Dependent fields are not actionable multiple choices'
        assert not related['save_results'] and not related['state_events'], 'Fields saved before confirmation'
        assert _snapshot(await _read_agent(tenant_a_admin, agent_id)) == before_related
        action = {'type': 'nl2agent_card_action', 'subtype': 'requirement_clarification',
                  'agent_id': agent_id, 'action': 'submit', 'result': {'answers': no_sync_answers(questions)}}
        confirmed = await _run_turn(tenant_a_admin, agent_id, json.dumps(action, ensure_ascii=False),
            phase='related-confirm', history=confirmation_history(related_query, related))
        after_related = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        write_case_evidence(CASE_ID + '-related-readback', {
            'before': before_related, 'after': after_related, 'action': action,
            'save_results': confirmed['save_results'], 'state_events': confirmed['state_events'],
        }, secrets=(tenant_a_admin.access_token, tenant_a_admin.refresh_token))
        assert_local_save(confirmed, before_related, after_related, agent_id, {'duty_prompt'})

        before_violation = _snapshot(await _read_agent(tenant_a_admin, agent_id))
        violation = await _run_turn(tenant_a_admin, agent_id, '请把智能体的显示名称改成：新名字。', phase='violation')
        assert not _has_tool(violation, SAVE_TOOL), 'display_name change must not call save_agent_draft_fields'
        assert not violation['state_events'], 'display_name change must not emit a state event'
        assert _snapshot(await _read_agent(tenant_a_admin, agent_id)) == before_violation, 'whitelist-violating request must not modify any field'
    finally:
        # Preserve the primary assertion while exposing cleanup failures.
        import sys
        primary = sys.exception()
        try:
            await _delete_draft(tenant_a_admin, agent_id)
        except Exception as cleanup_error:
            if primary is None:
                raise
            primary.add_note(f'Owned NL2Agent draft cleanup failed: {type(cleanup_error).__name__}')
