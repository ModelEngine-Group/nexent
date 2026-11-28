# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify the Docker shared workspace's host storage without starting Nexent."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
import yaml

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root


CASE_ID = "DEPLOY-WORKSPACE-D5-001"
WORKSPACE_TARGET = "/mnt/nexent/workdir"
SANDBOX_SOURCE = "NEXENT_SANDBOX_DOCKER_WORKSPACE_SOURCE"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D5"), pytest.mark.deploy]


def docker(*args, env=None, check=True):
    if shutil.which("docker") is None:
        raise AssetDependencyError("deployment", "docker", CASE_ID, detail="Docker is required")
    result = subprocess.run(["docker", *args], env=env, capture_output=True, text=True, timeout=25)
    if check:
        assert result.returncode == 0, result.stderr
    return result


def render_workspace(tmp_path, compose_filename):
    source_directory = repo_root() / "deploy/docker/compose"
    compose_dir = tmp_path / "deploy/docker/compose"
    compose_dir.mkdir(parents=True)
    compose_file = compose_dir / compose_filename
    shutil.copyfile(source_directory / compose_filename, compose_file)
    shutil.copyfile(source_directory / "docker-compose-ops.yml", compose_dir / "docker-compose-ops.yml")
    env_dir = tmp_path / "deploy/env"
    env_dir.mkdir()
    for filename in (".env", "monitoring.env"):
        (env_dir / filename).touch()

    env = os.environ.copy()
    env.update({name: "workspace-test:local" for name in (
        "ELASTICSEARCH_IMAGE", "POSTGRESQL_IMAGE", "NEXENT_WEB_IMAGE", "NEXENT_DATA_PROCESS_IMAGE",
        "REDIS_IMAGE", "MINIO_IMAGE", "OPENSSH_SERVER_IMAGE",
    )})
    env.update(ROOT_DIR=str(tmp_path), JWT_SECRET="workspace-test-jwt", NEXENT_POSTGRES_PASSWORD="workspace-test-db")
    assert "volumes" not in yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    render = docker("compose", "--env-file", str(env_dir / ".env"), "-p", "workspace-test",
                    "-f", str(compose_file), "config", "--format", "json", env=env)
    config = json.loads(render.stdout)
    runtime = config["services"]["nexent-runtime"]
    mount, = (entry for entry in runtime["volumes"] if entry["target"] == WORKSPACE_TARGET)
    assert mount["type"] == "bind"
    assert not mount.get("read_only", False)
    sandbox_source = runtime["environment"][SANDBOX_SOURCE]
    assert mount["source"] == sandbox_source == str(tmp_path / "agent-workspace")
    return mount["source"], sandbox_source


@pytest.mark.parametrize("compose_filename", ["docker-compose.yml", "docker-compose.prod.yml"])
@pytest.mark.parametrize("root_name", ["root", "root with spaces"])
def test_rendered_workspace_configuration(tmp_path, compose_filename, root_name):
    render_workspace(tmp_path / root_name, compose_filename)


def test_docker_bind_shares_host_directory(tmp_path):
    if docker("info", check=False).returncode:
        raise AssetDependencyError("deployment", "docker_daemon", CASE_ID, detail="Docker daemon is unavailable")
    image = os.environ.get("NEXENT_GATEWAY_IMAGE", "nexent/nexent-gateway:latest")
    inspect = docker("image", "inspect", "--format", "{{.Id}}", image, check=False)
    if inspect.returncode:
        raise AssetDependencyError("deployment", "gateway_image", CASE_ID, detail="A local Nexent Gateway image is required")
    image_id = inspect.stdout.strip()
    test_id = f"e2e-nexent-workspace-{uuid4().hex}"
    owner = f"com.nexent.test.workspace={test_id}"
    runtime_name = f"{test_id}-runtime"
    sandbox_name = f"{test_id}-sandbox"
    helper_args = ("--network", "none", "--label", owner, "--read-only",
                   "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "/bin/sh")
    with TemporaryDirectory(dir=tmp_path) as directory:
        runtime_source, sandbox_source = render_workspace(Path(directory), "docker-compose.yml")
        workspace = Path(runtime_source)
        workspace.mkdir()
        (workspace / "from-host").write_text("host input\n", encoding="utf-8")
        try:
            docker("run", "-d", "--name", runtime_name, *helper_args, "--mount",
                   f"type=bind,source={runtime_source},target={WORKSPACE_TARGET}", image_id, "-c", "sleep 120")
            docker("exec", "-w", WORKSPACE_TARGET, runtime_name, "/bin/sh", "-ec",
                   "test \"$(cat from-host)\" = 'host input'; echo 'runtime output' > from-runtime")
            docker("run", "--name", sandbox_name, *helper_args, "-w", WORKSPACE_TARGET, "--mount",
                   f"type=bind,source={sandbox_source},target={WORKSPACE_TARGET}", image_id,
                   "-ec", "test \"$(cat from-runtime)\" = 'runtime output'; echo 'sandbox output' > from-sandbox")
            result = docker("exec", "-w", WORKSPACE_TARGET, runtime_name, "cat", "from-sandbox")
            assert result.stdout == "sandbox output\n"
            assert (workspace / "from-runtime").read_text(encoding="utf-8") == "runtime output\n"
            assert (workspace / "from-sandbox").read_text(encoding="utf-8") == "sandbox output\n"
            for container_name in (runtime_name, sandbox_name):
                result = docker("inspect", "--format", "{{json .Mounts}}", container_name)
                mounts = json.loads(result.stdout)
                mount, = (entry for entry in mounts if entry["Destination"] == WORKSPACE_TARGET)
                assert mount["Type"] == "bind" and mount["RW"]
                assert all(entry["Type"] != "volume" for entry in mounts)
        finally:
            containers = docker("ps", "-aq", "--filter", f"label={owner}").stdout.splitlines()
            if containers:
                docker("rm", "-fv", *containers)
            assert not docker("ps", "-aq", "--filter", f"label={owner}").stdout.strip()
    assert not Path(directory).exists()
    write_case_evidence("docker-workspace-host-storage", {"host_round_trip": True, "cleanup_verified": True})
