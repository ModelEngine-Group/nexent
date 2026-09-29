from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from shared.config import repo_root

CASE_ID = 'DEP-AUTO-0E1DE34B7A6EA269'
NAMESPACE = 'nexent'
INFRA_RELEASE = 'nexent-infrastructure'
APP_RELEASE = 'nexent'
K8S_DIR = repo_root() / 'deploy' / 'k8s'
INFRA_COMPONENTS = ('nexent-elasticsearch', 'nexent-postgresql', 'nexent-redis', 'nexent-minio')


def _run(args, cwd=None):
    return subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run_script(script, *args):
    return _run(['bash', str(K8S_DIR / script), *args], cwd=str(K8S_DIR))


def _release_exists(name):
    return _run(['helm', 'status', name, '--namespace', NAMESPACE]).returncode == 0


def _helm_template(release, chart, values_files):
    args = ['helm', 'template', release, chart, '--namespace', NAMESPACE]
    for vf in values_files:
        args.extend(['-f', vf])
    return _run(args)


def _write_yaml(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


@pytest.mark.stage('D5')
@pytest.mark.case_id(CASE_ID)
def test_dep_auto_0e1de34b7a6ea269(tmp_path):
    if os.environ.get('D5_ISOLATED_K8S_ENVIRONMENT', '').lower() != 'true':
        pytest.skip('SKIPPED_BY_SAFETY: an isolated Kubernetes context is required')
    for tool in ('kubectl', 'helm', 'bash'):
        assert shutil.which(tool) is not None, 'required tool missing: ' + tool
    context = _run(['kubectl', 'config', 'current-context'])
    if context.returncode != 0 or not context.stdout.strip():
        pytest.skip('SKIPPED_BY_DEPENDENCY: Kubernetes context is not configured')
    if _release_exists(INFRA_RELEASE) or _release_exists(APP_RELEASE):
        pytest.skip('SKIPPED_BY_SAFETY: target Kubernetes namespace already has Nexent releases')

    chart_dir = str(K8S_DIR / 'helm' / 'nexent-infrastructure')

    # validate.yaml must reject every illegal value combination.
    illegal = {
        'replicas': '''nexent-elasticsearch:
  replicaCount: 2
''',
        'mode': '''nexent-elasticsearch:
  persistence:
    mode: invalid
''',
        'dynamic-no-sc': '''nexent-elasticsearch:
  persistence:
    mode: dynamic
''',
        'existing-no-claim': '''nexent-elasticsearch:
  persistence:
    mode: existing
''',
    }
    for name, content in illegal.items():
        vf = tmp_path / (name + '.yaml')
        _write_yaml(vf, content)
        result = _helm_template('validate-' + name, chart_dir, [str(vf)])
        assert result.returncode != 0, name + ' must be rejected by validate.yaml: ' + result.stderr

    # A legal single-replica local values set must render cleanly.
    legal = tmp_path / 'legal.yaml'
    _write_yaml(legal, '''nexent-elasticsearch:
  replicaCount: 1
  persistence:
    mode: local
''')
    result = _helm_template('validate-legal', chart_dir, [str(legal)])
    assert result.returncode == 0, 'legal values must render: ' + result.stderr

    # Deploy infrastructure release only.
    deploy = _run_script('deploy.sh', '--release-scope', 'infrastructure')
    assert deploy.returncode == 0, 'infrastructure deploy failed: ' + deploy.stdout + deploy.stderr
    for component in INFRA_COMPONENTS:
        ready = _run(['kubectl', 'get', 'deployment', component, '-n', NAMESPACE, '-o', 'jsonpath={.status.readyReplicas}'])
        assert ready.stdout.strip() == '1', component + ' is not ready'
    assert _release_exists(INFRA_RELEASE), 'infrastructure release missing'
    assert not _release_exists(APP_RELEASE), 'application release must not exist yet'

    # Deploy application release (triggers ES key initialization in the lifecycle).
    app_deploy = _run_script('deploy.sh', '--release-scope', 'nexent')
    assert app_deploy.returncode == 0, 'application deploy failed: ' + app_deploy.stdout + app_deploy.stderr
    assert _release_exists(APP_RELEASE), 'application release missing after deploy'

    # ES API key initialization must succeed and write a 0600 output file.
    es_key_file = tmp_path / 'es-api-key'
    env = dict(os.environ)
    env['ELASTICSEARCH_API_KEY_OUTPUT_FILE'] = str(es_key_file)
    init_es = subprocess.run(
        ['bash', str(K8S_DIR / 'init-elasticsearch.sh')],
        cwd=str(K8S_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert init_es.returncode == 0, 'ES key init failed: ' + init_es.stdout + init_es.stderr
    assert es_key_file.is_file(), 'ES API key output file was not created'
    key = es_key_file.read_text(encoding='utf-8').strip()
    assert key, 'ES API key output file is empty'
    assert (es_key_file.stat().st_mode & 0o777) == 0o600, 'ES API key file must be mode 0600'

    # Guard: uninstalling infrastructure while the application release exists is refused.
    guarded = _run_script('uninstall.sh', '--release-scope', 'infrastructure', '--keep-namespace')
    assert guarded.returncode != 0, 'infrastructure uninstall must be refused while app release exists'
    assert _release_exists(INFRA_RELEASE), 'infrastructure release must remain after refused uninstall'

    # Scope validation.
    bad_scope = _run_script('uninstall.sh', '--release-scope', 'bogus')
    assert bad_scope.returncode != 0, 'invalid release scope must be rejected'
    bad_ns = _run_script('uninstall.sh', '--release-scope', 'nexent', '--delete-namespace', 'true')
    assert bad_ns.returncode != 0, 'delete-namespace under non-all scope must be rejected'

    # Ordered uninstall: application first, then infrastructure.
    app_uninstall = _run_script('uninstall.sh', '--release-scope', 'nexent', '--keep-namespace')
    assert app_uninstall.returncode == 0, 'application uninstall failed: ' + app_uninstall.stdout + app_uninstall.stderr
    infra_uninstall = _run_script('uninstall.sh', '--release-scope', 'infrastructure', '--keep-namespace')
    assert infra_uninstall.returncode == 0, 'infrastructure uninstall failed: ' + infra_uninstall.stdout + infra_uninstall.stderr
    assert not _release_exists(APP_RELEASE), 'application release still present after uninstall'
    assert not _release_exists(INFRA_RELEASE), 'infrastructure release still present after uninstall'

    # Idempotent uninstall of an already-absent release returns 0.
    idempotent = _run_script('uninstall.sh', '--release-scope', 'all', '--keep-namespace')
    assert idempotent.returncode == 0, 'idempotent uninstall must return 0'
