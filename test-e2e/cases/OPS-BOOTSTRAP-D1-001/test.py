# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise deployment selection and startup with a controlled Compose boundary."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml


@pytest.mark.case_id('OPS-BOOTSTRAP-D1-001')
@pytest.mark.stage('D1')
@pytest.mark.be_ut
def test_ops_deployment_component(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    git = shutil.which('git')
    git_bash = Path(git).resolve().parent.parent / 'bin/bash.exe' if git else None
    bash = str(git_bash) if os.name == 'nt' and git_bash and git_bash.is_file() else shutil.which('bash')
    assert bash, 'Bash is required for the deployment component test'
    source = (repo / 'deploy/docker/deploy.sh').read_text(encoding='utf-8')
    function = re.search(r'^deploy_core_services\(\) \{\n.*?^\}', source, re.MULTILINE | re.DOTALL)
    assert function, 'The deployment entry must define deploy_core_services'
    harness = '''
source "$1/deploy/common/common.sh"
DEPLOYMENT_COMPONENTS="$2"
DEPLOYMENT_PORT_POLICY="$3"
deployment_compute_selection
if [ "$DEPLOYMENT_COMPONENTS" = application ]; then
  case " $DEPLOYMENT_SELECTED_HELM_CHARTS " in
    *" nexent-ops "*) ;; *) exit 90 ;;
  esac
else
  case " $DEPLOYMENT_SELECTED_HELM_CHARTS " in
    *" nexent-ops "*) exit 90 ;;
  esac
fi
ROOT_ENV_FILE=/controlled/env
COMPOSE_DIR=/controlled/compose
COMPOSE_FILE_SUFFIX="$4"
fake_compose() {
  printf 'ARG:%s\\n' "$@"
  return "$FAIL_COMPOSE"
}
docker_compose_command=fake_compose
'''
    harness += '\n' + function.group(0) + '\nFAIL_COMPOSE="$5"\ndeploy_core_services\n'
    for components, policy, suffix, failure in [
        ('application', 'development', '.yml', '0'),
        ('application', 'production', '.prod.yml', '0'),
        ('infrastructure', 'development', '.yml', '0'),
        ('application', 'development', '.yml', '17'),
    ]:
        result = subprocess.run(
            [bash, '--noprofile', '--norc', '-c', harness, 'ops-component',
             repo.as_posix(), components, policy, suffix, failure],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        args = [line.removeprefix('ARG:') for line in result.stdout.splitlines() if line.startswith('ARG:')]
        if components == 'infrastructure':
            assert result.returncode == 0, result.stderr
            assert args == []
        else:
            assert args[:8] == [
                '--env-file', '/controlled/env', '-p', 'nexent', '-f',
                f'/controlled/compose/docker-compose{suffix}', 'up', '-d',
            ]
            assert 'nexent-ops' in args[8:]
            assert 'nexent-runtime' in args[8:]
            assert 'nexent-elasticsearch' not in args[8:]
            assert result.returncode == (1 if failure != '0' else 0), result.stdout + result.stderr
    verify_helm_component(repo, bash, tmp_path)
    verify_k8s_readiness(repo, bash)


def verify_helm_component(repo, bash, tmp_path):
    """Render actual chart dependencies with the real generated values."""
    helm = shutil.which('helm')
    assert helm, 'Helm 3 must be on PATH for ops deployment composition proof'
    chart = repo / 'deploy/k8s/helm/nexent'
    values_path = tmp_path / 'ops-values.yaml'
    application_checksum = None
    script = '''
set -e
source "$1/deploy/common/common.sh"
DEPLOYMENT_COMPONENTS="$2"
DEPLOYMENT_PORT_POLICY=production
DEPLOYMENT_IMAGE_SOURCE=general
DEPLOYMENT_APP_VERSION=latest
deployment_apply_image_source
NEXENT_IMAGE=example.invalid/shared/backend:ops-check
OPS_PORT=15016
LOG_LEVEL=DEBUG
deployment_render_helm_chart_values
'''
    for component in ('application', 'infrastructure'):
        result = subprocess.run(
            [bash, '--noprofile', '--norc', '-c', script, 'ops-render', repo.as_posix(), component],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        assert result.returncode == 0, result.stderr
        values = yaml.safe_load(result.stdout)
        values['global'] = {'namespace': 'ops-proof', 'rolloutChecksums': {'backendImage': 'image-rev-1'}}
        values_path.write_text(yaml.safe_dump(values), encoding='utf-8')
        rendered = subprocess.run(
            [helm, 'template', 'ops-proof', str(chart), '-f', str(values_path)],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        assert rendered.returncode == 0, rendered.stderr
        documents = [doc for doc in yaml.safe_load_all(rendered.stdout) if isinstance(doc, dict)]
        ops = {doc['kind']: doc for doc in documents if doc.get('metadata', {}).get('name') == 'nexent-ops'}
        if component == 'infrastructure':
            assert ops == {}
            continue
        assert set(ops) == {'Deployment', 'Service'}
        deployment, service = ops['Deployment'], ops['Service']
        assert deployment['metadata']['namespace'] == service['metadata']['namespace'] == 'ops-proof'
        pod = deployment['spec']['template']
        assert pod['metadata']['annotations']['checksum/nexent-backend-image'] == 'image-rev-1'
        assert len(pod['metadata']['annotations']['checksum/ops-config']) == 64
        application_checksum = pod['metadata']['annotations']['checksum/ops-config']
        spec = pod['spec']
        assert spec['automountServiceAccountToken'] is False
        assert not spec.get('initContainers')
        assert spec['volumes'] == [{'name': 'ops-logs', 'persistentVolumeClaim': {'claimName': 'nexent-logs'}}]
        assert len(spec['containers']) == 1
        container = spec['containers'][0]
        assert container['image'] == 'example.invalid/shared/backend:ops-check'
        assert container['command'] == ['/opt/nexent/scripts/start-backend.sh', 'python', 'backend/ops_service.py']
        assert not container.get('envFrom')
        assert container['volumeMounts'] == [{'name': 'ops-logs', 'mountPath': '/mnt/nexent-data/logs'}]
        assert next(env for env in container['env'] if env['name'] == 'POD_NAME')['valueFrom']['fieldRef']['fieldPath'] == 'metadata.name'
        assert {env['name']: env['value'] for env in container['env'] if 'value' in env} == {
            'OPS_PORT': '15016',
            'LOG_DIR': '/mnt/nexent-data/logs/$(POD_NAME)',
            'NEXENT_SQL_STARTUP_MODE': 'off', 'PYTHON_DOTENV_DISABLED': '1',
        }
        for name in ('LOG_LEVEL', 'IS_DEBUG', 'LOG_MAX_BYTES', 'LOG_ROTATION_INTERVAL', 'LOG_BACKUP_COUNT'):
            assert next(env for env in container['env'] if env['name'] == name)['valueFrom']['secretKeyRef'] == {
                'name': 'nexent-env', 'key': name, 'optional': True,
            }
        assert container['ports'] == [{'name': 'http', 'containerPort': 15016}]
        assert container['startupProbe']['httpGet'] == {'path': '/health/live', 'port': 'http'}
        assert container['livenessProbe']['httpGet'] == {'path': '/health/live', 'port': 'http'}
        assert container['readinessProbe']['httpGet'] == {'path': '/health/ready', 'port': 'http'}
        assert deployment['spec']['selector']['matchLabels'] == pod['metadata']['labels'] == service['spec']['selector']
        assert service['spec']['type'] == 'NodePort'
        assert service['spec']['ports'] == [{'name': 'http', 'port': 15016, 'targetPort': 'http', 'nodePort': 30016}]

    ops_chart = chart / 'charts/nexent-ops'
    internal = subprocess.run(
        [helm, 'template', 'ops-proof', str(ops_chart), '--namespace', 'ops-proof',
         '--set', 'service.type=ClusterIP'],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert internal.returncode == 0, internal.stderr
    internal_docs = list(yaml.safe_load_all(internal.stdout))
    internal_service = next(doc for doc in internal_docs if doc['kind'] == 'Service')
    internal_deployment = next(doc for doc in internal_docs if doc['kind'] == 'Deployment')
    assert internal_service['spec']['type'] == 'ClusterIP'
    assert 'nodePort' not in internal_service['spec']['ports'][0]
    assert internal_deployment['spec']['template']['metadata']['annotations']['checksum/ops-config'] != application_checksum
    for setting in ('service.port=0', 'service.port=65536', 'service.nodePort=29999', 'replicaCount=0'):
        invalid = subprocess.run(
            [helm, 'template', 'ops-proof', str(ops_chart), '--set', setting],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        assert invalid.returncode != 0, setting
        assert setting.split('=')[0].split('.')[-1] in invalid.stderr


def verify_k8s_readiness(repo, bash):
    """Exercise actual readiness selection while controlling the cluster boundary."""
    source = (repo / 'deploy/k8s/deploy.sh').read_text(encoding='utf-8')
    function = re.search(r'^wait_for_nexent_ready\(\) \{\n.*?^\}', source, re.MULTILINE | re.DOTALL)
    assert function
    script = '''
source "$1/deploy/common/common.sh"
DEPLOYMENT_COMPONENTS="$2"
K8S_WAIT_TIMEOUT_SECONDS=1
wait_for_deployment_ready() {
  printf 'WAIT:%s\\n' "$1"
  [ "$1" != "$FAIL_DEPLOYMENT" ]
}
'''
    script += '\n' + function.group(0) + '\nFAIL_DEPLOYMENT="$3"\nwait_for_nexent_ready\n'
    for component, failing in [('application', ''), ('application', 'nexent-ops'), ('infrastructure', '')]:
        result = subprocess.run(
            [bash, '--noprofile', '--norc', '-c', script, 'ops-wait', repo.as_posix(), component, failing],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        waits = [line for line in result.stdout.splitlines() if line.startswith('WAIT:')]
        assert ('WAIT:nexent-ops' in waits) is (component == 'application')
        assert result.returncode == (1 if failing else 0), result.stdout + result.stderr
