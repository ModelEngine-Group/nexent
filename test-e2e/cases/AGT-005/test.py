"""Unknown capability clarification uses structure, not exact model prose."""
import json

import pytest

from shared.case_evidence import stream_diagnostics, write_case_evidence
from shared.factories.agent import _draft_agent
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.sse import assert_terminal_event, read_sse

CASE_ID = 'AGT-005'


def clarification_cards(events):
    cards = []
    for event in events:
        data = event.get('data')
        if not isinstance(data, dict) or data.get('type') != 'nl2a':
            continue
        content = data.get('content')
        card = json.loads(content) if isinstance(content, str) else content
        if isinstance(card, dict) and card.get('subtype') == 'requirement_clarification':
            cards.append(card)
    return cards


def binding_choice_cards(events):
    cards = []
    for event in events:
        data = event.get('data')
        if isinstance(data, dict) and data.get('type') == 'nl2a':
            content = data.get('content')
            card = json.loads(content) if isinstance(content, str) else content
            if isinstance(card, dict) and card.get('subtype') == 'installed_resource_binding':
                cards.append(card)
    return cards


def assert_clarification_cards(events):
    cards = clarification_cards(events)
    assert cards, 'Clarification branch contains no actionable card'
    for card in cards:
        questions = card.get('questions')
        assert isinstance(questions, list) and questions, 'Clarification card contains no questions'
        identifiers = []
        for question in questions:
            assert question.get('question_id') and question.get('title')
            identifiers.append(question['question_id'])
            assert question.get('question_type') in {'single_choice', 'multiple_choice', 'text'}
            assert isinstance(question.get('required'), bool)
            if question['question_type'] != 'text':
                assert question.get('options'), 'Choice question has no options'
        assert len(identifiers) == len(set(identifiers)), 'Question identifiers are not unique'
    payloads = [e.get('data') for e in events if isinstance(e.get('data'), dict)]
    assert not any(p.get('type') in {'error', 'nl2a_state'} for p in payloads), (
        'Clarification must not fail or save/generate the draft'
    )


def assert_safe_missing_capability(events, before, after, agent_id, *, accessible_tool_ids=()):
    if clarification_cards(events):
        assert_clarification_cards(events)
        assert after == before, 'Paused clarification partially wrote the draft or bound resources'
        return
    choices = binding_choice_cards(events)
    if choices:
        # Resource selection, like clarification, is an explicit user-pause
        # protocol. A suggested existing tool is not an automatic binding.
        for card in choices:
            assert int(card.get('agent_id') or 0) == agent_id, 'Resource card belongs to another draft'
            resources = card.get('resources')
            assert isinstance(resources, list) and resources, 'Resource choice contains no candidates'
            for resource in resources:
                candidate = resource.get('candidate') or {}
                assert candidate.get('resource_type') == 'tool', 'Unexpected resource type for the missing-tool probe'
                reference = str(candidate.get('candidate_ref') or '')
                assert reference.startswith('tool:') and reference[5:].isdigit(), 'Candidate has no concrete tool reference'
                assert int(reference[5:]) in accessible_tool_ids, 'Candidate tool does not exist in the accessible catalog'
                assert resource.get('is_bound') is False, 'Unknown capability was automatically bound'
        assert after == before, 'User-pause resource choice partially wrote the draft'
        assert not any(isinstance(e.get('data'), dict) and e['data'].get('type') in {'error', 'nl2a_state'}
                       for e in events), 'Resource pause emitted an error or saved the draft'
        return
    # The existing scenario also permits full generation with the unsupported
    # capability omitted. Do not invent a mandatory clarification-only rule.
    assert_terminal_event(events)
    states = []
    for item in events:
        data = item.get('data')
        if isinstance(data, dict) and data.get('type') == 'nl2a_state':
            content = data.get('content')
            state = json.loads(content) if isinstance(content, str) else content
            assert isinstance(state, dict), 'Draft state is not a structured object'
            assert int(state.get('agent_id') or 0) == agent_id, 'Generation wrote another draft'
            states.append(state)
    assert any(s.get('event') == 'agent_generation_completed' for s in states), (
        'No clarification card or explicit completed degradation result'
    )
    for key in ('model_ids', 'tools', 'enabled_tool_ids', 'skills', 'enabled_skill_ids',
                'related_agent_ids', 'sub_agent_id_list', 'sub_agent_relations', 'external_sub_agent_id_list'):
        assert after.get(key) == before.get(key), f'Unknown capability unexpectedly changed resource binding {key}'
    for key in ('duty_prompt', 'greeting_message', 'example_questions'):
        assert after.get(key), f'Completed degradation did not persist required field {key}'


def draft_snapshot(body):
    return {key: body.get(key) for key in (
        'name', 'display_name', 'description', 'duty_prompt', 'constraint_prompt',
        'few_shots_prompt', 'greeting_message', 'example_questions', 'model_ids',
        'tools', 'enabled_tool_ids', 'skills', 'enabled_skill_ids', 'related_agent_ids',
        'sub_agent_id_list', 'sub_agent_relations', 'external_sub_agent_id_list',
    )}


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_agt_005(tenant_a_admin):
    async with _draft_agent(tenant_a_admin, name_prefix='nl2agent-missing-capability') as (agent_id, _):
        async with client('config', token=tenant_a_admin.access_token) as api:
            before = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
        assert_status(before, 200)
        assert int(before.json().get('agent_id') or 0) == agent_id, 'Initial read-back did not return the owned draft'
        query = 'Create an assistant using a nonexistent external capability named d3-missing-tool.'
        async with client('runtime', token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream('POST', '/agent/nl2agent/run', json={
                'query': query, 'agent_id': agent_id, 'history': [], 'complexity': 'complicated',
            }) as response:
                assert_status(response, 200)
                events = await read_sse(response)
        async with client('config', token=tenant_a_admin.access_token) as api:
            after = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
            tools = await api.get('/tool/list')
        assert_status(after, 200)
        assert_status(tools, 200)
        catalog = tools.json()
        assert isinstance(catalog, list), 'Accessible tool catalog is not a list'
        accessible = {int(row.get('tool_id') or row['id']) for row in catalog}
        assert int(after.json().get('agent_id') or 0) == agent_id, 'Final read-back did not return the owned draft'
        before_state, after_state = draft_snapshot(before.json()), draft_snapshot(after.json())
        write_case_evidence(CASE_ID + '-clarification', {
            **stream_diagnostics(events), 'before': before_state, 'after': after_state,
            'accessible_tool_ids': sorted(accessible),
        }, secrets=(tenant_a_admin.access_token, tenant_a_admin.refresh_token))
        assert_safe_missing_capability(events, before_state, after_state, agent_id,
                                       accessible_tool_ids=accessible)
