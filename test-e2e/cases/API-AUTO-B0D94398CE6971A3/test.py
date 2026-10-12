"""D2 contract test for /user/current_user_info auth_provider and username serialization.

Locks the serialization contract introduced at
backend/apps/user_management_app.py:238-241 and
backend/services/user_management_service.py:63-79:

* data.user.auth_provider is always a string in {local, cas}.
* data.user.username is serialized only for the CAS branch; the local branch
  must not contain the field at all.
* The remaining identity fields (user_id / group_ids / tenant_id / user_email /
  user_role / permissions / accessibleRoutes) survive intact.

The CAS branch (auth_provider == cas and username == provider_username)
depends on an external CAS provider, a linked provider=cas OAuth account and a
server-side CAS session. These are not provisioned by the D2 API contract stage;
when CAS is unavailable that branch is left unexercised (INFRA) and must not
affect the deterministic local-branch judgment below.
"""

from __future__ import annotations

import json

import pytest

from shared.http import assert_status, client

CASE_ID = 'API-AUTO-B0D94398CE6971A3'
STAGE = 'D2'

AUTH_PROVIDER_VALUES = ('local', 'cas')

REQUIRED_USER_FIELDS = (
    'user_id',
    'group_ids',
    'tenant_id',
    'user_email',
    'user_role',
    'permissions',
    'accessibleRoutes',
    'auth_provider',
)

_SENSITIVE_KEY_PARTS = (
    'password',
    'passwd',
    'apikey',
    'accesskey',
    'secret',
    'token',
    'authorization',
)


def _collect_keys(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            out.append(str(key))
            _collect_keys(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_keys(item, out)


def _assert_no_plaintext_secrets(payload) -> None:
    keys = []
    _collect_keys(payload, keys)
    normalized = {str(key).lower().replace('_', '').replace('-', '') for key in keys}
    leaked = sorted(key for key in normalized if any(part in key for part in _SENSITIVE_KEY_PARTS))
    assert not leaked, f'current_user_info response leaked sensitive keys: {leaked}'
    body = json.dumps(payload)
    assert 'bearer' not in body.lower(), 'current_user_info response leaked a bearer token'


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage(STAGE)
async def test_current_user_info_auth_provider_and_username_contract(tenant_a_user):
    identity = tenant_a_user

    async with client('config', token=identity.access_token) as api:
        response = await api.get('/user/current_user_info')
    assert_status(response, 200)

    payload = response.json()
    assert payload.get('message') == 'Success'

    data = payload.get('data')
    assert isinstance(data, dict), 'response data must be an object'
    user = data.get('user')
    assert isinstance(user, dict), 'data.user must be an object'

    auth_provider = user.get('auth_provider')
    assert auth_provider == 'local', (
        f'local session must serialize auth_provider=local, got {auth_provider!r}'
    )
    assert auth_provider in AUTH_PROVIDER_VALUES
    assert 'username' not in user, 'local branch must not serialize username'

    for field in REQUIRED_USER_FIELDS:
        assert field in user, f'data.user missing required field {field!r}'

    assert isinstance(user['user_id'], str) and user['user_id'], 'user_id must be a non-empty string'
    assert isinstance(user['tenant_id'], str), 'tenant_id must be a string'
    assert isinstance(user['user_email'], str), 'user_email must be a string'
    assert isinstance(user['user_role'], str), 'user_role must be a string'
    assert isinstance(user['group_ids'], list), 'group_ids must be a list'
    assert isinstance(user['permissions'], list), 'permissions must be a list'
    assert isinstance(user['accessibleRoutes'], list), 'accessibleRoutes must be a list'

    _assert_no_plaintext_secrets(payload)
