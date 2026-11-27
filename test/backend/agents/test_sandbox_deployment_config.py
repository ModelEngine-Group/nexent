# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Render Helm configuration locally; never contact or deploy a Kubernetes cluster."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / 'deploy/k8s/helm/nexent'
HELM = shutil.which('helm')
pytestmark = pytest.mark.skipif(HELM is None, reason='Helm CLI is required for local template verification')


def render(*options):
    return subprocess.run([
        HELM, 'template', 't01-test', str(CHART),
        '--set-string', 'nexent-common.secrets.jwtSecret=t01-public-test-value',
        # Rendering proves structure only; this fixture never certifies a CNI.
        '--set', 'global.sandboxNetworkPolicyVerified=true', *options,
    ], capture_output=True, text=True, encoding='utf-8', timeout=20, check=False)


@pytest.mark.parametrize('provider,mode,level', [
    ('docker', 'lightweight', 'docker'), ('kubernetes', 'lightweight', 'kubernetes'),
    ('kubernetes', 'disabled', 'local'),
])
def test_provider_identity_and_default_runtime_replicas(provider, mode, level):
    result = render('--set', f'global.sandboxProvider={provider}', '--set', f'global.sandboxMode={mode}',
                    '--set', 'global.sharedStorage.mode=existing')
    assert result.returncode == 0, result.stderr
    objects = list(yaml.safe_load_all(result.stdout))
    runtime = next(o for o in objects if o and o.get('kind') == 'Deployment' and o['metadata']['name'] == 'nexent-runtime')
    chart_values = yaml.safe_load((CHART / 'values.yaml').read_text(encoding='utf-8'))
    assert runtime['spec']['replicas'] == chart_values['nexent-runtime']['replicaCount']
    assert runtime['spec']['strategy']['type'] == 'Recreate'
    env = {e['name']: e for e in runtime['spec']['template']['spec']['containers'][0]['env']}
    assert env['NEXENT_SANDBOX_DEFAULT_LEVEL']['value'] == level
    assert env['NEXENT_SANDBOX_ENABLED']['value'] == ('false' if mode == 'disabled' else 'true')
    assert env['NEXENT_RUNTIME_DEPLOYMENT_ID']['value'] == 't01-test'
    assert env['NEXENT_RUNTIME_POD_UID']['valueFrom']['fieldRef']['fieldPath'] == 'metadata.uid'
    assert env['NEXENT_RUNTIME_POD_NAMESPACE']['valueFrom']['fieldRef']['fieldPath'] == 'metadata.namespace'
    if provider == 'kubernetes':
        assert env['NEXENT_SANDBOX_FAILURE_POLICY']['value'] == 'error'
        assert env['NEXENT_SANDBOX_DEFAULT_SCOPE']['value'] == 'system'


@pytest.mark.parametrize('override,error', [
    ('nexent-runtime.replicaCount=2,global.sharedStorage.mode=local',
     'requires dynamic or existing shared RWX storage'),
    ('nexent-runtime.strategy.type=RollingUpdate', 'Recreate'),
    ('global.sandboxProvider=invalid', 'sandboxProvider'),
])
def test_invalid_provider_or_unsafe_deployment_is_still_rejected(override, error):
    result = render('--set', override)
    assert result.returncode != 0
    assert error in result.stderr


def test_kubernetes_local_storage_requires_explicit_development_exception():
    local_storage = ('--set', 'global.sandboxProvider=kubernetes,global.sandboxMode=lightweight,'
                     'global.sharedStorage.mode=local,'
                     'nexent-runtime.replicaCount=1,global.sandboxSingleNodeDevelopment=false')
    result = render(*local_storage)
    assert result.returncode != 0 and 'verified CSI RWX' in result.stderr
    result = render(*local_storage, '--set', 'global.sandboxSingleNodeDevelopment=true')
    assert result.returncode == 0, result.stderr


def test_unverified_network_policy_cannot_enable_a_kubernetes_sandbox():
    sandbox = ('--set', 'global.sandboxProvider=kubernetes,global.sandboxMode=lightweight,'
               'global.sharedStorage.mode=existing')
    result = render(*sandbox, '--set', 'global.sandboxNetworkPolicyVerified=false')
    assert result.returncode != 0
    assert 'enforced NetworkPolicy' in result.stderr
    result = render(*sandbox, '--set-string', 'global.sandboxNetworkPolicyVerified=false')
    assert result.returncode != 0 and 'must be a boolean' in result.stderr


def test_kubernetes_rbac_and_network_policy_are_scoped_to_execution():
    result = render('--set', 'global.sandboxProvider=kubernetes', '--set', 'global.sharedStorage.mode=existing')
    assert result.returncode == 0, result.stderr
    objects = [o for o in yaml.safe_load_all(result.stdout) if o]
    role = next(o for o in objects if o['kind'] == 'Role' and o['metadata']['name'] == 'nexent-runtime-sandbox')
    assert not any('secrets' in rule['resources'] or '*' in rule['verbs'] for rule in role['rules'])
    assert any(rule['resources'] == ['pods/exec'] and rule['verbs'] == ['get', 'create'] for rule in role['rules'])
    assert not any(o['kind'] == 'ClusterRole' and o['metadata']['name'] == 'nexent-runtime-sandbox' for o in objects)
    policy = next(o for o in objects if o['kind'] == 'NetworkPolicy' and o['metadata']['name'] == 'nexent-sandbox-control')
    assert policy['spec']['podSelector']['matchLabels'] == {'nexent.ai/sandbox': 'system'}
    assert policy['spec']['ingress'][0]['ports'] == [{'protocol': 'TCP', 'port': 8080}]
    assert policy['spec']['egress'][1]['ports'] == [{'protocol': 'TCP', 'port': 5014}]


def test_disabled_kubernetes_sandbox_retains_owner_cleanup_without_creating_business_resources():
    result = render('--set', 'global.sandboxProvider=kubernetes', '--set', 'global.sandboxMode=disabled')
    assert result.returncode == 0, result.stderr
    objects = [o for o in yaml.safe_load_all(result.stdout) if o]
    role = next(o for o in objects if o['kind'] == 'Role' and o['metadata']['name'] == 'nexent-runtime-sandbox')
    assert any('pods' in rule['resources'] and 'delete' in rule['verbs'] for rule in role['rules'])
    assert all('secrets' not in rule['resources'] for rule in role['rules'])
    assert not any(o['kind'] == 'NetworkPolicy' for o in objects)


def test_kubernetes_runtime_has_no_dedicated_drain_hook_credential_or_exit_budget():
    result = render('--set', 'global.sandboxProvider=kubernetes', '--set', 'global.sandboxSingleNodeDevelopment=true')
    assert result.returncode == 0, result.stderr
    objects = [o for o in yaml.safe_load_all(result.stdout) if o]
    assert not any(o['kind'] == 'Secret' and o['metadata']['name'] == 'nexent-runtime-drain' for o in objects)
    runtime = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'nexent-runtime')
    pod = runtime['spec']['template']['spec']
    container = pod['containers'][0]
    env = {entry['name']: entry for entry in container['env']}
    assert 'NEXENT_RUNTIME_DRAIN_TOKEN' not in env
    assert 'RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS' not in env
    assert 'lifecycle' not in container
    assert 'terminationGracePeriodSeconds' not in pod
    assert not any(entry['name'] == 'NEXENT_RUNTIME_DRAIN_TOKEN' for entry in pod['initContainers'][0].get('env', []))
