"""Authenticated, org/user-scoped controls for the registered Mem0 Mock."""
import json
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from shared.asset_registry import AssetDependencyError
from shared.config import load_secret_env, repo_root
from shared.http import assert_status


def memory_settings():
    secrets = load_secret_env()
    settings = {}
    for name in ('NEXENT_EXTERNAL_MEMORY_PLUGIN', 'NEXENT_EXTERNAL_MEMORY_ENDPOINT',
                 'NEXENT_EXTERNAL_MEMORY_API_KEY'):
        configured, exported = secrets.get(name, ''), os.environ.get(name, '')
        if configured and exported and configured != exported:
            raise AssetDependencyError('memory', 'configuration', detail='Conflicting configured/exported ' + name)
        settings[name] = exported or configured
        if not settings[name]:
            raise AssetDependencyError('memory', 'configuration', detail='Missing existing configuration ' + name)
    if settings['NEXENT_EXTERNAL_MEMORY_PLUGIN'] != 'mem0':
        raise AssetDependencyError('memory', 'mock_protocol', detail='This controlled profile requires Mem0')
    manifest = json.loads((repo_root() / 'test-e2e/infra/mock-services/memory-provider/deployment.json').read_text())
    ready = next(item for item in manifest['readiness'] if item.get('json_equals', {}).get('profile') == 'mock')
    url = urlsplit(ready['url'])
    # Use the controller's registered published endpoint, not an invented env
    # variable or the Docker-only product endpoint.
    return {'plugin': 'mem0', 'endpoint': settings['NEXENT_EXTERNAL_MEMORY_ENDPOINT'].rstrip('/'),
            'api_key': settings['NEXENT_EXTERNAL_MEMORY_API_KEY'],
            'control_url': f'{url.scheme}://{url.netloc}', 'readiness_path': url.path,
            'readiness': ready['json_equals']}


class MemoryMock:
    def __init__(self, api, settings, user_id, org):
        self.api, self.settings, self.user_id, self.org = api, settings, str(user_id), org
        self.orgs = {org}

    def provider_params(self, org=None):
        self.orgs.add(org or self.org)
        return {'plugin.name': self.settings['plugin'], 'plugin.base_url': self.settings['endpoint'],
                'plugin.api_key': self.settings['api_key'], 'plugin.org_id': org or self.org}

    async def fault(self, status=200, delay=0):
        response = await self.api.post('/__control/fault', json={
            'user_id': self.user_id, 'status': status, 'delay_seconds': delay})
        # Never include fixture credentials in assertion output.
        assert response.status_code == 200, f'Memory fault control HTTP {response.status_code}'

    async def counts(self):
        response = await self.api.get('/__control/observations', params={'user_id': self.user_id})
        assert response.status_code == 200, f'Memory observations HTTP {response.status_code}'
        return response.json()['counts']

    async def cleanup(self):
        failures = []
        for org in sorted(self.orgs):
            try:
                # Header override is scoped to one request; fault controls
                # continue to use the original org. Never reset global data.
                headers = {'X-Org-Id': org}
                response = await self.api.delete('/__control/reset', headers=headers,
                                                  params={'user_id': self.user_id})
                assert response.status_code == 200, f'Memory scoped cleanup HTTP {response.status_code}'
                observed = await self.api.get('/__control/observations', headers=headers,
                                              params={'user_id': self.user_id})
                assert observed.status_code == 200 and observed.json()['counts'] == {}, 'Memory scope survived cleanup'
            except Exception:
                failures.append(org)
        assert not failures, 'Memory Mock scope cleanup failed'


@asynccontextmanager
async def memory_mock(identity):
    settings = memory_settings()
    org = 'case-memory-' + uuid4().hex
    headers = {'Authorization': 'Token ' + settings['api_key'], 'X-Org-Id': org}
    async with httpx.AsyncClient(base_url=settings['control_url'], headers=headers,
                                timeout=10, trust_env=False) as api:
        ready = await api.get(settings['readiness_path'])
        assert_status(ready, 200)
        if any(ready.json().get(key) != value for key, value in settings['readiness'].items()):
            raise AssetDependencyError('memory', 'mock_readiness', detail='Endpoint is not the registered memory Mock')
        mock = MemoryMock(api, settings, identity.user_id, org)
        await mock.counts()  # Verify the dedicated credential before product writes.
        primary = None
        try:
            yield mock
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                await mock.cleanup()
            except Exception:
                if primary is None:
                    raise
                primary.add_note('Memory Mock scoped cleanup also failed')
