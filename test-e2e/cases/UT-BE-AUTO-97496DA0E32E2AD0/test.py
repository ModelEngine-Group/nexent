import pytest

from consts.agent_unavailable_reasons import AgentUnavailableReason
from management.services.agent.read import apply_duplicate_name_availability_rules

CASE_ID = 'UT-BE-AUTO-97496DA0E32E2AD0'


def _entry(name, display_name, create_time, reasons=None):
    return {
        'raw_agent': {
            'name': name,
            'display_name': display_name,
            'create_time': create_time,
        },
        'unavailable_reasons': list(reasons) if reasons is not None else [],
    }


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_apply_duplicate_name_availability_rules():
    dup_name = AgentUnavailableReason.DUPLICATE_NAME
    dup_display = AgentUnavailableReason.DUPLICATE_DISPLAY_NAME

    entries = [
        _entry('shared', 'label-b', '2024-01-02T00:00:00Z'),
        _entry('shared', 'label-a', '2024-01-01T00:00:00Z'),
        _entry('shared', 'label-c', '2024-01-03T00:00:00Z'),
    ]
    returned = apply_duplicate_name_availability_rules(entries)
    assert returned is None
    by_display = {e['raw_agent']['display_name']: e for e in entries}
    assert dup_name not in by_display['label-a']['unavailable_reasons']
    assert by_display['label-b']['unavailable_reasons'].count(dup_name) == 1
    assert by_display['label-c']['unavailable_reasons'].count(dup_name) == 1

    entries = [
        _entry('name-x', 'shared label', '2024-02-02T00:00:00Z'),
        _entry('name-y', 'shared label', '2024-02-01T00:00:00Z'),
        _entry('name-z', 'shared label', '2024-02-03T00:00:00Z'),
    ]
    apply_duplicate_name_availability_rules(entries)
    by_name = {e['raw_agent']['name']: e for e in entries}
    assert dup_display not in by_name['name-y']['unavailable_reasons']
    assert by_name['name-x']['unavailable_reasons'].count(dup_display) == 1
    assert by_name['name-z']['unavailable_reasons'].count(dup_display) == 1

    entries = [
        _entry('cross', 'identity-a', '2024-03-01T00:00:00Z'),
        _entry('other', 'identity-b', '2024-03-02T00:00:00Z'),
        _entry('cross', 'identity-b', '2024-03-03T00:00:00Z'),
    ]
    apply_duplicate_name_availability_rules(entries)
    assert dup_name in entries[2]['unavailable_reasons']
    assert dup_display in entries[2]['unavailable_reasons']
    assert entries[0]['unavailable_reasons'] == []
    assert entries[1]['unavailable_reasons'] == []

    entries = [
        _entry('dup', 'unique-d1', '2024-04-01T00:00:00Z', [AgentUnavailableReason.MODEL_DELETED]),
        _entry('dup', 'unique-d2', '2024-04-02T00:00:00Z', [AgentUnavailableReason.MODEL_NOT_CONFIGURED]),
    ]
    apply_duplicate_name_availability_rules(entries)
    assert entries[0]['unavailable_reasons'] == [AgentUnavailableReason.MODEL_DELETED]
    assert entries[1]['unavailable_reasons'] == [AgentUnavailableReason.MODEL_NOT_CONFIGURED, dup_name]

    single = [_entry('solo', 'solo', '2024-05-01T00:00:00Z')]
    apply_duplicate_name_availability_rules(single)
    assert single[0]['unavailable_reasons'] == []

    empty = []
    apply_duplicate_name_availability_rules(empty)
    assert empty == []
