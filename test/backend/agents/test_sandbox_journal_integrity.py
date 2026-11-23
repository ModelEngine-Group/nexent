# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Corrupt durable facts must never authorize another execution or cleanup."""

import json
import os
from dataclasses import asdict, replace

import pytest
from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal, SandboxRunRecord

from nexent.core.agents.sandbox_contracts import SandboxOwner


@pytest.fixture
def journal_record(tmp_path):
    journal = SandboxRunJournal(tmp_path / 'control')
    owner = SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')
    key = journal.business_key('release', 'ns', 'tenant', 'user', 7)
    return journal, SandboxRunRecord('a' * 32, key, asdict(owner), 'tenant', 'user', 7, 'b' * 64)


@pytest.mark.parametrize('field,value', [
    ('version', 2), ('phase', 'OTHER'), ('kind', 'OTHER'), ('run_id', '../escape'),
    ('owner', {}), ('tenant_id', ''), ('user_id', 7), ('conversation_id', True),
    ('associations', {}), ('business_key', 'c' * 64), ('updated_at', float('nan')),
    ('created_at', -1), ('workspace_path', 'relative'), ('workspace_path', '/safe/../other'),
    ('workspace_path', 7),
])
def test_invalid_protected_record_is_rejected(journal_record, field, value):
    journal, record = journal_record
    setattr(record, field, value)
    with pytest.raises(SandboxCoordinationUnknown):
        journal.publish(record)
    assert not list((journal.root / 'current').iterdir())


def test_business_association_type_and_immutable_identity(journal_record, tmp_path):
    journal, record = journal_record
    record.associations['assistant_message_id'] = []
    with pytest.raises(SandboxCoordinationUnknown, match='association value'):
        journal.publish(record)
    record.associations['assistant_message_id'] = 19
    record.workspace_path = str(tmp_path / 'run')
    journal.publish(record)
    for candidate in [replace(record, token_hash='c' * 64), replace(record, workspace_path=str(tmp_path / 'other'))]:
        with pytest.raises(SandboxCoordinationUnknown, match='immutable'):
            journal.write_run(candidate)
    record.associations['assistant_message_id'] = 20
    with pytest.raises(SandboxCoordinationUnknown, match='immutable'):
        journal.write_run(record)
    assert journal.read_current(record.business_key).associations['assistant_message_id'] == 19


@pytest.mark.parametrize('pointer', [[], {}, {'version': 2, 'run_id': 'a' * 32, 'business_key': 'placeholder'}])
def test_corrupt_current_pointer_is_not_an_empty_business_slot(journal_record, pointer):
    journal, record = journal_record
    if isinstance(pointer, dict) and 'business_key' in pointer:
        pointer['business_key'] = record.business_key
    journal._write(journal.root / 'current' / (record.business_key + '.json'), pointer)
    with pytest.raises(SandboxCoordinationUnknown, match='current pointer'):
        journal.read_current(record.business_key)


def test_missing_or_mismatched_run_cannot_satisfy_pointer(journal_record):
    journal, record = journal_record
    journal.publish(record)
    path = journal.root / 'runs' / (record.run_id + '.json')
    path.unlink()
    with pytest.raises(SandboxCoordinationUnknown, match='association is missing'):
        journal.read_current(record.business_key)
    value = asdict(record)
    value['run_id'] = 'c' * 32
    journal._write(path, value)
    with pytest.raises(SandboxCoordinationUnknown, match='run identity mismatch'):
        journal.read_run(record.run_id)
    journal._write(path, {'unexpected': True})
    with pytest.raises(SandboxCoordinationUnknown, match='Invalid sandbox journal record'):
        journal.read_run(record.run_id)


@pytest.mark.parametrize('timeout', [0, -1, float('inf'), float('nan')])
def test_lock_timeout_must_be_finite_and_positive(tmp_path, timeout):
    with pytest.raises(ValueError):
        SandboxRunJournal(tmp_path, lock_timeout_seconds=timeout)


def test_record_size_and_path_identity_limits(journal_record):
    journal, record = journal_record
    with pytest.raises(SandboxCoordinationUnknown, match='path identity'):
        journal.read_run('../outside')
    with pytest.raises(SandboxCoordinationUnknown, match='exceeds limit'):
        journal._write(journal.root / 'huge', {'payload': 'x' * 65536})
    assert not list(journal.root.glob('.*.tmp'))


@pytest.mark.skipif(os.name != 'posix', reason='Linux filesystem trust boundary')
@pytest.mark.parametrize('kind', ['mode', 'hardlink', 'large', 'symlink', 'corrupt'])
def test_unsafe_protected_files_fail_closed(journal_record, kind):
    journal, record = journal_record
    path = journal.root / 'unsafe'
    path.write_text(json.dumps({'safe': True}))
    path.chmod(0o600)
    if kind == 'mode':
        path.chmod(0o644)
    elif kind == 'hardlink':
        os.link(path, journal.root / 'second-link')
    elif kind == 'large':
        path.write_bytes(b'x' * 65537)
    elif kind == 'symlink':
        original = path.with_name('target')
        path.rename(original)
        path.symlink_to(original)
    else:
        path.write_text('{broken')
    with pytest.raises(SandboxCoordinationUnknown):
        journal._read(path)
