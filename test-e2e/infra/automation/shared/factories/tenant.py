"""Owned, API-provisioned tenants/accounts for mutating identity/quota tests.

Credentials are memory-only. Shared users.yaml and anchor tenants are untouched.
This factory is deliberately not an arbitrary resource-cleanup proxy: callers
must not register resources under temporary identities for a later process.
"""
from contextlib import asynccontextmanager
from functools import wraps
import inspect
import secrets
import uuid

from shared.auth import sign_in, sign_in_credentials
from shared.http import client, assert_status
from shared.asset_registry import register_asset, mark_asset_state, AssetDependencyError


ROLES = {'admin': 'ADMIN', 'user': 'USER', 'dev': 'DEV'}


async def delete_isolated_user(api, tenant_id, user_id):
    response = await api.delete(f'/users/{user_id}')
    # Repeated product DELETE returns 400; accept only verified absence.
    assert_status(response, (200, 400, 404))
    listing = await api.post('/users/list', json={'tenant_id': tenant_id, 'page': 1, 'page_size': 100})
    assert_status(listing, 200)
    rows = listing.json().get('data')
    if not isinstance(rows, list):
        raise RuntimeError('Cannot verify temporary user absence')
    if any(str(row.get('user_id') or row.get('id')) == user_id for row in rows):
        raise RuntimeError('Temporary user remains after deletion')


async def delete_isolated_tenant(api, tenant_id):
    listing = await api.post('/users/list', json={'tenant_id': tenant_id, 'page': 1, 'page_size': 100})
    assert_status(listing, 200)
    if listing.json().get('data') != []:
        raise RuntimeError('Owned tenant still contains users; cleanup incomplete')
    deleted = await api.delete(f'/tenants/{tenant_id}')
    assert_status(deleted, (200, 404))


@asynccontextmanager
async def isolated_accounts(aliases):
    aliases = tuple(dict.fromkeys(aliases))
    supported = {f'tenant_{tenant}_{role}' for tenant in ('a', 'b') for role in ROLES}
    supported.update({'tenant_a_user2', 'tenant_b_user2'})
    for alias in aliases:
        if alias not in supported:
            raise ValueError('Unsupported isolated identity alias')
    manager = await sign_in('super_admin')
    if manager.role != 'SU':
        raise AssetDependencyError('identities', 'super_admin', detail='Temporary tenants require SU')
    tenants, accounts, users = {}, {}, []
    primary = None
    async with client('config', token=manager.access_token) as api:
        try:
            for alias in aliases:
                tenant_key, role_key = alias.rsplit('_', 1)
                if role_key == 'user2':
                    role_key = 'user'
                if tenant_key not in tenants:
                    response = await api.post('/tenants', json={
                        'tenant_name': 'isolated-' + uuid.uuid4().hex,
                        'skill_ids': [], 'skill_names': [], 'locale': 'zh'})
                    assert_status(response, 201)
                    tenant = response.json().get('data') or {}
                    tid = str(tenant.get('tenant_id') or '')
                    if not tid or tid == manager.tenant_id:
                        raise RuntimeError('Tenant creation did not return a new owned ID')
                    tenants[tenant_key] = tenant
                    register_asset('isolated_tenants', tid, tid,
                        owner_case_id='ISOLATED-IDENTITY-FACTORY', cleanup={
                            'kind': 'delete_isolated_tenant', 'tenant_id': tid,
                            'service': 'config', 'identity': manager.id, 'method': 'DELETE',
                            'path': f'/tenants/{tid}', 'allowed_statuses': [200, 404]})
                tenant = tenants[tenant_key]
                tid = str(tenant['tenant_id'])
                invited = await api.post('/invitations', json={
                    'tenant_id': tid, 'code_type': ROLES[role_key] + '_INVITE',
                    'group_ids': [int(tenant['default_group_id'])], 'capacity': 1})
                assert_status(invited, 201)
                code = (invited.json().get('data') or {}).get('invitation_code')
                if not code:
                    raise RuntimeError('Invitation creation omitted its code')
                email = 'nexent-test-' + uuid.uuid4().hex + '@example.com'
                password = 'Nt9!' + secrets.token_urlsafe(24)
                async with client('config') as anonymous:
                    created = await anonymous.post('/user/signup', json={
                        'email': email, 'password': password, 'invite_code': code, 'auto_login': True})
                assert_status(created, 200)
                user_id = str(((created.json().get('data') or {}).get('user') or {}).get('id') or '')
                if not user_id:
                    raise RuntimeError('Signup omitted user ID; owned tenant needs reconciliation')
                users.append((tid, user_id))
                # Cleanup always authenticates as the stable manager, not the new account.
                register_asset('isolated_users', user_id, user_id,
                    owner_case_id='ISOLATED-IDENTITY-FACTORY', cleanup={
                        'kind': 'delete_isolated_user', 'tenant_id': tid, 'user_id': user_id,
                        'service': 'config', 'identity': manager.id, 'method': 'DELETE',
                        'path': f'/users/{user_id}', 'allowed_statuses': [200]})
                identity = await sign_in_credentials(alias, {
                    'username': email, 'tenant': tid, 'role': ROLES[role_key]}, password)
                if (identity.user_id, identity.tenant_id, identity.role) != (user_id, tid, ROLES[role_key]):
                    raise RuntimeError('Temporary account role/tenant readback mismatch')
                accounts[alias] = identity
            yield accounts
        except BaseException as exc:
            primary = exc
            raise
        finally:
            failures = []
            for tid, uid in reversed(users):
                try:
                    await delete_isolated_user(api, tid, uid)
                    mark_asset_state('isolated_users', uid, 'DELETED')
                except Exception as exc:
                    failures.append(type(exc).__name__)
                    mark_asset_state('isolated_users', uid, 'ORPHANED', detail=type(exc).__name__)
            for tenant in reversed(list(tenants.values())):
                tid = str(tenant['tenant_id'])
                try:
                    # Do not accept the cascade endpoint's swallowed user errors.
                    await delete_isolated_tenant(api, tid)
                    mark_asset_state('isolated_tenants', tid, 'DELETED')
                except Exception as exc:
                    failures.append(type(exc).__name__)
                    mark_asset_state('isolated_tenants', tid, 'ORPHANED', detail=type(exc).__name__)
            if failures:
                message = 'Isolated account cleanup incomplete; see asset journal'
                if primary is None:
                    raise RuntimeError(message)
                if hasattr(primary, 'add_note'):
                    primary.add_note(message)
                else:
                    primary.__notes__ = [*getattr(primary, '__notes__', []), message]


def with_isolated_accounts(test):
    """Keep the original test assertions and pytest fixture signature intact."""
    signature = inspect.signature(test)
    aliases = [name for name in signature.parameters if name.startswith(('tenant_a_', 'tenant_b_'))]
    if not aliases:
        raise ValueError('Isolated account test must consume at least one identity')

    @wraps(test)
    async def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        async with isolated_accounts(aliases) as identities:
            bound.arguments.update(identities)
            return await test(*bound.args, **bound.kwargs)
    return wrapped
