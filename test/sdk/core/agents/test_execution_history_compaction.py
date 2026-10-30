# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regression contracts for finalized execution summary/recall and exact messages."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing

from nexent.core.agents.context import ContextManager, ContextManagerConfig
from nexent.core.agents.context.execution_history import ExecutionHistory, result_text, summarize_record
from nexent.core.agents.context.models import ContextItem, ContextItemInput
from nexent.core.agents.context.rendering import ContextItemRenderer
from nexent.core.tools.read_execution_output_tool import ReadExecutionOutputTool


def summary_model(**kwargs):
    model = Mock(**kwargs)
    model.observer = None
    model.extra_body = {}
    model.context_budget_snapshot = None
    return model


def item(fields, **kwargs):
    return ContextItem.from_input(ContextItemInput(id='action', type='current_action', content={
        'assistant_output': '<code>print(result)</code>', 'execution_fields': fields, **kwargs,
    }))


def text(messages):
    return '\n'.join(p['text'] for m in messages for p in m['content'])


@pytest.mark.parametrize('value', ['0', 'False', '[]', ''])
def test_ac002_values_are_not_dropped_or_given_guessed_types(value):
    rendered = text(ContextItemRenderer().render([item({'RETURN_VALUE': value})]))
    assert f'<RETURN_VALUE>{value}</RETURN_VALUE>' in rendered
    assert 'type=' not in rendered
    assert rendered.count('print(result)') == 1
    assert 'completed_action_history' not in rendered
    assert 'index:' not in rendered


def test_ac003_partial_output_and_error_are_escaped_and_preserved():
    rendered = text(ContextItemRenderer().render([item({'STDOUT':'partial <data>', 'ERROR':'timeout & retry'})]))
    assert '<STDOUT>partial &lt;data&gt;</STDOUT>' in rendered
    assert '<ERROR>timeout &amp; retry</ERROR>' in rendered


def test_ac001_compact_replaces_output_not_appends():
    rendered = text(ContextItemRenderer().render([item({'STDOUT':'LONG_SENTINEL'}, summary='facts', output_ref='message:5/unit-index:2')]))
    assert 'LONG_SENTINEL' not in rendered
    assert '<SUMMARIED_RESULT>facts</SUMMARIED_RESULT>' in rendered
    assert rendered.count('print(result)') == 1


def bound_history(fields=None):
    store = ExecutionHistory()
    key = store.register('owner', fields or {'STDOUT':'头部\n'+'data\n'*2000+'ORCHID-7429\n尾部'})
    store.bind(key, 5, 2)
    return store, key


def test_ac008_recall_exact_original_middle_without_execution():
    store, key = bound_history()
    original = store.get(key).text
    offset = original.index('ORCHID')
    result = json.loads(store.read('owner','message:5/unit-index:2',offset,11))
    assert result == {'text':'ORCHID-7429','next_offset':offset+11,'eof':False}
    assert store.get(key).payload() == {'content':original}


@pytest.mark.parametrize('owner,reference,offset,limit,error',[
    ('other','message:5/unit-index:2',0,10,PermissionError),
    ('owner','message:6/unit-index:2',0,10,PermissionError),
    ('owner','../../etc/passwd',0,10,ValueError),
    ('owner','message:5/unit-index:2',-1,10,ValueError),
    ('owner','message:5/unit-index:2',0,16001,ValueError),
    ('owner','message:5/unit-index:2',999999,10,ValueError),
])
def test_ac010_invalid_or_unauthorized_read(owner,reference,offset,limit,error):
    store,_ = bound_history()
    with pytest.raises(error):
        store.read(owner,reference,offset,limit)


def test_ac009_aggregate_read_budget_resets_only_between_actions():
    store,_=bound_history({'OUTPUT':'x'*40000})
    assert len(json.loads(store.read('owner','message:5/unit-index:2',0,16000))['text'])==16000
    with pytest.raises(ValueError,match='budget'):
        store.read('owner','message:5/unit-index:2',16000,1)
    store.reset_read_budget('owner')
    assert json.loads(store.read('owner','message:5/unit-index:2',16000,1))['next_offset']==16001


def test_ac014_summary_is_generated_once_and_payload_adds_only_summary():
    store,key=bound_history()
    record=store.get(key)
    model=summary_model(return_value=SimpleNamespace(content='Preserved ORCHID-7429 and limitations'))
    model.last_finish_reason='stop'
    with ThreadPoolExecutor(max_workers=2) as pool:
        values=list(pool.map(lambda _:summarize_record(record,model,20000),range(2)))
    assert values[0]==values[1]
    assert model.call_count==1
    assert set(record.payload())=={'content','summary'}
    assert 'ORCHID-7429' in record.payload()['content']
    assert 'untrusted data' in model.call_args.args[0][0].content[0]['text']


@pytest.mark.parametrize('response,finish',[('', 'stop'),('x'*20000,'stop'),('partial','length')])
def test_ac006_invalid_summary_not_saved_or_retried(response,finish):
    store,key=bound_history()
    model=summary_model(return_value=SimpleNamespace(content=response));model.last_finish_reason=finish
    for _ in range(2):
        assert summarize_record(store.get(key),model,20000) is None
    assert model.call_count==1
    assert 'summary' not in store.get(key).payload()


def test_ac006_full_input_too_large_is_not_silently_truncated():
    store,key=bound_history()
    model=summary_model()
    assert summarize_record(store.get(key),model,1000) is None
    model.assert_not_called()


def test_ac015_reference_cannot_move_or_collide():
    store,key=bound_history()
    store.bind(key,5,2)
    with pytest.raises(ValueError):store.bind(key,5,3)
    other=store.register('owner',{'STDOUT':'different'})
    with pytest.raises(ValueError):store.bind(other,5,2)


def test_ac005_selected_action_compacts_and_ac009_recent_loaded_stays_full():
    store,key=bound_history()
    manager=ContextManager(ContextManagerConfig(execution_history=store, effective_input_limit_tokens=20000, compaction_target_tokens=100))
    model=summary_model(return_value=SimpleNamespace(content='ORCHID-7429'));model.last_finish_reason='stop'
    original=item(store.get(key).fields,execution_key=key)
    compact=manager._compact_execution(original,model)
    assert compact.content['output_ref']=='message:5/unit-index:2'
    assert compact.content['summary']=='ORCHID-7429'
    assert original.content.get('summary') is None
    loaded=item(store.get(key).fields,execution_key=key,loaded_result=True)
    result=manager._compact_to_compaction_target([loaded],[],[],[],model=model)
    assert result==[loaded]


def test_ac011_masked_output_is_authoritative_for_summary_and_recall():
    store,key=bound_history({'OUTPUT':'*** '+'safe '*2000})
    model=summary_model(return_value=SimpleNamespace(content='safe'));model.last_finish_reason='stop'
    summarize_record(store.get(key),model,20000)
    assert 'SECRET' not in str(model.call_args)
    assert '***' in store.read('owner','message:5/unit-index:2')


def test_read_tool_marks_success_only_after_authorized_read():
    store,_=bound_history()
    on_read=Mock();tool=ReadExecutionOutputTool(store,'owner',on_read)
    tool.forward('message:5/unit-index:2',0,1)
    on_read.assert_called_once()
    with pytest.raises(PermissionError):tool.forward('message:6/unit-index:2')
    on_read.assert_called_once()


def test_ac009_remaining_context_budget_counts_json_and_xml_escaping():
    from html import escape
    store, key = bound_history({'OUTPUT': '"<&\\' * 5000})
    store.reset_read_budget('owner', max_rendered_chars=500)
    payload = store.read('owner', 'message:5/unit-index:2', 0, 4000)
    value = json.loads(payload)
    assert 0 < value['next_offset'] < 4000
    assert len(escape(payload)) + 80 <= 500
    with pytest.raises(ValueError, match='context budget'):
        store.read('owner', 'message:5/unit-index:2', value['next_offset'], 4000)


def test_ac009_zero_remaining_budget_is_explicit_and_does_not_consume_data():
    store, _ = bound_history()
    store.reset_read_budget('owner', max_rendered_chars=0)
    with pytest.raises(ValueError, match='context budget'):
        store.read('owner', 'message:5/unit-index:2')
    store.reset_read_budget('owner', max_rendered_chars=1000)
    assert json.loads(store.read('owner', 'message:5/unit-index:2', 0, 10))['next_offset'] == 10
