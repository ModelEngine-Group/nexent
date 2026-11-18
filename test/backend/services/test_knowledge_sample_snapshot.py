# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manifest sampling is bounded and revisions include unsampled published files."""

from unittest.mock import Mock

import pytest
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Page
from runtime.knowledge_base.sample import _snapshot

from test.backend.infrastructure.test_vector_store import context


def manifest(number):
    return {'tenant_id': 'tenant', 'record_id': f'{number:032x}', 'knowledge_id': 1, 'file_id': f'{number:032x}',
            'visible_version': 0, 'tombstone_version': -1, 'visible_generation': 'a' * 32, 'visible_job_id': 'b' * 32}


def test_snapshot_hashes_all_pages_and_keeps_at_most_requested_documents(monkeypatch):
    rows = [manifest(n) for n in range(501)]
    records = Mock()
    records.scope.tenant_id = "tenant"
    records.query.side_effect = [Page(tuple(rows[:500])), Page(tuple(rows[500:]))]
    monkeypatch.setattr('runtime.knowledge_base.sample.random.randrange', lambda n: n - 1)
    digest, chosen = _snapshot(records, 1, 2, context=context())
    assert chosen == rows[:2] and len(digest) == 64
    second = records.query.call_args.args[1]
    assert second.where.terms[1].field == 'record_id' and second.where.terms[1].value == rows[499]['record_id']
    assert second.order_by[0].field == 'record_id'
    rows[-1] = {**rows[-1], 'visible_generation': 'c' * 32}
    records.query.side_effect = [Page(tuple(rows[:500])), Page(tuple(rows[500:]))]
    changed, selected = _snapshot(records, 1, 0, context=context())
    assert changed != digest and selected == []


def test_tombstoned_and_unpublished_manifests_do_not_enter_sample_or_revision():
    records = Mock()
    records.scope.tenant_id = "tenant"
    records.query.return_value = Page((manifest(1),))
    original, _ = _snapshot(records, 1, 1, context=context())
    records.query.return_value = Page((manifest(1), {**manifest(2), 'visible_version': None},
                                      {**manifest(3), 'tombstone_version': 0}))
    final, chosen = _snapshot(records, 1, 10, context=context())
    assert original == final and chosen == [manifest(1)]


@pytest.mark.parametrize("foreign", [{"knowledge_id": 2}, {"tenant_id": "other-tenant"}])
def test_foreign_manifest_is_refused_even_if_driver_violates_scope(foreign):
    records = Mock()
    records.scope.tenant_id = "tenant"
    records.query.return_value = Page(({**manifest(1), **foreign},))
    with pytest.raises(ScopeDenied):
        _snapshot(records, 1, 1, context=context())
