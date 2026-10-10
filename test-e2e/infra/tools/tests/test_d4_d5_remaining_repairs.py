"""Offline prerequisite/negative checks; not formal product acceptance."""
import sys
import re
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'automation'))
from d3 import assets
from d5.scenarios import scenario_security_special as security
from shared.asset_registry import AssetDependencyError
from shared.factories import model as models
from shared.factories import tenant


def test_browser_health_failure_is_not_pass_and_preserves_primary_assertions():
    page_source = (Path(__file__).resolve().parents[2] / 'automation/d4/pages/model.page.ts').read_text(encoding='utf-8')
    body = re.search(r'async verifyPersistedModel\([^\n]+\{\n(.*?)\n  \}\n\n  async checkAllConnectivity', page_source, re.S).group(1)
    script = '''
const assert = require('node:assert/strict');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const verify = new AsyncFunction('displayName', 'capability', 'dependencyCheck', BODY);
async function check(httpStatus, connectivity, prerequisite) {
  const fixture = { page: { request: { post: async () => ({
    ok: () => httpStatus === 200, status: () => httpStatus,
    json: async () => ({data: {connectivity}})
  }) } } };
  return verify.call(fixture, 'fixture', 'embedding', prerequisite);
}
(async () => {
  await assert.rejects(check(200, false, true), {name: 'DependencyFailure'});
  await assert.rejects(check(200, false, false), {name: 'ProductFailure'});
  await assert.rejects(check(500, true, true), /healthcheck returned 500/);
  assert.equal(await check(200, true, true), 200);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''.replace('BODY', repr(body))
    outcome = subprocess.run(['node', '-'], input=script, text=True, capture_output=True, timeout=15)
    assert outcome.returncode == 0, outcome.stderr


@pytest.mark.asyncio
async def test_security_provider_failure_precedes_tenant_creation(monkeypatch):
    probe = AsyncMock(side_effect=[1, AssetDependencyError('models', 'embedding', detail='TLS unavailable')])
    create = AsyncMock()
    monkeypatch.setattr(assets, 'model_id', probe)
    monkeypatch.setattr(tenant, 'isolated_accounts', create)
    with pytest.raises(AssetDependencyError, match='TLS unavailable'):
        await security._prompt_injection(SimpleNamespace(), SimpleNamespace())
    assert [call.args[0] for call in probe.await_args_list] == ['llm', 'embedding']
    create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,message,expected', [
    (409, "Failed to get embedding dimension for model 'fixture'. Please verify the URL, API key, and network connection.", AssetDependencyError),
    (409, 'Duplicate display name', AssertionError),
    (500, 'Unexpected product failure', AssertionError),
])
async def test_only_explicit_dimension_failure_is_dependency(monkeypatch, status, message, expected):
    posts = []
    class API:
        async def post(self, path, **kwargs):
            posts.append(path)
            return httpx.Response(status, json={'message': message}, request=httpx.Request('POST', 'http://fixture' + path))
    @asynccontextmanager
    async def client(*args, **kwargs):
        yield API()
    monkeypatch.setattr(models, 'client', client)
    monkeypatch.setattr(models, 'model_request', lambda kind, display_name: {'model_type': kind, 'display_name': display_name})
    with pytest.raises(expected):
        async with models.owned_configured_model(SimpleNamespace(access_token='fixture'), 'SEC-09', 'embedding'):
            pytest.fail('An unsuccessful preparation cannot enter security acceptance')
    assert posts == ['/model/create']
