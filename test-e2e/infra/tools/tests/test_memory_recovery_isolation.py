"""Offline regression for AGT-071 recovery data and context-proof boundaries."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))


def load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fresh_lookup_avoids_actual_lexical_mock_history_pollution():
    mock = load('test-e2e/infra/mock-services/memory-provider/server.py', 'recovery_memory_mock')
    state = mock.MemoryState()

    def add(text):
        state.add('owned-org', {'user_id': 'owned-user', 'infer': False,
                               'messages': [{'role': 'user', 'content': text}]})

    query = 'What is the unique answer for MEMLOOKUP-old? Return only that answer from memory.'
    seed = 'Nexent lookup MEMLOOKUP-old has unique answer EXTMEM-old'
    add(seed)
    for i in range(8):
        add(f'{i} {query} Local lookup LOCALLOOKUP-old has unique answer LOCALMEM-old')

    def search(text):
        return state.search('owned-org', {'query': text, 'filters': {'user_id': 'owned-user'},
                                          'top_k': 5})['results']

    # Reproduce the real false negative: old dialogue outranks the original fact.
    assert seed not in [item['memory'] for item in search(query)]
    recovery_lookup, recovery_answer = 'RECOVERYLOOKUP-fresh', 'RECOVERYANSWER-fresh'
    add(f'Nexent lookup {recovery_lookup} has unique answer {recovery_answer}')
    matches = search(recovery_lookup)
    assert len(matches) == 1 and recovery_answer in matches[0]['memory']
    assert recovery_answer not in recovery_lookup
    # Isolation is not a reset: all previous data still exists, and a missing
    # recovery fact is not fabricated by the Mock.
    assert len(state.records) == 10
    assert search('RECOVERYLOOKUP-absent') == []


@pytest.mark.parametrize('content,kind,expected', [
    ('Found 1 relevant memories:\n#### External Memory\n[1] RECOVERYANSWER-fresh', 'execution_logs', True),
    ('Found 1 relevant memories:\n#### User Memory\nRECOVERYANSWER-fresh', 'execution_logs', False),
    ('#### External Memory\n[]\n#### User Memory\nRECOVERYANSWER-fresh', 'execution_logs', False),
    ('RECOVERYANSWER-fresh', 'final_answer', False),
    ('#### External Memory\nRECOVERYANSWER-fresh', 'model_output_deep_thinking', False),
    ('#### External Memory\nRECOVERYANSWER-other', 'execution_logs', False),
])
def test_only_actual_external_context_can_prove_injection(content, kind, expected):
    case = load('test-e2e/cases/AGT-071/test.py', 'memory_recovery_case')
    events = [{'data': {'type': kind, 'content': content}}]
    assert case.external_context_has_marker(events, 'RECOVERYANSWER-fresh') is expected
