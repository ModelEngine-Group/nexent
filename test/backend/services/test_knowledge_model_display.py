# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COL-DISPLAY-01 keep resource-bound display reads in Runtime SI."""

from contextlib import contextmanager
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.knowledge_collections import KnowledgeCollectionGrant
from nexent.storage.errors import (
    DeadlineExceeded,
    InvalidInput,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    FieldPatch,
    OperationContext,
    PageRequest,
    RecordQuery,
    Revision,
)
from runtime.model import display as module

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_model_display import DISPLAY, bind_knowledge_model_display


@pytest.fixture
def boundary():
    engine = sa.create_engine('sqlite://', execution_options={'schema_translate_map': {'nexent': None}})
    table = sa.Table('model_record_t', sa.MetaData(), sa.Column('model_id', sa.Integer, primary_key=True),
        *(sa.Column(name, sa.String) for name in ('tenant_id', 'display_name', 'model_type', 'delete_flag', 'api_key')), schema='nexent')
    table.create(engine)
    with engine.begin() as conn:
        for key, tenant, display, kind, deleted in [(1, 'tenant-a', 'Own', 'embedding', 'N'),
            (2, 'tenant-b', 'Remote', 'multi_embedding', 'N'), (3, 'tenant-b', 'Deleted', 'multi_embedding', 'Y'),
            (4, 'tenant-b', None, None, 'N')]:
            conn.execute(table.insert(), {'model_id': key, 'tenant_id': tenant, 'display_name': display,
                'model_type': kind, 'delete_flag': deleted, 'api_key': 'must-not-be-selected'})
    actor = ServicePrincipal('reader', 'tenant-a')
    grant = KnowledgeCollectionGrant(knowledge_id=7, collection='kb', resource_tenant_id='tenant-b',
                                      revision='a' * 64, embedding_model_id=2)
    opened, closed, statements = [], [], []
    sa.event.listen(engine, 'before_cursor_execute', lambda conn, cursor, statement, params, context, many: statements.append(statement))

    @contextmanager
    def ports(principal, approved, *, context):
        assert principal == actor and approved is grant
        records = bind_knowledge_model_display(principal, approved, engine)
        opened.append(records)
        try:
            yield records
        finally:
            records.close(); closed.append(True)

    yield SimpleNamespace(**locals())
    engine.dispose()


def invoke(s, **kwargs):
    return module.knowledge_model_display(s.actor, s.grant,
        context=OperationContext('display', monotonic() + 5), ports=s.ports, **kwargs)


def test_remote_model_uses_exact_resource_namespace_and_actual_actor_without_credentials(boundary):
    s = boundary
    result = invoke(s)
    assert result.display_name == 'Remote' and result.is_multimodal
    assert s.opened[0].scope.tenant_id == 'tenant-b' and s.opened[0].scope.actor_id == 'reader'
    assert len(s.statements) == 1 and 'api_key' not in s.statements[0] and 'http_headers' not in s.statements[0]
    assert set(result.model_dump()) == {'display_name', 'is_multimodal'} and s.closed == [True]


@pytest.mark.parametrize('model_id', [1, 3, 99])
def test_wrong_tenant_deleted_or_missing_model_keeps_original_empty_display(boundary, model_id):
    s = boundary
    s.grant.embedding_model_id = model_id
    result = invoke(s)
    assert result.display_name == '' and not result.is_multimodal and s.closed == [True]


def test_null_display_and_unknown_type_keep_original_values(boundary):
    s = boundary
    s.grant.embedding_model_id = 4
    result = invoke(s)
    assert result.display_name is None and not result.is_multimodal


def test_no_model_reference_never_opens_storage(boundary):
    s = boundary
    s.grant.embedding_model_id = None
    assert invoke(s).display_name == '' and not s.opened


def test_existing_display_best_effort_has_safe_warning_and_no_retry(boundary, caplog):
    s = boundary
    broken = Mock(side_effect=Unavailable())
    result = module.knowledge_model_display(s.actor, s.grant, context=OperationContext('display-error', monotonic() + 5), ports=broken)
    assert result.display_name == '' and not result.is_multimodal and broken.call_count == 1
    assert 'knowledge_model_display_unavailable' in caplog.text and 'display-error' in caplog.text


@pytest.mark.parametrize('error', [DeadlineExceeded(), OperationCancelled(), ScopeDenied()])
def test_timeout_cancel_and_bad_scope_are_never_defaulted(boundary, error):
    s = boundary
    broken = Mock(side_effect=error)
    with pytest.raises(type(error)):
        module.knowledge_model_display(s.actor, s.grant, context=OperationContext('display-error', monotonic() + 5), ports=broken)
    assert broken.call_count == 1


def test_pre_cancelled_parent_never_opens_storage(boundary):
    signal = Event(); signal.set()
    broken = Mock()
    with pytest.raises(OperationCancelled):
        module.knowledge_model_display(boundary.actor, boundary.grant,
            context=OperationContext('cancelled', monotonic() + 5, cancelled=signal), ports=broken)
    broken.assert_not_called()


def test_display_binding_cannot_request_credentials_or_write_models(boundary):
    s = boundary
    parent = OperationContext('finite-display', monotonic() + 5)
    with s.ports(s.actor, s.grant, context=parent) as records:
        with pytest.raises(InvalidInput):
            records.query(DISPLAY, RecordQuery(fields=('api_key',)), PageRequest(), context=parent)
        with pytest.raises(ScopeDenied):
            records.patch(DISPLAY, 2, FieldPatch(set_values={'display_name': 'changed'}),
                          expected=Revision('1'), context=parent)
    assert not s.statements


@pytest.mark.parametrize('field,value', [('tenant_id', 'tenant-a'), ('actor_id', 'other'),
    ('service_role', 'management'), ('system', True), ('resource_prefix', 'prefix')])
def test_corrupted_display_scope_is_not_reported_as_an_empty_name(boundary, field, value):
    s = boundary
    scope = SimpleNamespace(service_role='runtime', tenant_id='tenant-b', actor_id='reader', system=False,
                            resource_prefix='', namespaces={DISPLAY})
    setattr(scope, field, value)
    records = SimpleNamespace(scope=scope, get=Mock())
    closed = []
    @contextmanager
    def ports(*args, **kwargs):
        try:
            yield records
        finally:
            closed.append(True)
    with pytest.raises(ScopeDenied):
        module.knowledge_model_display(s.actor, s.grant, context=OperationContext('scope', monotonic() + 5), ports=ports)
    records.get.assert_not_called()
    assert closed == [True]
