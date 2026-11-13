# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Owned single-node verification resources; never replace a developer stack."""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from kubernetes import client, config
from kubernetes.stream import stream


def verification_image(repo, evidence):
    tracked = subprocess.run(['git', 'ls-files', 'backend', 'sdk/nexent'], cwd=repo,
                             capture_output=True, text=True, check=True).stdout.splitlines()
    owned = list((repo / 'backend/runtime').glob('*.py'))
    owned += [repo / 'backend/runtime/api/sandbox.py', repo / 'backend/management/db/runtime_recovery.py']
    owned += list((repo / 'sdk/nexent/core/agents').glob('sandbox_*.py'))
    paths = sorted(set(tracked + [p.relative_to(repo).as_posix() for p in owned if p.is_file()]))
    manifest = {rel: hashlib.sha256((repo / rel).read_bytes()).hexdigest() for rel in paths
                if (repo / rel).is_file() and '.env' not in Path(rel).name and not rel.endswith('.pyc')}
    base = os.environ.get('NEXENT_KSM_RUNTIME_BASE', 'nexent/nexent:v2.8.4')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:@-' for c in base):
        raise ValueError('Verification base must be a plain OCI image reference')
    base_id = subprocess.run(['docker', 'image', 'inspect', base, '--format', '{{.Id}}'],
                             capture_output=True, text=True, check=True).stdout.strip()
    fingerprint = hashlib.sha256(json.dumps([base_id, manifest], sort_keys=True).encode()).hexdigest()
    image = 'nexent/ksm-verification:' + fingerprint[:20]
    present = subprocess.run(['docker', 'image', 'inspect', image, '--format',
                              '{{index .Config.Labels "nexent.ksm.source"}}'], capture_output=True, text=True)
    if present.returncode or present.stdout.strip() != fingerprint:
        scratch_root = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(prefix='nexent-ksm-build-', dir=scratch_root) as scratch:
            target = Path(scratch).resolve()
            if target.parent != scratch_root:
                raise RuntimeError('Verification build cleanup escaped its owned scratch root')
            for rel in manifest:
                destination = target / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo / rel, destination)
            (target / 'Dockerfile').write_text(
                f'FROM {base}\nCOPY backend/ /opt/backend/\n'
                'COPY sdk/nexent/ /opt/verification-sdk/nexent/\n'
                'ENV PYTHONPATH=/opt/verification-sdk:/opt/backend\n'
                f'LABEL nexent.ksm.source="{fingerprint}"\n', encoding='utf-8')
            completed = subprocess.run(['docker', 'build', '--pull=false', '-q', '-t', image, str(target)],
                                       capture_output=True, text=True, timeout=300)
            if completed.returncode:
                raise RuntimeError('Owned verification image build failed')
    (evidence / 'sources.json').write_text(json.dumps({'image': image, 'base_id': base_id,
        'fingerprint': fingerprint, 'files': manifest,
        'fixture_sha256': hashlib.sha256(Path(__file__).with_name('ksm_runtime_fixture.py').read_bytes()).hexdigest()},
        indent=2), encoding='utf-8')
    return image


def run_owned_runtime_probe(repo, evidence):
    evidence.mkdir(parents=True, exist_ok=True)
    config.load_kube_config(context=os.environ.get('NEXENT_KSM_KUBE_CONTEXT', 'docker-desktop'))
    image = verification_image(repo, evidence)
    namespace = 'nexent-ksm-core-' + uuid.uuid4().hex[:8]
    receipt = {'proof': 'controlled-model real Runtime/Agent/Kubernetes boundary; no full S1 claim',
               'namespace': namespace, 'image': image, 'runtimes': {}}
    with client.ApiClient() as transport:
        api, rbac = client.CoreV1Api(transport), client.RbacAuthorizationV1Api(transport)
        api.create_namespace({'metadata': {'name': namespace, 'labels': {'nexent-test-owner': namespace}}})
        try:
            api.create_namespaced_config_map(namespace, {'metadata': {'name': 'runtime-fixture'}, 'data': {'runtime_fixture.py': Path(__file__).with_name('ksm_runtime_fixture.py').read_text(encoding='utf-8')}})
            api.create_namespaced_service_account(namespace, {'metadata': {'name': 'runtime'}})
            rbac.create_namespaced_role(namespace, {'metadata': {'name': 'runtime'}, 'rules': [
                {'apiGroups': [''], 'resources': ['pods', 'services'], 'verbs': ['get', 'list', 'watch', 'create', 'delete']},
                {'apiGroups': [''], 'resources': ['pods/exec'], 'verbs': ['get', 'create']},
                {'apiGroups': [''], 'resources': ['persistentvolumeclaims'], 'verbs': ['get']}]})
            rbac.create_namespaced_role_binding(namespace, {'metadata': {'name': 'runtime'},
                'subjects': [{'kind': 'ServiceAccount', 'name': 'runtime', 'namespace': namespace}],
                'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'runtime'}})
            api.create_namespaced_persistent_volume_claim(namespace, {'metadata': {'name': 'workspace'},
                'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'hostpath',
                         'resources': {'requests': {'storage': '1Gi'}}}})
            api.create_namespaced_service(namespace, {'metadata': {'name': 'redis'}, 'spec': {
                'selector': {'app': 'redis'}, 'ports': [{'port': 6379, 'targetPort': 6379}]}})
            api.create_namespaced_pod(namespace, {'metadata': {'name': 'redis', 'labels': {'app': 'redis'}},
                'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'redis', 'image': 'redis:alpine', 'imagePullPolicy': 'IfNotPresent',
                        'args': ['redis-server', '--save', '', '--appendonly', 'no'],
                        'resources': {'limits': {'memory': '128Mi', 'cpu': '0.5'}}}]}})
            for name in ('runtime-a', 'runtime-b'):
                values = {'IS_DEPLOYED_BY_KUBERNETES': 'true', 'NEXENT_SANDBOX_PROVIDER': 'kubernetes',
                    'NEXENT_SANDBOX_ENABLED': 'true', 'NEXENT_SANDBOX_DEFAULT_LEVEL': 'kubernetes',
                    'NEXENT_SANDBOX_DEFAULT_SCOPE': 'system', 'NEXENT_SANDBOX_FAILURE_POLICY': 'error',
                    'NEXENT_RUNTIME_DEPLOYMENT_ID': namespace, 'KUBERNETES_NAMESPACE': namespace,
                    'NEXENT_RUNTIME_CONTAINER_NAME': 'nexent-runtime',
                    'RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS': '8', 'AGENT_AUTOMATION_ENABLED': 'false',
                    'RUNTIME_STATE_REDIS_URL': 'redis://redis:6379/0', 'REDIS_URL': 'redis://redis:6379/0',
                    'AGENT_WORKSPACE_ROOT': '/mnt/nexent/workdir', 'NEXENT_SANDBOX_WORKSPACE_MOUNT': '/mnt/nexent',
                    'NEXENT_SANDBOX_WORKSPACE_CLAIM': 'workspace', 'NEXENT_SANDBOX_SINGLE_NODE_DEVELOPMENT': 'true',
                    'NEXENT_SANDBOX_DOCKER_IMAGE': os.environ.get('NEXENT_KSM_SANDBOX_IMAGE', 'nexent/nexent-sandbox-full:latest'),
                    'NEXENT_SANDBOX_NETWORK': 'enabled' if name == 'runtime-b' else 'disabled',
                    'JWT_SECRET': secrets.token_hex(32), 'ENABLE_TELEMETRY': 'false'}
                env = [{'name': k, 'value': v} for k, v in values.items()]
                env += [{'name': key, 'valueFrom': {'fieldRef': {'fieldPath': field}}} for key, field in [
                    ('NEXENT_RUNTIME_POD_NAME', 'metadata.name'), ('NEXENT_RUNTIME_POD_NAMESPACE', 'metadata.namespace'),
                    ('NEXENT_RUNTIME_POD_UID', 'metadata.uid'), ('NEXENT_RUNTIME_POD_IP', 'status.podIP')]]
                api.create_namespaced_pod(namespace, {'metadata': {'name': name, 'labels': {'app': 'nexent-runtime'}},
                    'spec': {'enableServiceLinks': False, 'serviceAccountName': 'runtime', 'restartPolicy': 'Never',
                        'initContainers': [{'name': 'permissions', 'image': image, 'imagePullPolicy': 'Never',
                            'command': ['python', '-c', "import os;os.chown('/mnt/nexent',-1,1000);os.chmod('/mnt/nexent',0o2775)"],
                            'volumeMounts': [{'name': 'workspace', 'mountPath': '/mnt/nexent'}]}],
                        'containers': [{'name': 'nexent-runtime', 'image': image, 'imagePullPolicy': 'Never',
                            'command': ['python', '/probe/runtime_fixture.py'], 'env': env,
                            'resources': {'limits': {'memory': '1200Mi', 'cpu': '1'}},
                            'volumeMounts': [{'name': 'workspace', 'mountPath': '/mnt/nexent'}, {'name': 'probe', 'mountPath': '/probe', 'readOnly': True}],
                            'readinessProbe': {'httpGet': {'path': '/health/ready', 'port': 5014}, 'periodSeconds': 2}}],
                        'volumes': [{'name': 'workspace', 'persistentVolumeClaim': {'claimName': 'workspace'}}, {'name': 'probe', 'configMap': {'name': 'runtime-fixture'}}]}})
                deadline = time.monotonic() + 100
                while True:
                    pod = api.read_namespaced_pod(name, namespace)
                    if any(c.type == 'Ready' and c.status == 'True' for c in pod.status.conditions or []):
                        break
                    if pod.status.phase in ('Failed', 'Succeeded') or time.monotonic() >= deadline:
                        print(api.read_namespaced_pod_log(name, namespace, container='nexent-runtime', tail_lines=60))
                        raise RuntimeError('Current Runtime startup failed: ' + name)
                    time.sleep(0.5)
                receipt['runtimes'][name] = {'uid': pod.metadata.uid, 'ready': True, 'node': pod.spec.node_name}
                print(name + ' CURRENT_RUNTIME_READY', flush=True)
            assert len({value['node'] for value in receipt['runtimes'].values()}) == 1
            assert not api.list_namespaced_pod(namespace, label_selector='nexent.ai/sandbox=system').items
            receipt['core_agents'] = {}
            core_program = "import urllib.request;request=urllib.request.Request('http://127.0.0.1:5014/__ksm/core',data=b'');response=urllib.request.urlopen(request,timeout=240);print(response.read().decode())"
            def execute_core(name):
                with client.ApiClient() as peer_transport:
                    peer = client.CoreV1Api(peer_transport)
                    ws = stream(peer.connect_get_namespaced_pod_exec,name,namespace,container='nexent-runtime',command=['python','-c',core_program],stderr=True,stdout=True,stdin=False,tty=False,_preload_content=False)
                    result, errors = '', ''
                    try:
                        while ws.is_open():
                            ws.update(timeout=1)
                            result += ws.read_stdout()
                            errors += ws.read_stderr()
                        result += ws.read_stdout()
                        errors += ws.read_stderr()
                        if ws.returncode != 0:
                            print(api.read_namespaced_pod_log(name,namespace,container='nexent-runtime',tail_lines=60))
                        assert ws.returncode == 0, errors
                    finally:
                        ws.close()
                return json.loads(result)
            import asyncio

            from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
            manager = ThreadManager('ksm-host-probe', {'control-io': LanePolicy('control-io', 2, 0)})
            manager.start()
            try:
                pending = {name: manager.submit('control-io', ManagedTaskSpec(task_name='owner-core-probe', owner='ksm-test'), execute_core, name).future for name in ('runtime-a','runtime-b')}
                for name, future in pending.items():
                    receipt['core_agents'][name] = future.result(timeout=240)
                    print(name + ' CORE_AGENT_PROBE_OK ' + json.dumps(receipt['core_agents'][name]), flush=True)
            finally:
                asyncio.run(manager.shutdown(timeout=5))
            assert len(api.list_namespaced_pod(namespace,label_selector='nexent.ai/sandbox=system').items) == 2
        finally:
            ns = api.read_namespace(namespace)
            assert ns.metadata.labels.get('nexent-test-owner') == namespace
            api.delete_namespace(namespace, body={'preconditions': {'uid': ns.metadata.uid}})
            receipt['owned_namespace_delete_requested'] = True
            cleanup_deadline = time.monotonic() + 90
            while True:
                try:
                    api.read_namespace(namespace)
                except client.ApiException as exc:
                    if exc.status == 404:
                        receipt['owned_namespace_removed'] = True
                        break
                    raise
                if time.monotonic() >= cleanup_deadline:
                    raise RuntimeError('Owned namespace cleanup did not complete')
                time.sleep(0.2)
            (evidence / 'result.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            print('Owned Runtime probe namespace deletion requested', flush=True)
    return receipt
