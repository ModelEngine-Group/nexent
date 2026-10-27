# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Infrastructure regression proof; not live SAI product acceptance."""
import importlib.util
import ast
import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
import httpx

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'test-e2e/infra/automation'))


@pytest.mark.parametrize('status,message,valid', [
    (400, 'At least one supported knowledge base field must be provided for update', True),
    (200, 'At least one supported knowledge base field must be provided for update', False),
    (422, 'At least one supported knowledge base field must be provided for update', False),
    (400, 'name or description', False),
    (400, 'Unrelated validation failure', False),
])
def test_aidp_empty_update_retains_exact_current_rejection(status, message, valid):
    spec = importlib.util.spec_from_file_location(
        'aidp_update_contract_repair', REPO / 'test-e2e/cases/API-AUTO-7513FEF9904B9F3F/test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = httpx.Response(status, json={'message': message},
                              request=httpx.Request('PUT', 'http://fixture.test/owned-kb'))
    if valid:
        module.assert_empty_update_rejected(response)
    else:
        with pytest.raises(AssertionError):
            module.assert_empty_update_rejected(response)


@pytest.mark.parametrize('case_id', ['FAF-D4-001', 'NL2AGENT-PROTOCOL-D4-001'])
def test_repaired_d4_contract_actions_match_every_audited_phase(case_id):
    directory = REPO / 'test-e2e/cases' / case_id
    contract = yaml.safe_load((directory / 'case.yaml').read_text(encoding='utf-8'))['case']
    # Count actual AST array elements, not arrows inside nested helper callbacks.
    parser = r"""
const fs = require('node:fs');
const ts = require('./test-e2e/infra/automation/d1/frontend/node_modules/typescript');
const file = ts.createSourceFile('test.spec.ts', fs.readFileSync(process.argv[1], 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
const result = [];
function visit(node) {
  if (ts.isCallExpression(node) && node.expression.getText(file) === 'executeFixedScenario') {
    const shape = {};
    for (const property of node.arguments[1].properties) {
      if (ts.isPropertyAssignment(property) && ts.isArrayLiteralExpression(property.initializer))
        shape[property.name.getText(file)] = property.initializer.elements.length;
    }
    result.push(shape);
  }
  ts.forEachChild(node, visit);
}
visit(file);
process.stdout.write(JSON.stringify(result));
"""
    actual = json.loads(subprocess.check_output(
        ['node', '-e', parser, str(directory / 'test.spec.ts')], cwd=REPO, text=True))
    assert actual == [{'preconditions': len(contract['preconditions']),
                       'steps': len(contract['steps']),
                       'assertions': len(contract['expected_results'])}]


spec = importlib.util.spec_from_file_location('sai_evidence_repair', REPO / 'test-e2e/infra/automation/shared/sai_docker.py')
sai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sai)


@pytest.mark.parametrize('scope,batches', [('session', 1), ('system', 10)])
def test_probe_preserves_container_file_and_replaces_old_summary(tmp_path, monkeypatch, scope, batches):
    repo = tmp_path / 'repo'
    for source in sai.MODULES.values():
        path = repo / 'sdk/nexent' / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('current-source', encoding='utf-8')
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    (evidence / 'result.json').write_text('old-summary', encoding='utf-8')
    written = []

    def container(arguments, **kwargs):
        assert arguments[:3] == ['docker', 'run', '--rm']
        assert arguments[arguments.index('--scope') + 1] == scope
        assert arguments[arguments.index('--batches') + 1] == str(batches)
        raw = evidence / Path(arguments[-1]).name
        assert raw.is_file() and raw.read_text() == ''
        raw.write_text(json.dumps({'successful_invocations': 2 * batches, 'leftovers': 0}), encoding='utf-8')
        written.append(raw)
        kwargs['diagnostics'].write_text('{"exit_code": 0}', encoding='utf-8')

    monkeypatch.setattr(sai, 'command', container)
    original = Path.write_text

    def deny_overwrite(path, *args, **kwargs):
        if path in written or path == evidence / 'result.json':
            raise PermissionError('Simulated root-owned result cannot be truncated')
        return original(path, *args, **kwargs)

    # Container writes bypass the host guard; all later host writes are guarded.
    def guarded_container(*args, **kwargs):
        monkeypatch.setattr(Path, 'write_text', original)
        container(*args, **kwargs)
        monkeypatch.setattr(Path, 'write_text', deny_overwrite)

    monkeypatch.setattr(sai, 'command', guarded_container)
    result = sai.execute_probe(repo, {'runtime_image': 'owned-image'}, evidence, scope, batches)
    assert result['successful_invocations'] == 2 * batches
    assert result['images']['runtime_image'] == 'owned-image'
    assert 'images' not in json.loads(written[0].read_text())
    assert json.loads((evidence / 'result.json').read_text()) == result


def test_docker_failure_retains_structural_cause_without_kernel_secrets(tmp_path, monkeypatch):
    secret = 'runtime-generated-credential-xyz'
    stderr = f'Traceback:\n  File "/tests/probe.py", line 17, in run_probe\nPermissionError: [Errno 13] {secret}\n'
    monkeypatch.setattr(sai.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout=f'Authorization: {secret}', stderr=stderr))
    target = tmp_path / 'docker-run.json'
    with pytest.raises(AssertionError) as failure:
        sai.command(['docker', 'run'], diagnostics=target)
    evidence = json.loads(target.read_text())
    assert evidence['exit_code'] == 1
    assert evidence['stderr']['exception_types'] == ['PermissionError']
    assert evidence['stderr']['errno'] == ['13']
    assert evidence['stderr']['frames'] == [{'file': 'probe.py', 'line': 17, 'function': 'run_probe'}]
    assert secret not in target.read_text() and secret not in str(failure.value)
    frames = []
    trace = failure.value.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code.co_name == 'command':
            frames.append(trace.tb_frame.f_locals)
        trace = trace.tb_next
    assert len(frames) == 1 and 'completed' not in frames[0]


def test_docker_timeout_is_not_hidden_or_counted_as_pass(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(['docker', 'run'], 900, output='sensitive kernel output')
    monkeypatch.setattr(sai.subprocess, 'run', timeout)
    target = tmp_path / 'timeout.json'
    with pytest.raises(subprocess.TimeoutExpired):
        sai.command(['docker', 'run'], diagnostics=target)
    assert json.loads(target.read_text())['status'] == 'TIMEOUT'
    assert 'sensitive kernel output' not in target.read_text()


def test_bare_assertion_error_keeps_its_type_without_source_or_values():
    result = sai._diagnostic_summary('    assert secret_value\nAssertionError\n')
    assert result['exception_types'] == ['AssertionError']
    assert 'secret_value' not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_publish', [False, True])
async def test_repository_fixture_owns_and_cleans_only_created_resources(tmp_path, monkeypatch, fail_publish):
    import httpx
    sys.path.insert(0, str(REPO / 'test-e2e/infra/automation'))
    module_spec = importlib.util.spec_from_file_location(
        'owned_repository_fixture_repair', REPO / 'test-e2e/cases/API-AUTO-D6C1BBC6199D63C0/test.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    assignments, calls, released = {}, [], []

    def response(status, body):
        return httpx.Response(status, json=body, request=httpx.Request('GET', 'http://fixture'))

    class API:
        count = 0

        async def get(self, path):
            calls.append(('GET', path))
            if path == '/tag-libraries':
                return response(200, [{'bucket_key': 'default_resource', 'bucket_id': 17}])
            assert path.startswith('/tag-libraries/assignments/agent/')
            return response(200, {'assignments': [{'value_id': vid} for vid in assignments[int(path.rsplit('/', 1)[1])]]})

        async def post(self, path, json):
            calls.append(('POST', path))
            if path.endswith('/definitions'):
                self.count += 1
                return response(200, {'definition_id': self.count,
                                      'values': [{'value_id': self.count * 10}]})
            if path.endswith('/publish'):
                return response(500 if fail_publish else 200, {'version_no': 1})
            assert path.startswith('/repository/agent/')
            return response(200, {'agent_repository_id': int(path.split('/')[3]) + 100})

        async def put(self, path, json):
            assignments[int(path.rsplit('/', 1)[1])] = json['value_ids']
            return response(200, {})

        async def patch(self, path, json):
            calls.append((json['status'], path))
            return response(200, {})

        async def delete(self, path):
            calls.append(('DELETE', path))
            return response(200, {})

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        assert kwargs['token'] == 'fixture-token'
        yield API()

    @asynccontextmanager
    async def draft(identity, *, name_prefix, model_ids):
        assert model_ids == []
        agent_id = 1 + len(assignments)
        try:
            yield agent_id, {'name': name_prefix.replace('-', '_'), 'display_name': name_prefix}
        finally:
            released.append(agent_id)

    monkeypatch.setattr(module, 'client', fake_client)
    monkeypatch.setattr(module, '_draft_agent', draft)
    monkeypatch.setattr(module, 'register_asset', lambda *args, **kwargs: None)
    monkeypatch.setattr(module, 'mark_asset_state', lambda *args, **kwargs: None)
    identity = SimpleNamespace(id='tenant_a_admin', access_token='fixture-token')
    if fail_publish:
        with pytest.raises(AssertionError):
            async with module._owned_repository(identity):
                pytest.fail('Failed preparation must not yield an executable fixture')
    else:
        async with module._owned_repository(identity) as (_, agents, listings, tags, definitions, search):
            assert agents == [1, 2, 3] and listings == [101, 102, 103]
            assert assignments == {1: [10], 2: [20], 3: [10, 20]}
            assert len(tags) == len(definitions) == 2
            assert search.startswith('filter-') and search.endswith('-2')
            assert '_' not in search, 'Search must use display_name, not normalized name'
        assert {path for method, path in calls if method == 'not_shared'} == {
            f'/repository/agent/{rid}/status' for rid in listings}
    assert len(released) == (1 if fail_publish else 3)
    assert {path for method, path in calls if method == 'DELETE'} == {
        '/tag-libraries/17/definitions/1/values/10', '/tag-libraries/17/definitions/1',
        '/tag-libraries/17/definitions/2/values/20', '/tag-libraries/17/definitions/2'}


def test_case_mcp_binding_routes_all_consumers_and_restores_their_originals():
    # Execute the exact lightweight helper without importing the live app/DB.
    path = REPO / 'test-e2e/infra/automation/model_controls/runtime.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_bind_case_mcp')
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(path), 'exec'), namespace)
    regular = SimpleNamespace(get_tenant_local_mcp_server=lambda tenant: 'developer-stack')
    creator = SimpleNamespace(get_tenant_local_mcp_server=lambda tenant: None)
    with pytest.MonkeyPatch.context() as patch:
        namespace['_bind_case_mcp'](patch, 'http://case-owned.invalid/sse', regular, creator)
        for consumer in (regular, creator):
            assert consumer.get_tenant_local_mcp_server('isolated-tenant') == 'http://case-owned.invalid/sse'
    assert regular.get_tenant_local_mcp_server('isolated-tenant') == 'developer-stack'
    assert creator.get_tenant_local_mcp_server('isolated-tenant') is None
    fixture = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'runtime_fixture')
    call = next(node for node in ast.walk(fixture) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == '_bind_case_mcp')
    assert {node.id for node in call.args[2:]} == {'nl2agent_service', 'agent_preparation'}


@pytest.mark.asyncio
@pytest.mark.parametrize('lost_prompt_at', [None, 'draft', 'version'])
async def test_faf_uses_canonical_prompt_and_checks_both_snapshots(monkeypatch, lost_prompt_at):
    sys.path.insert(0, str(REPO / 'test-e2e/infra/automation'))
    import httpx
    from shared import faf
    drafts, versions, writes, readbacks, cleaned = {}, {}, [], [], []

    def response(body):
        return httpx.Response(200, json=body, request=httpx.Request('POST', 'http://fixture/agent'))

    @asynccontextmanager
    async def draft(identity, *, name_prefix, **kwargs):
        ident = len(drafts) + 1
        body = {'agent_id': ident, 'name': name_prefix.replace('-', '_'), 'display_name': name_prefix}
        drafts[ident] = {**body, 'prompt': ''}
        yield ident, body

    class API:
        async def post(self, path, json):
            if path == '/agent/update':
                assert 'prompt' in json and 'duty_prompt' not in json
                writes.append(dict(json))
                drafts[json['agent_id']] = dict(json)
                return response({'agent_id': json['agent_id']})
            if path.endswith('/publish'):
                ident = int(path.split('/')[2])
                versions[ident] = dict(drafts[ident])
                return response({'version_no': 1})
            assert path == '/agent/search_info'
            ident, version = json['agent_id'], json['version_no']
            readbacks.append((ident, version))
            body = dict(versions[ident] if version else drafts[ident])
            if lost_prompt_at == ('version' if version else 'draft'):
                body['prompt'] = ''
            return response(body)

    @asynccontextmanager
    async def client(*args, **kwargs):
        yield API()

    async def select(identity):
        return None

    async def delete(identity, ident):
        cleaned.append(ident)

    monkeypatch.setattr(faf, '_draft_agent', draft)
    monkeypatch.setattr(faf, 'client', client)
    monkeypatch.setattr(faf, 'selected_faf_model', select)
    monkeypatch.setattr(faf, '_delete_draft', delete)
    identity = SimpleNamespace(id='tenant_a_admin', access_token='fixture-session')
    if lost_prompt_at:
        with pytest.raises(AssertionError, match='instructions'):
            await faf.prepare_faf_agents(identity, 'FAF-D3-001')
        assert cleaned == [1]
    else:
        fixtures = await faf.prepare_faf_agents(identity, 'FAF-D3-001')
        assert len(writes) == 4
        assert readbacks == [(ident, version) for ident in range(1, 5) for version in (0, 1)]
        assert writes[0]['prompt'] == faf.PROMPTS['pure']
        assert writes[1]['prompt'] == faf.PROMPTS['mixed']
        assert writes[2]['prompt'] == faf.PROMPTS['child']
        assert writes[3]['related_agents'] == [{'agent_id': 3, 'version_no': 1}]
        assert 'faf_child' in writes[3]['prompt'] and 'FAF-PARENT-OK' in writes[3]['prompt']
        await faf.cleanup_faf_agents(identity, fixtures)
        assert cleaned == [4, 3, 2, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize('empty_catalog', [False, True])
async def test_aidp_create_fixture_uses_catalog_and_current_request_schema(monkeypatch, empty_catalog):
    import httpx
    from typing import List, Optional
    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
    from shared import aidp
    from shared.asset_registry import AssetDependencyError
    calls = []

    @asynccontextmanager
    async def client(*args, **kwargs):
        assert kwargs['token'] == 'fixture-session'
        async def get(path, **kwargs):
            calls.append((path, kwargs))
            return httpx.Response(200, json={'models': [] if empty_catalog else [
                {'model_name': 'configured-embedding'}, {'model_name': ''}]},
                request=httpx.Request('GET', 'http://fixture/models'))
        yield SimpleNamespace(get=get)

    monkeypatch.setattr(aidp, 'client', client)
    identity = SimpleNamespace(access_token='fixture-session')
    if empty_catalog:
        with pytest.raises(AssetDependencyError, match='no embedding model'):
            await aidp.create_payload(identity, 'owned-kb', ingroup_permission='PRIVATE')
        return
    body = await aidp.create_payload(identity, 'owned-kb', ingroup_permission='PRIVATE')
    assert calls == [('/aidp-mgmt/models', {'params': {'service': 'embedding', 'app': 'KnowledgeBase'}})]
    assert body['embedding_model'] == 'configured-embedding' and body['description'] == 'owned-kb'
    # Validate with the exact product schema, without importing live services.
    path = REPO / 'backend/ext_components/aidp/apps/aidp_mgmt_app.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CreateKbRequest')
    namespace = {key: value for key, value in locals().items() if key in {
        'BaseModel', 'ConfigDict', 'Field', 'field_validator', 'model_validator', 'List', 'Optional'}}
    namespace['__name__'] = __name__
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), namespace)
    schema = namespace['CreateKbRequest']
    assert schema.model_validate(body).embedding_model == 'configured-embedding'
    for missing in ('description', 'embedding_model'):
        with pytest.raises(ValueError):
            schema.model_validate({key: value for key, value in body.items() if key != missing})
    unauthorized = await aidp.create_payload(identity, 'auth-sweep', ingroup_permission='PRIVATE')
    assert schema.model_validate(unauthorized).name == 'auth-sweep'
