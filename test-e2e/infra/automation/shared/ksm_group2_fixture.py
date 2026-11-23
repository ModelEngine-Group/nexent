# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Group-two negative checks, exclusively inside the owned Kubernetes fixture."""

import json
import logging
import ssl
import time
import uuid
from concurrent.futures import CancelledError
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from kubernetes.client.exceptions import ApiException
from requests.exceptions import SSLError

from nexent.core.agents.cores.smolagents.agent import cleanup_run_workspace
from nexent.core.agents.sandbox_contracts import SandboxGenerationChangedError
from nexent.core.agents.sandbox_kubernetes import KubernetesSandboxBackend, _document
from nexent.core.agents.sandbox_kubernetes_exec import KubernetesProcessAdapter
from nexent.core.agents.sandbox_kubernetes_lease import KubernetesKernelLease
from nexent.core.agents.sandbox.tls import SandboxTLSClient
from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool
from nexent.storage.minio import MinIOStorageClient


def rejected(action, errors=(Exception,)):
    try:
        action()
    except errors as exc:
        return type(exc).__name__
    raise AssertionError('Operation unexpectedly succeeded')


def until(predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError('Fixture condition not observed')
        time.sleep(0.2)


def probe_group2(owned, prepare):
    coordinator, run_id, scope, config, workspace = prepare(owned)
    assert coordinator.owner.namespace.startswith('nexent-ksm-core-')
    backend, owner, profile = config.runtime_backend, config.owner, config.system_profile
    results = {}

    def check(name, action):
        try:
            detail = action()
            results[name] = {'status': 'PASS', 'detail': detail}
        except Exception as exc:
            results[name] = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'}
        print('GROUP2 ' + name + ' ' + results[name]['status'], flush=True)

    check('ready_cancel_timeout', lambda: readiness(backend, owner, profile))
    gateway = backend.ensure_system(owner, profile)
    gateway.logger = logging.getLogger('group2')
    mapping = config.bind_workspace().for_run(str(workspace))
    process = KubernetesProcessAdapter(backend, owner, profile, gateway.generation)
    check('identity_rbac_limits', lambda: identity(process, gateway, mapping))
    check('tls_https_wss', lambda: tls(gateway))
    check('profile_conflict', lambda: profile_conflict(backend, owner, profile, gateway))
    def check_files():
        detail = files(config, workspace, mapping, process, run_id)
        safe = detail.pop('replacement_rejected')
        races = detail.pop('replacement_checks')
        results['upload_path_replacement'] = {'status': 'PASS' if safe else 'FAIL',
            'detail': races,
            'outside_bytes_uploaded': any(row['outside_bytes_uploaded'] for row in races.values())}
        return detail
    check('files_and_upload', check_files)
    check('repeated_cleanup', lambda: cleanup(config))
    check('exec_disconnect', lambda: exec_disconnect(coordinator, owned['lease'], process, workspace, mapping))
    check('kernel_disconnect', lambda: kernel_disconnect(gateway, workspace, mapping))
    check('pod_replacement', lambda: replacement(backend, owner, profile, gateway, workspace, mapping))
    return {'run_id': run_id, 'checks': results,
            'passed': all(row['status'] == 'PASS' for row in results.values())}


def remove_sandbox(backend, owner, profile):
    backend.close_owner(owner, profile, deadline=time.monotonic() + 15)
    def absent():
        with backend.api_factory() as api:
            try:
                api.read_namespaced_pod(backend.resource_name(owner), owner.namespace)
            except ApiException as exc:
                if exc.status == 404:
                    return True
                raise
        return False
    until(absent)


def readiness(base, owner, profile):
    class DelayedGateway(KubernetesSandboxBackend):
        def manifests(self, *args):
            pod, service = super().manifests(*args)
            original = pod['spec']['containers'][0]['command']
            pod['spec']['containers'][0]['command'] = ['python', '-c',
                'import os,sys,time;time.sleep(12);os.execvp(sys.argv[1],sys.argv[1:])', *original]
            return pod, service

    delayed = DelayedGateway(base.api_factory, workspace_subpath=base.workspace_subpath,
                             startup_timeout=0.5, single_node_development=True)
    name = delayed.resource_name(owner)
    try:
        rejected(lambda: delayed.ensure_system(owner, profile), (TimeoutError,))
        with base.api_factory() as api:
            def running():
                return api.read_namespaced_pod(name, owner.namespace).status.phase == 'Running'
            until(running)
            pod = api.read_namespaced_pod(name, owner.namespace)
            assert not any(c.type == 'Ready' and c.status == 'True' for c in pod.status.conditions)
            first_uid = pod.metadata.uid
        rejected(lambda: delayed.ensure_system(owner, profile), (TimeoutError,))
        assert not delayed._connections
        delayed.startup_timeout = 5
        calls = []
        def cancel():
            calls.append(time.monotonic())
            if len(calls) >= 4:
                raise CancelledError('Fixture cancellation while waiting for Ready')
        rejected(lambda: delayed.ensure_system(owner, profile, check_cancelled=cancel), (CancelledError,))
        with base.api_factory() as api:
            until(lambda: any(c.type == 'Ready' and c.status == 'True'
                for c in api.read_namespaced_pod(name, owner.namespace).status.conditions))
            pod = api.read_namespaced_pod(name, owner.namespace)
            assert pod.metadata.uid == first_uid
            assert not delayed._connections
            assert len(api.list_namespaced_pod(owner.namespace,
                label_selector='nexent.ai/sandbox=system').items) == 1
        return {'running_not_ready': True, 'timeout_no_connection': True,
                'cancelled_no_connection': True, 'late_ready_same_uid': first_uid}
    finally:
        remove_sandbox(delayed, owner, profile)


def identity(process, gateway, mapping):
    with gateway.backend.api_factory() as api:
        pod = api.read_namespaced_pod(gateway.backend.resource_name(gateway.owner), gateway.owner.namespace)
        assert not pod.spec.automount_service_account_token
        assert not pod.spec.host_network and not pod.spec.host_pid and not pod.spec.host_ipc
        assert not any(v.host_path for v in pod.spec.volumes)
        for container in pod.spec.containers:
            assert not container.security_context.privileged
            assert not container.security_context.allow_privilege_escalation
            assert container.security_context.capabilities.drop == ['ALL']
        denied = []
        for operation, args in [(api.list_namespaced_secret, (gateway.owner.namespace,)),
                                (api.list_namespaced_pod, ('default',))]:
            try:
                operation(*args)
            except ApiException as exc:
                assert exc.status == 403
                denied.append(exc.status)
            else:
                raise AssertionError('Runtime SA exceeded its scope')
        assert api.read_namespaced_persistent_volume_claim('workspace', gateway.owner.namespace).status.phase == 'Bound'
    code = """import json,os
from pathlib import Path
assert os.getuid()==1000
assert not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()
assert not Path('/var/run/docker.sock').exists()
assert not Path('/mnt/nexent/workdir/.sandbox-control').exists()
p=Path('/sys/fs/cgroup')
print(json.dumps({n:(p/n).read_text().strip() for n in ['cpu.max','memory.max','memory.current','cpu.stat']}))
"""
    result = process.run(['python', '-c', code], cwd=str(mapping.container_root / 'outputs'), env={}, timeout_seconds=5)
    assert result.exit_code == 0, result.stderr.decode()
    limits = json.loads(result.stdout)
    quota, period = map(int, limits['cpu.max'].split())
    assert quota / period == float(gateway.profile.cpu_quota)
    assert int(limits['memory.max']) == gateway.profile.memory_limit_mb * 1024 * 1024
    load = r"""import json,subprocess,sys
from pathlib import Path
p=Path('/sys/fs/cgroup/cpu.stat')
def throttled(): return int(dict(line.split() for line in p.read_text().splitlines())['nr_throttled'])
before=throttled()
code='import time;t=time.monotonic()+2\nwhile time.monotonic()<t: pass'
children=[subprocess.Popen([sys.executable,'-c',code]) for _ in range(3)]
assert all(child.wait(timeout=8)==0 for child in children)
after=throttled()
assert after>before
print(json.dumps({'before':before,'after':after}))
"""
    loaded = process.run(['python', '-c', load], cwd='/tmp', env={}, timeout_seconds=12)
    assert loaded.exit_code == 0, loaded.stderr.decode()
    limits['cpu_throttling_under_bounded_load'] = json.loads(loaded.stdout)
    return {'uid': 1000, 'denied': denied, 'pod_uid': pod.metadata.uid, 'cgroups': limits}


def tls(gateway):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from datetime import datetime, timedelta, timezone
    from websocket import create_connection

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'wrong-fixture')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1)).sign(key, hashes.SHA256()))
    wrong = SandboxTLSClient(cert.public_bytes(serialization.Encoding.PEM))
    kernel = KubernetesKernelLease(gateway, gateway.logger)
    try:
        assert gateway.tls_client.http.get(gateway.base_url + '/api/kernels', timeout=5).status_code == 200
        rejected(lambda: wrong.http.get(gateway.base_url + '/api/kernels', timeout=5), (SSLError,))
        rejected(lambda: gateway.tls_client.http.get('http://' + gateway.host + ':8080/api/kernels'), (ValueError,))
        def channel(context):
            return create_connection(kernel.ws_url, timeout=5, sslopt={'context': context},
                http_proxy_host=gateway.host, http_no_proxy=[gateway.host], redirect_limit=0)
        rejected(lambda: channel(wrong.ssl_context), (ssl.SSLError,))
        ws = channel(gateway.tls_client.ssl_context)
        assert ws.getstatus() == 101
        ws.close()
        cert = x509.load_pem_x509_certificate(gateway.tls_client.ca_file.read_bytes())
        assert gateway.host in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        return {'https': 200, 'wss': 101, 'wrong_trust_rejected': True, 'san': gateway.host}
    finally:
        kernel.cleanup()
        wrong.close()


def profile_conflict(backend, owner, profile, gateway):
    rejected(lambda: backend.ensure_system(owner, replace(profile, cpu_quota=float(profile.cpu_quota) + 1)))
    with backend.api_factory() as api:
        pods = api.list_namespaced_pod(owner.namespace, label_selector='nexent.ai/sandbox=system').items
        assert len(pods) == 1 and pods[0].metadata.uid == gateway.pod_uid
    return {'preserved_uid': gateway.pod_uid}


def files(config, workspace, mapping, process, run_id):
    skill = workspace / '.skills' / 'guard.txt'
    skill.write_text('SKILL_ORIGINAL')
    config.workspace_access.seal_materials(workspace)
    outputs = workspace / 'outputs'
    script = """import os,sys
from pathlib import Path
p=Path(sys.argv[1])
try:
    (p/'.skills/guard.txt').write_text('BAD')
except PermissionError:
    pass
else:
    raise AssertionError('Skill writable')
(p/'outputs/allowed.txt').write_text('UPLOAD_OK')
assert (p/'.skills/guard.txt').read_text()=='SKILL_ORIGINAL'
print('FILE_PERMISSIONS_OK')
"""
    result = process.run(['python', '-c', script, str(mapping.container_root)], cwd=str(mapping.container_root), env={}, timeout_seconds=5)
    assert result.exit_code == 0, result.stderr.decode()
    client = MinIOStorageClient('http://minio:9000', 'ksm-fixture', 'ksm-disposable-only',
                                default_bucket='ksm-group2', secure=False)
    uploaded = []
    tool = UploadToS3Tool(workspace_path=str(workspace), minio_client=client,
                         user_id='fixture-user', run_id=run_id, on_upload=uploaded.append)
    tool.workspace_mapping = mapping
    outside = workspace.parent / ('outside-' + run_id)
    outside.mkdir()
    sentinel = outside / 'sentinel.txt'
    sentinel.write_text('OUTSIDE_PRIVATE')
    (outputs / 'escape').symlink_to(outside, target_is_directory=True)
    for bad in ['../outside/sentinel.txt', '/etc/passwd', 'outputs/escape/sentinel.txt']:
        rejected(lambda value=bad: tool.forward(value))
    assert uploaded == []
    good = json.loads(tool.forward('allowed.txt'))
    body = client.client.get_object(Bucket='ksm-group2', Key=good['object_name'])['Body']
    try:
        assert body.read() == b'UPLOAD_OK'
    finally:
        body.close()
    # A real closed TCP endpoint, scoped only to this client's next request.
    from botocore.config import Config
    import boto3
    working = client.client
    client.client = boto3.client('s3', endpoint_url='http://127.0.0.1:1',
        aws_access_key_id='ksm-fixture', aws_secret_access_key='ksm-disposable-only',
        config=Config(connect_timeout=1, read_timeout=1, retries={'max_attempts': 0}, proxies={}))
    (outputs / 'upload-fail.txt').write_text('FAILURE_PROBE')
    try:
        rejected(lambda: tool.forward('upload-fail.txt'))
        assert len(uploaded) == 1
        keys = [o['Key'] for o in working.list_objects_v2(Bucket='ksm-group2').get('Contents', [])]
        assert not any(key.endswith('/upload-fail.txt') for key in keys)
    finally:
        client.client.close()
        client.client = working
    assert json.loads(tool.forward('upload-fail.txt'))['status'] == 'success'
    # Inject at both validation/open and open/storage boundaries. Each hook
    # must execute, including when the storage implementation switches to streams.
    races = {}
    try:
        for stage in ('before_open', 'after_open'):
            for parent in (False, True):
                label = stage + ('_parent' if parent else '_leaf')
                directory = outputs / label
                directory.mkdir()
                race = directory / sentinel.name
                race.write_text('SAFE')
                target = directory if parent else race
                saved = target.with_name(target.name + '-saved')
                calls = []
                callbacks_before = len(uploaded)
                def swap():
                    target.rename(saved)
                    target.symlink_to(outside if parent else sentinel, target_is_directory=parent)
                    calls.append(True)
                candidates = tool._upload_path_candidates
                def swapped_candidates(value):
                    paths = candidates(value)
                    swap()
                    return paths
                upload_path, upload_stream = client.upload_file, client.upload_fileobj
                def swapped_path(path, key):
                    swap()
                    return upload_path(path, key)
                def swapped_stream(stream, key):
                    swap()
                    return upload_stream(stream, key)
                from contextlib import ExitStack
                try:
                    error, content = None, None
                    with ExitStack() as stack:
                        if stage == 'before_open':
                            stack.enter_context(patch.object(tool, '_upload_path_candidates', swapped_candidates))
                        else:
                            stack.enter_context(patch.object(client, 'upload_file', swapped_path))
                            stack.enter_context(patch.object(client, 'upload_fileobj', swapped_stream))
                        try:
                            result = json.loads(tool.forward(label + '/' + sentinel.name,
                                                             label + '/' + sentinel.name))
                        except Exception as exc:
                            error = type(exc).__name__
                    if error is None:
                        body = working.get_object(Bucket='ksm-group2', Key=result['object_name'])['Body']
                        try:
                            content = body.read()
                        finally:
                            body.close()
                    expected = (error is not None and len(uploaded) == callbacks_before if stage == 'before_open'
                                else error is None and content == b'SAFE' and result['size'] == 4
                                and len(uploaded) == callbacks_before + 1)
                    keys = [o['Key'] for o in working.list_objects_v2(Bucket='ksm-group2').get('Contents', [])]
                    if stage == 'before_open':
                        expected = expected and not any('/' + label + '/' in key for key in keys)
                    races[label] = {'passed': calls == [True] and expected,
                                    'hook_calls': len(calls), 'error': error,
                                    'outside_bytes_uploaded': content == b'OUTSIDE_PRIVATE',
                                    'original_bytes_uploaded': content == b'SAFE'}
                finally:
                    if target.is_symlink():
                        target.unlink()
                        saved.rename(target)
                    race.unlink()
                    directory.rmdir()
        return {'skill_write_denied': True, 'traversal_symlink_denied': True,
                'upload_failure_no_artifact': True, 'upload_recovered': True,
                'replacement_rejected': all(item['passed'] for item in races.values()),
                'replacement_checks': races}
    finally:
        assert sentinel.read_text() == 'OUTSIDE_PRIVATE'
        (outputs / 'escape').unlink()
        working.close()



def exec_disconnect(coordinator, lease, process, workspace, mapping):
    import nexent.core.agents.sandbox_kubernetes_exec as module
    from runtime.sandbox_coordination import SandboxRunLifecycle
    original = module.stream
    calls = []
    marker = workspace / 'outputs' / 'exec-count.txt'
    lifecycle = SandboxRunLifecycle(coordinator, lease)
    adapter = KubernetesProcessAdapter(process.backend, process.owner, process.profile,
                                       process.generation, run_lifecycle=lifecycle)
    def interrupted(*args, **kwargs):
        ws = original(*args, **kwargs)
        calls.append(1)
        until(marker.exists, timeout=5)
        ws.close()
        # Drop the exit channel after the remote command has committed.
        return SimpleNamespace(is_open=lambda: False, read_stdout=lambda: b'', read_stderr=lambda: b'',
                               returncode=None, close=ws.close)
    code = "from pathlib import Path;import time;p=Path('exec-count.txt');p.open('a').write('X');time.sleep(2)"
    with patch.object(module, 'stream', interrupted):
        rejected(lambda: adapter.run(['python', '-c', code], cwd=str(mapping.container_root / 'outputs'),
                                     env={}, timeout_seconds=4), (RuntimeError,))
    assert len(calls) == 1 and marker.read_text() == 'X'
    record = coordinator.journal.read_current(lease.business_key)
    assert record.phase == 'UNKNOWN'
    assert not coordinator.finish(lease)
    return {'remote_count': 1, 'phase': record.phase, 'reservation_retained': True,
            'fault': 'real exec committed; exit channel deliberately discarded'}


def cleanup(config):
    access = config.workspace_access
    first, peer = [access.prepare_run('fixture-tenant', 'fixture-user', uuid.uuid4().hex) for _ in range(2)]
    other = access.owner_root.parent / ('fixture-other-' + uuid.uuid4().hex)
    other.mkdir()
    (other / 'sentinel').write_text('OTHER_OWNER')
    (peer / 'outputs/sentinel').write_text('OTHER_RUN')
    (first / 'outputs/link').symlink_to(other, target_is_directory=True)
    assert cleanup_run_workspace(str(first), first.name)
    assert not cleanup_run_workspace(str(first), first.name)
    assert (other / 'sentinel').read_text() == 'OTHER_OWNER'
    assert (peer / 'outputs/sentinel').read_text() == 'OTHER_RUN'
    assert not first.exists()
    return {'repeated_cleanup': True, 'other_run_preserved': True, 'outside_symlink_target_preserved': True}


def start_exit_probe(prepare):
    from runtime.thread_management import runtime_thread_manager
    from nexent.core.concurrency import ManagedTaskSpec
    owned = {}
    coordinator, run_id, scope, config, workspace = prepare(owned)
    gateway = config.runtime_backend.ensure_system(config.owner, config.system_profile)
    gateway.logger = logging.getLogger('group2-exit')
    kernel = KubernetesKernelLease(gateway, gateway.logger)
    mapping = config.bind_workspace().for_run(str(workspace))
    marker = workspace / 'outputs/exit-count.txt'
    peer = config.workspace_access.prepare_run('fixture-tenant', 'fixture-user', uuid.uuid4().hex)
    (peer / 'outputs/sentinel').write_text('PEER_KEEP')
    task = runtime_thread_manager.submit('sandbox',
        ManagedTaskSpec(task_name='fixture-owner-exit', owner='ksm-test', run_id=run_id),
        kernel.run_code_raise_errors,
        f"from pathlib import Path\nimport time\np=Path({str(mapping.container_root / 'outputs/exit-count.txt')!r})\np.open('a').write('X')\ntime.sleep(120)")
    until(marker.exists, timeout=10)
    assert not task.future.done()
    return {'owner_uid': coordinator.owner.pod_uid, 'sandbox_uid': gateway.pod_uid,
            'run_id': run_id, 'active': True,
            'marker': str(marker.relative_to('/mnt/nexent')),
            'peer': str((peer / 'outputs/sentinel').relative_to('/mnt/nexent'))}


def probe_memory(owned, prepare):
    _, _, _, config, workspace = prepare(owned)
    gateway = config.runtime_backend.ensure_system(config.owner, config.system_profile)
    assert gateway.profile.memory_limit_mb == 192
    process = KubernetesProcessAdapter(gateway.backend, gateway.owner, gateway.profile, gateway.generation)
    permissions_and_cpu = identity(process, gateway, config.bind_workspace().for_run(str(workspace)))
    # One bounded allocation, only in this 192 MiB disposable sandbox cgroup.
    transport = {}
    try:
        result = process.run(['python', '-c', 'x=bytearray(256*1024*1024);print(len(x))'],
                             cwd='/tmp', env={}, timeout_seconds=10)
        transport['exit_code'] = result.exit_code
    except (ApiException, RuntimeError, ValueError) as exc:
        transport['error'] = type(exc).__name__
    # OOM may close exec before its exit channel. Require independent container evidence.
    with gateway.backend.api_factory() as api:
        observed = []
        def terminated():
            pod = api.read_namespaced_pod(gateway.backend.resource_name(gateway.owner), gateway.owner.namespace)
            observed[:] = [s.state.terminated for s in pod.status.container_statuses or [] if s.state.terminated]
            return bool(observed)
        until(terminated, timeout=15)
    assert observed[0].reason == 'OOMKilled' and observed[0].exit_code == 137
    events = {'container_reason': observed[0].reason, 'exit_code': observed[0].exit_code}
    return {'passed': True, 'memory_limit_mb': 192, 'requested_mb': 256,
            'transport': transport, 'memory_events': events, 'identity_and_cpu': permissions_and_cpu}


def kernel_disconnect(gateway, workspace, mapping):
    import websocket
    original = websocket.create_connection
    kernel = KubernetesKernelLease(gateway, gateway.logger, receive_timeout_seconds=3)
    marker = workspace / 'outputs' / 'kernel-count.txt'
    count = []
    def channel(*args, **kwargs):
        ws = original(*args, **kwargs)
        send = ws.send
        def send_and_drop(payload, *a, **k):
            result = send(payload, *a, **k)
            if 'execute_request' in str(payload):
                count.append(1)
                until(marker.exists, timeout=5)
                ws.shutdown()
            return result
        ws.send = send_and_drop
        return ws
    try:
        with patch.object(websocket, 'create_connection', channel):
            rejected(lambda: kernel.run_code_raise_errors(
                f"from pathlib import Path\nimport time\np=Path({str(mapping.container_root / 'outputs/kernel-count.txt')!r})\np.open('a').write('X')\ntime.sleep(2)"))
        assert count == [1] and marker.read_text() == 'X'
        return {'remote_count': 1, 'channel_lost_visible': True}
    finally:
        kernel.cleanup()


def replacement(backend, owner, profile, gateway, workspace, mapping):
    kernel = KubernetesKernelLease(gateway, gateway.logger)
    kernel.run_code_raise_errors('g2_old_state=123')
    old_cert = gateway.tls_client.ca_file.read_bytes()
    old_uid = gateway.pod_uid
    with backend.api_factory() as api:
        api.delete_namespaced_pod(backend.resource_name(owner), owner.namespace,
            body={'preconditions': {'uid': old_uid}, 'gracePeriodSeconds': 1})
        def absent():
            try:
                api.read_namespaced_pod(backend.resource_name(owner), owner.namespace)
            except ApiException as exc:
                if exc.status == 404:
                    return True
                raise
            return False
        until(absent)
        manifest, _ = backend.manifests(owner, profile)
        api.create_namespaced_pod(owner.namespace, manifest)
        until(lambda: any(c.type == 'Ready' and c.status == 'True'
            for c in api.read_namespaced_pod(backend.resource_name(owner), owner.namespace).status.conditions or []))
    rejected(lambda: kernel.run_code_raise_errors('print(g2_old_state)'), (SandboxGenerationChangedError,))
    rejected(lambda: backend.ensure_system(owner, profile), (SandboxGenerationChangedError,))
    from runtime.sandbox_coordination import SandboxCoordinationUnknown
    rejected(lambda: backend.ensure_system(owner, profile), (SandboxCoordinationUnknown,))
    # Verify the new transport independently; owner admission correctly remains blocked.
    from nexent.core.agents.sandbox_kubernetes import KubernetesGateway
    from nexent.core.agents.sandbox.tls import TLS_CERTIFICATE
    with backend.api_factory() as api:
        pod = _document(api.read_namespaced_pod(backend.resource_name(owner), owner.namespace))
    process = KubernetesProcessAdapter(backend, owner, profile, backend.generation(pod))
    certificate = process.run(['cat', TLS_CERTIFICATE], cwd='/home/sandbox', env={}, timeout_seconds=5)
    assert certificate.exit_code == 0
    fresh = KubernetesGateway(backend, owner, profile, pod, certificate.stdout)
    fresh.logger = gateway.logger
    assert fresh.pod_uid != old_uid
    old_trust = SandboxTLSClient(old_cert)
    try:
        rejected(lambda: old_trust.http.get(fresh.base_url + '/api/kernels', timeout=5), (SSLError,))
        new_kernel = KubernetesKernelLease(fresh, fresh.logger)
        try:
            result = new_kernel.run_code_raise_errors("assert 'g2_old_state' not in globals();print('NEW_EXEC_OK')")
            assert 'NEW_EXEC_OK' in result.logs
        finally:
            new_kernel.cleanup()
    finally:
        old_trust.close()
        fresh.close()
    return {'old_uid': old_uid, 'new_uid': fresh.pod_uid, 'old_trust_rejected': True, 'old_state_absent': True,
            'owner_readmission': 'rejected until reconciliation; no automatic continuation claimed'}
