# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run namespaced sandbox containers, then recover each from a new Runtime process."""

import json
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import docker
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "sdk"), str(ROOT)]
CASE_ID = "EVOLUTION-SANDBOX-RECOVERY-D5-001"
CONTAINER_ROOT = "/home/sandbox/workdir"


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D5")
def test_docker_sandbox_deployments_recover_independently(tmp_path):
    from nexent.core.agents.sandbox.execution import (
        SANDBOX_CONTAINER_NAME, SANDBOX_NAMESPACE_LABEL, SANDBOX_NETWORK_NAME, _is_containerized_runtime,
    )

    client = docker.from_env()
    image = os.environ.get("NEXENT_TEST_SANDBOX_IMAGE", "nexent/nexent-sandbox:latest")
    client.images.get(image)
    suffix = uuid4().hex[:10]
    namespaces = {role: f"{role}-{suffix}" for role in ("chat", "eval")}
    workspaces = {role: tmp_path / role for role in namespaces}
    for role, workspace in workspaces.items():
        workspace.mkdir()
        (workspace / "owned.txt").write_text(role, encoding="utf-8")
        (workspace / f"{role}-only.txt").touch()
    initial_default = [c.id for c in client.containers.list(all=True) if c.name == SANDBOX_CONTAINER_NAME]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in (ROOT / "backend", ROOT / "sdk", ROOT))}

    def call(role, *, remove=False):
        child_env = {**env, "NEXENT_SANDBOX_DOCKER_NAMESPACE": namespaces[role]}
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), role, str(workspaces[role]), image, str(remove)],
            cwd=ROOT, env=child_env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=100,
        )
        assert process.returncode == 0, process.stderr[-3000:]
        return json.loads(process.stdout.splitlines()[-1])

    try:
        chat, replay = call("chat"), call("eval")
        assert chat["id"] != replay["id"] and chat["url"] != replay["url"]
        for role, receipt in (("chat", chat), ("eval", replay)):
            assert receipt["answer"] == role and not receipt["cross_mount"]
            assert receipt["name"] == f"{SANDBOX_CONTAINER_NAME}-{namespaces[role]}"
            actual = client.containers.get(receipt["id"])
            assert actual.labels[SANDBOX_NAMESPACE_LABEL] == namespaces[role]
            assert any(mount["Destination"] == CONTAINER_ROOT for mount in actual.attrs["Mounts"])
        assert call("eval", remove=True) == replay
        with pytest.raises(docker.errors.NotFound):
            client.containers.get(replay["id"])
        assert call("chat", remove=True) == chat
        with pytest.raises(docker.errors.NotFound):
            client.containers.get(chat["id"])
        assert [c.id for c in client.containers.list(all=True) if c.name == SANDBOX_CONTAINER_NAME] == initial_default
    finally:
        for namespace in namespaces.values():
            for container in client.containers.list(all=True, filters={"label": f"{SANDBOX_NAMESPACE_LABEL}={namespace}"}):
                if container.name == f"{SANDBOX_CONTAINER_NAME}-{namespace}":
                    container.remove(force=True)
            try:
                network = client.networks.get(f"{SANDBOX_NETWORK_NAME}-{namespace}")
                if _is_containerized_runtime():
                    runner = client.containers.get(socket.gethostname())
                    if runner.id in (network.attrs.get("Containers") or {}):
                        network.disconnect(runner)
                network.remove()
            except docker.errors.NotFound:
                pass
        client.close()


def worker(role, workspace, image, remove):
    from runtime.adapters.nexent.sandbox import resolve_deployed_sandbox
    from nexent.core.agents.sandbox.execution import SandboxPoolManager

    logger = logging.getLogger(__name__)
    config = resolve_deployed_sandbox({
        "level": "docker", "scope": "system", "docker_image": image, "failure_policy": "error",
        "workspace_mode": "bind", "container_workspace_root": CONTAINER_ROOT, "timeout_seconds": 25,
        "extra_kwargs": {"workspace_root": workspace},
    })
    pool = SandboxPoolManager()
    lease = pool.acquire(config, logger)
    try:
        other = "eval" if role == "chat" else "chat"
        output = lease.run_code_raise_errors(
            "from pathlib import Path\n"
            f"base = Path({CONTAINER_ROOT!r})\n"
            f"print((base / 'owned.txt').read_text(), (base / {f'{other}-only.txt'!r}).exists())"
        )
        answer, cross_mount = output.logs.strip().split()
        return {
            "answer": answer, "cross_mount": cross_mount == "True",
            "name": lease.container.name, "id": lease.container.id, "url": lease.base_url,
        }
    finally:
        pool.release(lease, logger)
        if remove:
            pool.shutdown(logger)


if __name__ == "__main__":
    role, workspace, image, remove = sys.argv[1:]
    print(json.dumps(worker(role, workspace, image, remove == "True")), flush=True)
