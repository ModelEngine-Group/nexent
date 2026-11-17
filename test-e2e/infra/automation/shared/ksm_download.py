# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Controlled file generation on a separately provisioned Kubernetes suite deployment."""

import hashlib
import os

from kubernetes import client, config

from shared.asset_registry import AssetDependencyError
from shared.tool_fastpath_deployed import artifact_objects, download_artifact, final_answers


def _namespace():
    namespace = os.environ.get('NEXENT_KSM_WEB_NAMESPACE')
    if not namespace:
        raise AssetDependencyError('deployment', 'ksm_web', detail='NEXENT_KSM_WEB_NAMESPACE is required')
    config.load_kube_config(context=os.environ.get('NEXENT_KSM_KUBE_CONTEXT', 'docker-desktop'))
    return namespace


def deployment(_cfg):
    namespace = _namespace()
    with client.ApiClient() as transport:
        api = client.CoreV1Api(transport)
        assert (api.read_namespace(namespace).metadata.labels or {}).get('nexent-test-owner') == namespace
        runtimes = api.list_namespaced_pod(namespace, label_selector='app=nexent-runtime').items
        assert runtimes, 'Disposable Nexent Runtime is not deployed'
        for pod in runtimes:
            runtime = next(container for container in pod.spec.containers if container.name == 'nexent-runtime')
            env = {item.name: item.value for item in runtime.env or []}
            assert env.get('NEXENT_SANDBOX_DEFAULT_LEVEL') == 'kubernetes'
            assert env.get('NEXENT_SANDBOX_DEFAULT_SCOPE') == 'system'
        return {'namespace': namespace, 'runtime_uids': [pod.metadata.uid for pod in runtimes]}


def responses(nonce):
    filename = f'tfp-{nonce}.txt'
    return [
        '<code>import os\nfrom pathlib import Path\n'
        f'Path({filename!r}).write_bytes(b"2\\n4\\n6\\n")\n'
        f'print("KSM_POD=" + os.environ["HOSTNAME"])\nprint(upload_to_s3(file_path={filename!r}))</code>',
        f'<final_answer>KSM_DOWNLOAD_{nonce}\n[{filename}]({{{{TFP_ARTIFACT_URL}}}})</final_answer>',
    ]


async def verify_download(identity, units, fixture, case_id):
    nonce = fixture['nonce']
    objects = artifact_objects(units, identity, nonce)
    assert len(objects) == 1, f'{case_id}: expected one owned file'
    key, artifact = next(iter(objects.items()))
    final, = final_answers(units)
    assert f'KSM_DOWNLOAD_{nonce}' in final and artifact['s3_url'] in final
    assert not any(unit.get('type') == 'error' for unit in units)
    content = await download_artifact(identity, key)
    assert content == b'2\n4\n6\n'
    logs = '\n'.join(str(unit.get('content', '')) for unit in units if unit.get('type') == 'execution_logs')
    verified = fixture['fingerprints']
    with client.ApiClient() as transport:
        namespace = _namespace()
        assert namespace == verified['namespace']
        pods = client.CoreV1Api(transport).list_namespaced_pod(namespace, label_selector='nexent.ai/sandbox=system').items
        pod, = [pod for pod in pods if f'KSM_POD={pod.metadata.name}' in logs]
        assert any(ref.uid in verified['runtime_uids'] for ref in pod.metadata.owner_references)
    return {'filename': artifact['filename'], 'sha256': hashlib.sha256(content).hexdigest(), 'pod_uid': pod.metadata.uid}
