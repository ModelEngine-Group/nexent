# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""A legacy physical index cannot be reused across known KB or tenant history."""

import pytest
from contracts.knowledge_maintenance import LEGACY_INDEX_OWNER
from nexent.storage.errors import ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import legacy_index_owner as mapping
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context


@pytest.mark.parametrize('foreign_tenant,deleted', [('tenant-a', 'N'), ('tenant-b', 'N'), ('tenant-b', 'Y')])
def test_ownership_counts_include_cross_kb_tenant_and_deleted_history(resources, monkeypatch, foreign_tenant, deleted):
    _, _, engine, tables = resources
    table = tables['cleanse_knowledge']; monkeypatch.setattr(mapping, 'knowledge', table)
    port = mapping.bind_legacy_index_owner(ServicePrincipal('user-a','tenant-a'), 1, 'kb-one', engine)
    try:
        assert port.get(LEGACY_INDEX_OWNER, 'kb-one', context=context())['owner_count'] == 1
        with engine.begin() as connection:
            connection.execute(table.insert(), {'knowledge_id': 2, 'index_name': 'kb-one', 'tenant_id': foreign_tenant, 'delete_flag': deleted})
        row = port.get(LEGACY_INDEX_OWNER, 'kb-one', context=context())
        assert row == {'index_name': 'kb-one', 'owner_count': 2, 'selected_owner_count': 1}
        with pytest.raises(ScopeDenied): port.create(LEGACY_INDEX_OWNER, row, context=context())
    finally: port.close()
