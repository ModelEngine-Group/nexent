"""Runner/configuration fault detection; these are not product acceptance results."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

import httpx

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))
import nexent_formal_pytest as plugin
from shared import config, memory_mock
from shared.asset_registry import AssetDependencyError
from d3.scenarios import scenario_memory_title_automation_scenarios as memory

spec = importlib.util.spec_from_file_location('runner_d3_repair', ROOT / 'test-e2e/infra/tools/run_cases.py')
runner = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT / 'test-e2e/infra/tools'))
spec.loader.exec_module(runner)
pytest_plugins = ['pytester']


@pytest.fixture
def formal(pytester, monkeypatch, tmp_path):
    monkeypatch.setenv('RESULT_DIR', str(tmp_path / 'results'))
    monkeypatch.setenv('NEXENT_REPO', str(ROOT))
    monkeypatch.setattr(plugin, 'apply_product_postgres_env', lambda: None)
    monkeypatch.setattr(plugin, 'load_yaml', lambda name: {})
    pytester.makeconftest('pytest_plugins = ["nexent_formal_pytest"]')
    return pytester, tmp_path / 'results'


@pytest.mark.parametrize('second,expected', [('pass', 'PASS'), ('assert False', 'FAIL'),
                                           ('raise RuntimeError("broken")', 'AUTOMATION_ERROR')])
def test_all_member_functions_are_required(formal, second, expected):
    pytester, result_dir = formal
    pytester.makepyfile(f'''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        def test_first(): pass
        def test_second(): {second}
    ''')
    pytester.runpytest_inprocess('-q')
    rows = [json.loads(line) for line in (result_dir / 'checkpoints/results.jsonl').read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]['result'] == expected
    assert rows[0]['expected_items'] == rows[0]['completed_items'] == 2


def test_cleanup_failure_cannot_be_hidden_by_call_pass(formal):
    pytester, result_dir = formal
    pytester.makepyfile('''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        @pytest.fixture
        def cleanup():
            yield
            raise RuntimeError('cleanup failed')
        def test_first(cleanup): pass
        def test_second(): pass
    ''')
    pytester.runpytest_inprocess('-q')
    row = json.loads((result_dir / 'checkpoints/results.jsonl').read_text())
    assert row['result'] == 'AUTOMATION_ERROR'
    assert 'teardown' in row['failure_reason'] and 'cleanup failed' in row['failure_reason']


def test_maxfail_cannot_certify_unexecuted_members(formal):
    pytester, result_dir = formal
    pytester.makepyfile('''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        def test_first(): assert False
        def test_second(): pass
    ''')
    pytester.runpytest_inprocess('-q', '--maxfail=1')
    row = json.loads((result_dir / 'checkpoints/results.jsonl').read_text())
    assert row['result'] == 'AUTOMATION_ERROR'
    assert row['expected_items'] == 2 and row['completed_items'] == 1


@pytest.mark.parametrize('other_stage', ['D3', 'D2'])
def test_unrelated_scripts_cannot_share_case_id(formal, other_stage):
    pytester, result_dir = formal
    pytester.makepyfile(test_one='''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        def test_first(): pass
    ''', test_two=f'''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('{other_stage}')]
        def test_other(): pass
    ''')
    result = pytester.runpytest_inprocess('-q')
    assert result.ret != 0
    result.stderr.fnmatch_lines(['*duplicate case_id FIXTURE-D3*'])


def test_setup_failure_still_requires_remaining_members(formal):
    pytester, result_dir = formal
    pytester.makepyfile('''
        import pytest
        from shared.asset_registry import AssetDependencyError
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        @pytest.fixture
        def unavailable(): raise AssetDependencyError('models','embedding', detail='offline')
        def test_first(unavailable): pass
        def test_second(): pass
    ''')
    pytester.runpytest_inprocess('-q', '--junitxml=' + str(result_dir / 'junit.xml'))
    outcome, counts = runner.junit_outcome(result_dir / 'junit.xml')
    assert outcome == 'FAIL'
    details = runner.pytest_failure_details(result_dir, 'FIXTURE-D3', 'D3', counts, {})
    assert details['status'] == 'BLOCKED_BY_DEPENDENCY'


@pytest.mark.parametrize('status', ['SKIPPED_BY_POLICY', 'SKIPPED_BY_SAFETY', 'BLOCKED_BY_DEPENDENCY'])
def test_explicit_junit_skip_status_retained(tmp_path, status):
    path = tmp_path / 'junit.xml'
    path.write_text(f'<testsuite><testcase><skipped message="{status}: disabled"/></testcase></testsuite>')
    assert runner.junit_outcome(path)[0] == status
    path.write_text(f'<testsuite><testcase><skipped message="{status}: disabled"/></testcase>'
                    '<testcase><failure>business assertion failed</failure></testcase></testsuite>')
    assert runner.junit_outcome(path)[0] == 'FAIL'


def test_parameter_variants_share_one_case(formal):
    pytester, result_dir = formal
    pytester.makepyfile('''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        @pytest.mark.parametrize('value', [0,1,2])
        def test_variant(value): assert value < 2
    ''')
    pytester.runpytest_inprocess('-q')
    row = json.loads((result_dir / 'checkpoints/results.jsonl').read_text())
    assert row['result'] == 'FAIL' and row['completed_items'] == 3


def test_collect_only_does_not_create_a_terminal_result(formal):
    pytester, result_dir = formal
    pytester.makepyfile('''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        def test_first(): pass
        def test_second(): pass
    ''')
    assert pytester.runpytest_inprocess('--collect-only', '-q').ret == 0
    assert not (result_dir / 'checkpoints/results.jsonl').exists()


@pytest.mark.parametrize('other', ['pass', "pytest.skip('unexplained')"])
def test_partial_policy_exclusion_is_not_a_whole_case_exemption(formal, other):
    pytester, result_dir = formal
    pytester.makepyfile(f'''
        import pytest
        pytestmark = [pytest.mark.case_id('FIXTURE-D3'), pytest.mark.stage('D3')]
        def test_first(): pytest.skip('SKIPPED_BY_POLICY: excluded')
        def test_second(): {other}
    ''')
    pytester.runpytest_inprocess('-q', '--junitxml=' + str(result_dir / 'junit.xml'))
    row = json.loads((result_dir / 'checkpoints/results.jsonl').read_text())
    assert row['result'] == runner.junit_outcome(result_dir / 'junit.xml')[0] == 'BLOCKED'


@pytest.fixture
def memory_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    (home / 'config').mkdir(parents=True)
    (home / 'config/secrets.env').write_text('# no memory secrets\n')
    (home / 'config/memory-mock.env').write_text(
        'NEXENT_EXTERNAL_MEMORY_PLUGIN="mem0"\n'
        'NEXENT_EXTERNAL_MEMORY_ENDPOINT=http://fixture:9090\n'
        'NEXENT_EXTERNAL_MEMORY_API_KEY="offline-fixture-value"\n')
    monkeypatch.setenv('NEXENT_TEST_HOME', str(home))
    monkeypatch.setattr(memory_mock, 'repo_root', lambda: ROOT)
    for key in ('NEXENT_EXTERNAL_MEMORY_PLUGIN', 'NEXENT_EXTERNAL_MEMORY_ENDPOINT', 'NEXENT_EXTERNAL_MEMORY_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    return home


def test_mock_config_loaded_without_export(memory_home):
    settings = memory_mock.memory_settings()
    assert settings['plugin'] == 'mem0'
    assert settings['endpoint'] == 'http://fixture:9090'
    assert settings['api_key'] == 'offline-fixture-value'


@pytest.mark.parametrize('source', ['secrets', 'export'])
def test_config_conflicts_are_errors_not_overrides(memory_home, monkeypatch, source):
    if source == 'secrets':
        (memory_home / 'config/secrets.env').write_text('NEXENT_EXTERNAL_MEMORY_API_KEY=another-fixture\n')
    else:
        monkeypatch.setenv('NEXENT_EXTERNAL_MEMORY_API_KEY', 'another-fixture')
    with pytest.raises(AssetDependencyError, match='Conflicting') as exc:
        memory_mock.memory_settings()
    assert 'another-fixture' not in str(exc.value) and 'offline-fixture-value' not in str(exc.value)


def test_optional_mock_file_not_required_for_existing_export(memory_home, monkeypatch):
    values = config.load_config_env('memory-mock.env')
    (memory_home / 'config/memory-mock.env').unlink()
    for key, value in values.items(): monkeypatch.setenv(key, value)
    assert memory_mock.memory_settings()['plugin'] == 'mem0'


@pytest.mark.asyncio
@pytest.mark.parametrize('outage', [False, True])
async def test_empty_memory_not_silently_reclassified_or_passed(monkeypatch, outage):
    health = AsyncMock(side_effect=AssetDependencyError('models', 'embedding', detail='offline') if outage else None)
    saved = []
    monkeypatch.setattr(memory, 'model_id', health)
    monkeypatch.setattr(memory, 'write_case_evidence', lambda name, data: saved.append(list(data)))
    with pytest.raises(AssertionError, match='Stored memory marker'):
        await memory._assert_memory_marker(SimpleNamespace(), False, [])
    health.assert_awaited_once()
    assert health.await_args.kwargs == {'force_health': True}
    assert saved[-1][-1]['outcome'] == ('unavailable' if outage else 'connected')
    assert saved[-1][-1]['causality'] == 'not_proven_by_later_probe'


@pytest.mark.asyncio
async def test_record_precheck_failure_does_not_write(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(memory, 'model_id', AsyncMock(side_effect=AssetDependencyError('models', 'embedding')))
    monkeypatch.setattr(memory, '_create_agent_memory', create)
    with pytest.raises(AssetDependencyError): await memory._memory_records(SimpleNamespace(), True)
    create.assert_not_awaited()


def test_quoted_config_key_in_trace_is_redacted():
    assert 'fixture-sensitive' not in plugin._redact_reason("{'api_key': 'fixture-sensitive'}")


@pytest.mark.asyncio
@pytest.mark.parametrize('retrieves', [True, False])
async def test_memory_record_poll_is_read_only_and_cleanup_is_verified(monkeypatch, retrieves):
    class API:
        marker = ''
        updates = searches = 0

        async def get(self, path, **kwargs):
            body = {'memory_id': 99} if path.endswith('/99') else [{'memory_id': 99}]
            return httpx.Response(200, json=body, request=httpx.Request('GET', 'http://fixture'))

        async def patch(self, path, json):
            self.updates += 1
            self.marker = json['content'].removeprefix('Updated ')
            return httpx.Response(200, json={}, request=httpx.Request('PATCH', 'http://fixture'))

        async def post(self, path, json):
            assert path == '/memory/records/search' and json['agent_id'] == '7'
            self.searches += 1
            body = [{'content': self.marker}] if retrieves and self.searches >= 2 else []
            return httpx.Response(200, json=body, request=httpx.Request('POST', 'http://fixture'))

    api = API()
    @asynccontextmanager
    async def client(*args, **kwargs): yield api

    identity = SimpleNamespace(access_token='offline-fixture')
    health, create, cleanup = AsyncMock(), AsyncMock(return_value=99), AsyncMock()
    monkeypatch.setattr(memory, 'model_id', health)
    monkeypatch.setattr(memory, '_create_agent_memory', create)
    monkeypatch.setattr(memory, 'cleanup_owned_memory', cleanup)
    monkeypatch.setattr(memory, 'client', client)
    monkeypatch.setattr(memory, 'get_test_asset', lambda *args: 7)
    monkeypatch.setattr(memory, 'write_case_evidence', lambda *args: None)
    monkeypatch.setattr(memory.asyncio, 'sleep', AsyncMock())
    if retrieves:
        await memory._memory_records(identity, True)
    else:
        with pytest.raises(AssertionError, match='Stored memory marker'):
            await memory._memory_records(identity, True)
    assert api.updates == 1 and api.searches == (2 if retrieves else 10)
    create.assert_awaited_once()
    assert create.await_args.kwargs['require_indexed'] is True
    cleanup.assert_awaited_once_with(identity, 99)
    assert health.await_count == (1 if retrieves else 2)
