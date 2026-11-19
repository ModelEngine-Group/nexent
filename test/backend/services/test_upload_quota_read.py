# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UPLOADER-QUOTA-READ-01 checks actual SI personal quota inputs."""

import pytest
from nexent.storage.errors import ScopeDenied

from infrastructure import tenant_quota_read as records
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_tenant_quota_read import quota  # noqa: F401
from test.backend.services.test_tenant_quota_usage_read import usage  # noqa: F401


@pytest.fixture
def upload(usage):  # noqa: F811
    from management.services.file.upload_quota_read import UploadQuotaReader

    s = usage
    with s.engine.begin() as conn:
        table = s.tables['cleanse_knowledge']
        conn.execute(table.update().where(table.c.knowledge_id == 1).values(ingroup_permission='PRIVATE'))
        conn.execute(records.config_table.insert(), [
            {'tenant_config_id': i, 'tenant_id': tenant, 'config_key': key, 'config_value': value, 'delete_flag': deleted}
            for i, tenant, key, value, deleted in (
                (30, 'tenant-a', 'PERSONAL_KB_QUOTA_DEFAULT', '10', 'N'),
                (31, 'tenant-a', 'PERSONAL_KB_QUOTA_user-a', '8', 'N'),
                (32, 'tenant-b', 'PERSONAL_KB_QUOTA_user-a', '0', 'N'),
                (33, 'tenant-a', 'PERSONAL_KB_QUOTA_user-a', '999', 'Y'),
            )
        ])
    s.upload_reader = UploadQuotaReader(ports=s.usage_service.ports)
    return s


def test_actual_user_private_usage_excludes_other_users_and_orphans(upload):
    s = upload
    result = s.upload_reader.read('tenant-a', s.actor, context=context())
    assert result['tenant_source_bytes'] == 36 and result['personal_bytes'] == 5
    assert result['personal_limit'] == 8 and result['personal_source'] == 'individual'
    assert s.opened == [(s.actor, 'tenant-a')]


@pytest.mark.parametrize(('raw', 'limit', 'source'), [('0', 0, 'individual'), ('broken', 0, 'individual'),
                                                       (None, 10, 'default')])
def test_individual_zero_invalid_and_default_semantics(upload, raw, limit, source):
    s = upload
    with s.engine.begin() as conn:
        table = records.config_table
        conn.execute(table.update().where(table.c.tenant_config_id == 31).values(config_value=raw))
    result = s.upload_reader.read('tenant-a', s.actor, context=context())
    assert (result['personal_limit'], result['personal_source']) == (limit, source)


def test_no_individual_or_default_is_unlimited(upload):
    s = upload
    with s.engine.begin() as conn:
        table = records.config_table
        conn.execute(table.update().where(table.c.tenant_config_id.in_([30, 31])).values(delete_flag='Y'))
    result = s.upload_reader.read('tenant-a', s.actor, context=context())
    assert result['personal_limit'] is None and result['personal_source'] == 'unlimited'


def test_revoked_actor_cannot_read_upload_inputs(upload):
    s = upload
    s.update('cleanse_accounts', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.upload_reader.read('tenant-a', s.actor, context=context())
    assert not s.opened
