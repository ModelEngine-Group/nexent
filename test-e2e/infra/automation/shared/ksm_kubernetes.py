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
from copy import deepcopy
from pathlib import Path

from kubernetes import client, config
from kubernetes.stream import stream


def verification_image(repo, evidence):
    tracked = subprocess.run(['git', 'ls-files', 'backend', 'infrastructure', 'sdk/nexent'], cwd=repo,
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
                f'FROM {base}\nCOPY backend/ /opt/verification-tree/backend/\n'
                'COPY infrastructure/ /opt/verification-tree/infrastructure/\n'
                'COPY sdk/nexent/ /opt/verification-sdk/nexent/\n'
                'ENV PYTHONPATH=/opt/verification-sdk:/opt/verification-tree:/opt/verification-tree/backend\n'
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


def run_owned_runtime_probe(repo, evidence, *, scenario='core', runtime_overlay=None):
    if scenario not in {'core', 'w01', 'files', 'security', 'multiruntime', 'group2', 'group2-exit', 'group2-invalid', 'group2-memory'}:
        raise ValueError('Unknown Kubernetes verification scenario')
    runtime_names = ('runtime-a', 'runtime-b') if scenario in {'core', 'files', 'multiruntime'} else ('runtime-a',)
    evidence.mkdir(parents=True, exist_ok=True)
    config.load_kube_config(context=os.environ.get('NEXENT_KSM_KUBE_CONTEXT', 'docker-desktop'))
    fixture = Path(__file__).with_name('ksm_runtime_fixture.py')
    data = {'runtime_fixture.py': fixture.read_text(encoding='utf-8')}
    if scenario.startswith('group2'):
        data['ksm_group2_fixture.py'] = fixture.with_name('ksm_group2_fixture.py').read_text(encoding='utf-8')
    mounts = [{'name': 'probe', 'mountPath': '/probe', 'readOnly': True}]
    if runtime_overlay is None:
        image = verification_image(repo, evidence)
    else:
        image = os.environ['NEXENT_KSM_RUNTIME_BASE']
        hashes = {}
        for index, path in enumerate(runtime_overlay):
            source = (repo / path).resolve()
            if source.is_relative_to((repo / 'backend').resolve()):
                destination = '/opt/backend/' + source.relative_to(repo / 'backend').as_posix()
            else:
                relative = source.relative_to((repo / 'sdk/nexent').resolve())
                destination = '/opt/backend/.venv/lib/python3.11/site-packages/nexent/' + relative.as_posix()
            key = f'overlay-{index}.py'
            data[key] = source.read_text(encoding='utf-8')
            hashes[path] = hashlib.sha256(data[key].encode()).hexdigest()
            mounts.append({'name': 'probe', 'mountPath': destination,
                           'subPath': key, 'readOnly': True})
        (evidence / 'sources.json').write_text(json.dumps({'image': image, 'overlay': hashes,
            'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest()}, indent=2), encoding='utf-8')
    namespace = 'nexent-ksm-core-' + uuid.uuid4().hex[:8]
    if scenario.startswith('group2'):
        source_path = evidence / 'sources.json'
        sources = json.loads(source_path.read_text(encoding='utf-8'))
        sources['group2_fixture_sha256'] = hashlib.sha256(data['ksm_group2_fixture.py'].encode()).hexdigest()
        source_path.write_text(json.dumps(sources, indent=2), encoding='utf-8')
    receipt = {'proof': 'controlled-model real Runtime/Agent/Kubernetes boundary; no full S1 claim',
               'namespace': namespace, 'image': image, 'runtimes': {}}
    with client.ApiClient() as transport:
        api, rbac = client.CoreV1Api(transport), client.RbacAuthorizationV1Api(transport)
        api.create_namespace({'metadata': {'name': namespace, 'labels': {'nexent-test-owner': namespace}}})
        try:
            api.create_namespaced_config_map(namespace, {'metadata': {'name': 'runtime-fixture'}, 'data': data})
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
                'spec': {'restartPolicy': 'Never', 'serviceAccountName': 'runtime', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'redis', 'image': 'redis:alpine', 'imagePullPolicy': 'IfNotPresent',
                        'args': ['redis-server', '--save', '', '--appendonly', 'no'],
                        'resources': {'limits': {'memory': '128Mi', 'cpu': '0.5'}}}]}})
            if scenario == 'group2':
                # Disposable object storage; no credentials or data from the developer stack.
                api.create_namespaced_service(namespace, {'metadata': {'name': 'minio'}, 'spec': {
                    'selector': {'app': 'minio'}, 'ports': [{'port': 9000, 'targetPort': 9000}]}})
                api.create_namespaced_pod(namespace, {'metadata': {'name': 'minio', 'labels': {'app': 'minio'}},
                    'spec': {'restartPolicy': 'Never', 'serviceAccountName': 'runtime', 'automountServiceAccountToken': False,
                        'containers': [{'name': 'minio',
                            'image': 'quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z',
                            'imagePullPolicy': 'IfNotPresent', 'args': ['server', '/data'],
                            'env': [{'name': 'MINIO_ROOT_USER', 'value': 'ksm-fixture'},
                                    {'name': 'MINIO_ROOT_PASSWORD', 'value': 'ksm-disposable-only'}],
                            'resources': {'limits': {'memory': '256Mi', 'cpu': '0.5'}},
                            'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
                        'volumes': [{'name': 'data', 'emptyDir': {}}]}})
            for name in runtime_names:
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
                    'JWT_SECRET': secrets.token_hex(32), 'ENABLE_TELEMETRY': 'false',
                    'GATEWAY_AUTH_ENABLED': 'true'}
                if runtime_overlay is not None:
                    values['PYTHONPATH'] = '/opt/backend'
                if scenario == 'group2-memory':
                    values['NEXENT_SANDBOX_MEMORY_LIMIT_MB'] = '192'
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
                            'volumeMounts': [{'name': 'workspace', 'mountPath': '/mnt/nexent'}, *mounts],
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
                receipt['runtimes'][name] = {'uid': pod.metadata.uid, 'ready': True, 'node': pod.spec.node_name,
                                             'image_id': pod.status.container_statuses[0].image_id}
                print(name + ' CURRENT_RUNTIME_READY', flush=True)
            assert len({value['node'] for value in receipt['runtimes'].values()}) == 1
            assert not api.list_namespaced_pod(namespace, label_selector='nexent.ai/sandbox=system').items
            if scenario in {'group2', 'group2-invalid'}:
                invalid = deepcopy(api.read_namespaced_pod('runtime-a', namespace).spec)
                invalid.containers[0].env.append(client.V1EnvVar(name='NEXENT_SANDBOX_EXECUTION_UID', value='0'))
                api.create_namespaced_pod(namespace, client.V1Pod(
                    metadata=client.V1ObjectMeta(name='invalid-runtime'), spec=invalid))
                deadline = time.monotonic() + 45
                while True:
                    pod = api.read_namespaced_pod('invalid-runtime', namespace)
                    if any(c.type == 'Ready' and c.status == 'True' for c in pod.status.conditions or []):
                        probe = ('import json,os,urllib.request;'
                            'from runtime.adapters.nexent.sandbox import get_runtime_sandbox_options;'
                            'r={"execution_uid":int(os.environ["NEXENT_SANDBOX_EXECUTION_UID"]),'
                            '"readiness_status":urllib.request.urlopen("http://127.0.0.1:5014/health/ready").status};'
                            '\ntry: get_runtime_sandbox_options()\n'
                            'except Exception as e: r["policy_error"]=type(e).__name__\n'
                            'print("KSM_POLICY_RESULT="+json.dumps(r))')
                        with client.ApiClient() as peer_transport:
                            ws = stream(client.CoreV1Api(peer_transport).connect_get_namespaced_pod_exec,
                                'invalid-runtime', namespace, container='nexent-runtime',
                                command=['python', '-c', probe], stderr=True, stdout=True, stdin=False, tty=False,
                                _preload_content=False)
                            try:
                                ws.run_forever(timeout=30)
                                output = ws.read_stdout()
                                assert ws.returncode == 0, ws.read_stderr()
                            finally:
                                ws.close()
                        payload = next(line.split('=', 1)[1] for line in output.splitlines()
                                       if line.startswith('KSM_POLICY_RESULT='))
                        actual = json.loads(payload)
                        pods = api.list_namespaced_pod(namespace, label_selector='nexent.ai/sandbox=system').items
                        valid = actual['execution_uid'] == 0 and actual.get('policy_error') == 'ValueError' and not pods
                        # Runtime readiness intentionally retains its existing process/coordination contract.
                        receipt['invalid_config'] = {'status': 'PASS' if valid else 'FAIL',
                            'sandbox_created': bool(pods), 'actual': actual}
                        break
                    if pod.status.phase == 'Failed':
                        receipt['invalid_config'] = {'status': 'PASS', 'execution_uid': 0, 'phase': 'Failed', 'ready': False}
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Invalid configuration did not fail startup within the fixture deadline')
                    time.sleep(0.2)
                api.delete_namespaced_pod('invalid-runtime', namespace,
                    body={'preconditions': {'uid': pod.metadata.uid}})
                if scenario == 'group2-invalid':
                    receipt['passed'] = receipt['invalid_config']['status'] == 'PASS'
                    return receipt
            receipt['core_agents'] = {}
            probe_timeout = 600 if scenario == 'group2' else 240
            core_program = (
                'import sys, urllib.request; '
                'from gateway.identity.downstream import IDENTITY_HEADER, sign_identity; '
                'path=sys.argv[1]; '
                'identity={"user_id":"fixture-user","tenant_id":"fixture-tenant","kind":"session"}; '
                'header=sign_identity(identity,"runtime","POST",path,b""); '
                'request=urllib.request.Request("http://127.0.0.1:5014"+path, data=b"",'
                'headers={IDENTITY_HEADER:header}); '
                f'print(urllib.request.urlopen(request, timeout={probe_timeout}).read().decode())'
            )
            def execute_core(name, endpoint=scenario):
                with client.ApiClient() as peer_transport:
                    peer = client.CoreV1Api(peer_transport)
                    ws = stream(peer.connect_get_namespaced_pod_exec,name,namespace,container='nexent-runtime',command=['python','-c',core_program,'/__ksm/' + endpoint],stderr=True,stdout=True,stdin=False,tty=False,_preload_content=False)
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
                pending = {name: manager.submit('control-io', ManagedTaskSpec(task_name='owner-core-probe', owner='ksm-test'), execute_core, name).future for name in runtime_names}
                for name, future in pending.items():
                    receipt['core_agents'][name] = future.result(timeout=probe_timeout)
                    status = 'FINDINGS' if receipt['core_agents'][name].get('passed') is False else 'OK'
                    print(name + ' CORE_AGENT_PROBE_' + status + ' ' + json.dumps(receipt['core_agents'][name]), flush=True)
            finally:
                asyncio.run(manager.shutdown(timeout=5))
            if scenario != 'multiruntime':
                assert len(api.list_namespaced_pod(namespace, label_selector='nexent.ai/sandbox=system').items) == len(runtime_names)
            if scenario == 'group2':
                receipt['passed'] = (receipt['invalid_config']['status'] == 'PASS'
                    and receipt['core_agents']['runtime-a']['passed'])
            if scenario == 'group2-exit':
                active = receipt['core_agents']['runtime-a']
                assert active['active'] and active['owner_uid'] == receipt['runtimes']['runtime-a']['uid']
                replacement_spec = deepcopy(api.read_namespaced_pod('runtime-a', namespace).spec)
                claim_uid = api.read_namespaced_persistent_volume_claim('workspace', namespace).metadata.uid
                api.delete_namespaced_pod('runtime-a', namespace,
                    body={'preconditions': {'uid': active['owner_uid']}, 'gracePeriodSeconds': 2})
                deadline = time.monotonic() + 60
                while api.list_namespaced_pod(namespace, label_selector='app=nexent-runtime').items or api.list_namespaced_pod(
                        namespace, label_selector='nexent.ai/sandbox=system').items:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Owned Runtime and sandbox did not terminate')
                    time.sleep(0.2)
                # A read-only PVC mount verifies exit effects without restarting the owner.
                verify = ('from pathlib import Path;import sys;root=Path("/evidence");'
                    'paths=[(root/p).resolve() for p in sys.argv[1:]];'
                    'assert all(p.is_relative_to(root) for p in paths);'
                    'assert paths[0].read_text()=="X";assert paths[1].read_text()=="PEER_KEEP";print("EXIT_OK")')
                api.create_namespaced_pod(namespace, {'metadata': {'name': 'exit-verifier'}, 'spec': {
                    'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'verify', 'image': image, 'imagePullPolicy': 'Never',
                        'command': ['python', '-c', verify, active['marker'], active['peer']],
                        'resources': {'limits': {'memory': '128Mi', 'cpu': '0.5'}},
                        'volumeMounts': [{'name': 'workspace', 'mountPath': '/evidence', 'readOnly': True}]}],
                    'volumes': [{'name': 'workspace', 'persistentVolumeClaim': {'claimName': 'workspace'}}]}})
                deadline = time.monotonic() + 40
                while True:
                    verifier = api.read_namespaced_pod('exit-verifier', namespace)
                    if verifier.status.phase in {'Succeeded', 'Failed'}:
                        assert verifier.status.phase == 'Succeeded', api.read_namespaced_pod_log('exit-verifier', namespace)
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Exit evidence reader did not complete')
                    time.sleep(0.2)
                assert api.read_namespaced_persistent_volume_claim('workspace', namespace).metadata.uid == claim_uid
                receipt['owner_exit'] = {**active, 'runtime_and_sandbox_removed': True,
                    'marker_count': 1, 'peer_preserved': True, 'pvc_uid_preserved': claim_uid}
                api.create_namespaced_pod(namespace, client.V1Pod(
                    metadata=client.V1ObjectMeta(name='runtime-a', labels={'app': 'nexent-runtime'}),
                    spec=replacement_spec))
                deadline = time.monotonic() + 100
                while True:
                    replacement_pod = api.read_namespaced_pod('runtime-a', namespace)
                    if any(c.type == 'Ready' and c.status == 'True' for c in replacement_pod.status.conditions or []):
                        break
                    if replacement_pod.status.phase == 'Failed' or time.monotonic() >= deadline:
                        raise RuntimeError('Replacement Runtime did not become ready')
                    time.sleep(0.2)
                assert replacement_pod.metadata.uid != active['owner_uid']
                receipt['owner_exit']['replacement_owner_uid'] = replacement_pod.metadata.uid
                receipt['owner_exit']['fresh_admission'] = execute_core('runtime-a', 'w01')
                assert receipt['owner_exit']['fresh_admission']['promotion']['python_result'] == 42
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
