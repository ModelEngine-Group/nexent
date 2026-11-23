from __future__ import annotations

import logging

import pytest

from ext_components.aidp.consts.aidp_exceptions import (
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
)
from ext_components.aidp.services import aidp_permission_service as svc
from ext_components.aidp.services.aidp_permission_service import (
    EDIT,
    PRIVATE,
    READ_ONLY,
    REQUIRE_EDIT,
    AidpPermissionDecision,
    _decision_meets,
    _parse_group_ids,
    _resolve_permission,
    require_permission,
)

CAN_EDIT_ALL_USER_ROLES = ('SU', 'ADMIN', 'SPEED', 'ASSET_OWNER')


def _record(kb_id='kb-1', owner_user_id='owner-1', ingroup_permission=READ_ONLY, group_ids=None):
    record = {
        'kb_id': kb_id,
        'owner_user_id': owner_user_id,
        'ingroup_permission': ingroup_permission,
    }
    if group_ids is not None:
        record['group_ids'] = group_ids
    return record


@pytest.mark.case_id('UT-BE-AUTO-C41A646DB91F8B53')
@pytest.mark.stage('D1')
def test_resolve_permission_matrix(monkeypatch, caplog):
    kb_id = 'kb-1'
    tenant_id = 'tenant-1'
    owner = 'owner-1'

    decision = _resolve_permission(
        _record(kb_id=kb_id, owner_user_id=owner),
        user_id=owner,
        tenant_id=tenant_id,
        user_role='USER',
        user_groups=[],
    )
    assert isinstance(decision, AidpPermissionDecision)
    assert decision.permission == EDIT
    assert decision.is_management_role is False
    assert decision.matched_group_ids == ()

    for role in ('SU', 'USER'):
        decision = _resolve_permission(
            _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=PRIVATE, group_ids=[1, 2]),
            user_id='other-1',
            tenant_id=tenant_id,
            user_role=role,
            user_groups=[1, 2],
        )
        assert decision.permission is None
        assert decision.is_management_role is False
        assert decision.matched_group_ids == ()

    decision = _resolve_permission(
        _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=READ_ONLY, group_ids=[1, 2]),
        user_id='other-1',
        tenant_id=tenant_id,
        user_role='USER',
        user_groups=[1, 2],
    )
    assert decision.permission is None

    for role in CAN_EDIT_ALL_USER_ROLES:
        decision = _resolve_permission(
            _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=READ_ONLY, group_ids=[1, 2]),
            user_id='other-1',
            tenant_id=tenant_id,
            user_role=role,
            user_groups=[],
        )
        assert decision.permission == EDIT
        assert decision.is_management_role is True
        assert decision.matched_group_ids == ()

    decision = _resolve_permission(
        _record(kb_id=kb_id, owner_user_id=owner, group_ids=[3, 1, 2]),
        user_id='dev-1',
        tenant_id=tenant_id,
        user_role='DEV',
        user_groups=[2, 5, 1, 9],
    )
    assert decision.permission == READ_ONLY
    assert decision.is_management_role is False
    assert decision.matched_group_ids == (1, 2)

    decision = _resolve_permission(
        _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=None, group_ids=[1]),
        user_id='dev-1',
        tenant_id=tenant_id,
        user_role='DEV',
        user_groups=[1],
    )
    assert decision.permission == READ_ONLY
    assert decision.matched_group_ids == (1,)

    decision = _resolve_permission(
        _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=EDIT, group_ids=[7, 8]),
        user_id='dev-1',
        tenant_id=tenant_id,
        user_role='DEV',
        user_groups=[8],
    )
    assert decision.permission == EDIT
    assert decision.matched_group_ids == (8,)

    decision = _resolve_permission(
        _record(kb_id=kb_id, owner_user_id=owner, group_ids=[1, 2]),
        user_id='dev-1',
        tenant_id=tenant_id,
        user_role='DEV',
        user_groups=[3, 4],
    )
    assert decision.permission is None
    assert decision.matched_group_ids == ()

    decision = _resolve_permission(
        _record(kb_id=kb_id, owner_user_id=owner, group_ids=None),
        user_id='dev-1',
        tenant_id=tenant_id,
        user_role='DEV',
        user_groups=[3, 4],
    )
    assert decision.permission is None
    assert decision.matched_group_ids == ()

    with pytest.raises(AidpKbNotFoundError):
        _resolve_permission({}, user_id='dev-1', tenant_id=tenant_id)
    with pytest.raises(AidpKbNotFoundError):
        _resolve_permission(None, user_id='dev-1', tenant_id=tenant_id)

    assert _decision_meets(
        AidpPermissionDecision(kb_id, tenant_id, 'u', READ_ONLY, False, ()), REQUIRE_EDIT
    ) is False
    assert _decision_meets(
        AidpPermissionDecision(kb_id, tenant_id, 'u', EDIT, False, ()), REQUIRE_EDIT
    ) is True
    assert _decision_meets(
        AidpPermissionDecision(kb_id, tenant_id, 'u', None, False, ()), REQUIRE_EDIT
    ) is False

    monkeypatch.setattr(svc, '_get_permission_record', lambda *, kb_id, tenant_id: None)
    with pytest.raises(AidpKbNotFoundError):
        require_permission('kb-missing', 'dev-1', tenant_id, REQUIRE_EDIT)

    monkeypatch.setattr(svc, '_get_user_role', lambda user_id, tenant_id: 'DEV')
    monkeypatch.setattr(svc, '_get_user_groups', lambda user_id, tenant_id: [1])

    monkeypatch.setattr(
        svc,
        '_get_permission_record',
        lambda *, kb_id, tenant_id: _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=READ_ONLY, group_ids=[1, 2]),
    )
    with pytest.raises(AidpKbPermissionDeniedError):
        require_permission(kb_id, 'dev-1', tenant_id, REQUIRE_EDIT)

    monkeypatch.setattr(
        svc,
        '_get_permission_record',
        lambda *, kb_id, tenant_id: _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=PRIVATE, group_ids=[1, 2]),
    )
    with pytest.raises(AidpKbPermissionDeniedError):
        require_permission(kb_id, 'dev-1', tenant_id, REQUIRE_EDIT)

    assert _parse_group_ids([1, 2, 3]) == [1, 2, 3]
    assert _parse_group_ids('1, 2, 3') == [1, 2, 3]
    assert _parse_group_ids('1,,3') == [1, 3]
    assert _parse_group_ids(None) == []
    assert _parse_group_ids('') == []

    caplog.set_level(logging.INFO, logger='aidp_permission_service')
    caplog.clear()
    monkeypatch.setattr(
        svc,
        '_get_permission_record',
        lambda *, kb_id, tenant_id: _record(kb_id=kb_id, owner_user_id=owner, ingroup_permission=READ_ONLY, group_ids=[1, 2]),
    )
    with pytest.raises(AidpKbPermissionDeniedError):
        require_permission(kb_id, 'dev-1', tenant_id, REQUIRE_EDIT)
    logged_text = caplog.text.lower()
    for secret_marker in ('api_key', 'apikey', 'token', 'password', 'secret', 'sk-'):
        assert secret_marker not in logged_text
