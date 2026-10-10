import pytest
from unittest import mock

import services.agent_repository_service as svc

CASE_ID = 'UT-BE-AUTO-2448EA6E8C27143B'

TENANT_ID = 'tenant-a'
USER_ID = 'su-user-1'
AGENT_REPOSITORY_ID = 9001
AGENT_ID = 7001
PUBLISHER_USER_ID = 'publisher-user-1'
RESOURCE_TYPE = 'agent_repository'
EVENT_TYPE_PENDING = 'repository_review_pending'

_MOCK_NAMES = (
    'get_agent_repository_by_id',
    'update_agent_repository_status_by_id',
    'reset_agent_repository_status',
    '_get_user_role',
    'create_repository_review_notification',
    'deactivate_notifications',
)


def _make_record(status):
    return {
        'agent_repository_id': AGENT_REPOSITORY_ID,
        'agent_id': AGENT_ID,
        'author': 'author-a',
        'submitted_by': 'submitter@example.com',
        'name': 'agent-a',
        'display_name': 'Agent A',
        'description': 'desc',
        'status': status,
        'tags': ['tag-a'],
        'tool_count': 2,
        'version_name': 'V1',
        'icon': 'icon',
        'downloads': 0,
        'content': '',
        'publisher_tenant_id': TENANT_ID,
        'publisher_user_id': PUBLISHER_USER_ID,
    }


def _install_mocks(monkeypatch):
    mocks = {}
    for name in _MOCK_NAMES:
        patched = mock.Mock()
        monkeypatch.setattr(svc, name, patched)
        mocks[name] = patched
    mocks['update_agent_repository_status_by_id'].return_value = 1
    mocks['_get_user_role'].return_value = 'SU'
    return mocks


def _call_impl(mocks, current, new, content=None, notify_content=None):
    record = _make_record(current)
    updated = _make_record(new)
    mocks['get_agent_repository_by_id'].side_effect = [record, updated]
    return svc.update_agent_repository_status_impl(
        agent_repository_id=AGENT_REPOSITORY_ID,
        status=new,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        notify_content=notify_content,
        content=content,
    )


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_su_agent_repository_status_transitions(monkeypatch, caplog):
    mocks = _install_mocks(monkeypatch)
    result = _call_impl(mocks, 'pending_review', 'rejected', content='reason-rejected')
    assert result['status'] == 'rejected'
    assert result['agent_repository_id'] == AGENT_REPOSITORY_ID
    mocks['_get_user_role'].assert_called_once_with(USER_ID)
    mocks['update_agent_repository_status_by_id'].assert_called_once_with(
        repository_id=AGENT_REPOSITORY_ID,
        status='rejected',
        user_id=USER_ID,
        filter_publisher_tenant_id=TENANT_ID,
        publisher_tenant_id=None,
        publisher_user_id=None,
        submitted_by=None,
        content='reason-rejected',
    )
    mocks['reset_agent_repository_status'].assert_called_once_with(
        agent_repository_id=AGENT_REPOSITORY_ID,
        agent_id=AGENT_ID,
        status='rejected',
        publisher_tenant_id=TENANT_ID,
    )
    mocks['create_repository_review_notification'].assert_called_once_with(
        resource_type=RESOURCE_TYPE,
        review_status='rejected',
        receiver_user_id=PUBLISHER_USER_ID,
        details={
            'name': 'Agent A',
            'agent_repository_id': AGENT_REPOSITORY_ID,
            'agent_id': AGENT_ID,
            'content': 'reason-rejected',
        },
        tenant_id=TENANT_ID,
        unique_id=AGENT_REPOSITORY_ID,
        created_by=USER_ID,
    )
    mocks['deactivate_notifications'].assert_called_once_with(
        event_type=EVENT_TYPE_PENDING,
        resource_type=RESOURCE_TYPE,
        unique_id=AGENT_REPOSITORY_ID,
        updated_by=USER_ID,
    )

    mocks = _install_mocks(monkeypatch)
    result = _call_impl(mocks, 'pending_review', 'shared')
    assert result['status'] == 'shared'
    mocks['reset_agent_repository_status'].assert_called_once_with(
        agent_repository_id=AGENT_REPOSITORY_ID,
        agent_id=AGENT_ID,
        status='shared',
        publisher_tenant_id=TENANT_ID,
    )
    mocks['create_repository_review_notification'].assert_called_once()
    assert mocks['create_repository_review_notification'].call_args.kwargs['review_status'] == 'shared'
    mocks['deactivate_notifications'].assert_called_once_with(
        event_type=EVENT_TYPE_PENDING,
        resource_type=RESOURCE_TYPE,
        unique_id=AGENT_REPOSITORY_ID,
        updated_by=USER_ID,
    )

    mocks = _install_mocks(monkeypatch)
    result = _call_impl(mocks, 'shared', 'not_shared')
    assert result['status'] == 'not_shared'
    mocks['reset_agent_repository_status'].assert_called_once_with(
        agent_repository_id=AGENT_REPOSITORY_ID,
        agent_id=AGENT_ID,
        status='not_shared',
        publisher_tenant_id=TENANT_ID,
    )
    mocks['create_repository_review_notification'].assert_not_called()
    mocks['deactivate_notifications'].assert_not_called()

    illegal_transitions = [
        ('pending_review', 'not_shared'),
        ('rejected', 'shared'),
        ('not_shared', 'pending_review'),
        ('rejected', 'not_shared'),
    ]
    for current, new in illegal_transitions:
        mocks = _install_mocks(monkeypatch)
        mocks['get_agent_repository_by_id'].return_value = _make_record(current)
        with pytest.raises(ValueError, match='Invalid status transition'):
            svc.update_agent_repository_status_impl(
                agent_repository_id=AGENT_REPOSITORY_ID,
                status=new,
                user_id=USER_ID,
                tenant_id=TENANT_ID,
            )
        mocks['update_agent_repository_status_by_id'].assert_not_called()
        mocks['reset_agent_repository_status'].assert_not_called()
        mocks['create_repository_review_notification'].assert_not_called()
        mocks['deactivate_notifications'].assert_not_called()

    mocks = _install_mocks(monkeypatch)
    with pytest.raises(ValueError) as exc_info:
        svc.update_agent_repository_status_impl(
            agent_repository_id=AGENT_REPOSITORY_ID,
            status='archived',
            user_id=USER_ID,
            tenant_id=TENANT_ID,
        )
    assert 'Invalid status' in str(exc_info.value)
    assert 'archived' in str(exc_info.value)
    mocks['get_agent_repository_by_id'].assert_not_called()
    mocks['update_agent_repository_status_by_id'].assert_not_called()
    mocks['reset_agent_repository_status'].assert_not_called()

    mocks = _install_mocks(monkeypatch)
    mocks['get_agent_repository_by_id'].return_value = None
    with pytest.raises(ValueError, match='Repository listing not found'):
        svc.update_agent_repository_status_impl(
            agent_repository_id=AGENT_REPOSITORY_ID,
            status='shared',
            user_id=USER_ID,
            tenant_id=TENANT_ID,
        )
    mocks['update_agent_repository_status_by_id'].assert_not_called()
    mocks['reset_agent_repository_status'].assert_not_called()

    mocks = _install_mocks(monkeypatch)
    mocks['get_agent_repository_by_id'].return_value = _make_record('shared')
    mocks['update_agent_repository_status_by_id'].return_value = 0
    with pytest.raises(ValueError, match='Repository listing not found'):
        svc.update_agent_repository_status_impl(
            agent_repository_id=AGENT_REPOSITORY_ID,
            status='not_shared',
            user_id=USER_ID,
            tenant_id=TENANT_ID,
        )
    mocks['update_agent_repository_status_by_id'].assert_called_once()
    mocks['reset_agent_repository_status'].assert_not_called()
    mocks['create_repository_review_notification'].assert_not_called()
    mocks['deactivate_notifications'].assert_not_called()

    secret_markers = ('api_key', 'apikey', 'token', 'password', 'secret')
    for rec in caplog.records:
        message = rec.getMessage().lower()
        assert not any(marker in message for marker in secret_markers)
