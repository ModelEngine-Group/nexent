# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify host-data retention after a real Docker Compose configuration error."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
from tempfile import TemporaryDirectory

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.config import repo_root


CASE_ID = "DEPLOY-UNINSTALL-D5-001"
pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D5"), pytest.mark.deploy]


def test_compose_configuration_failure_preserves_host_data(tmp_path):
    if not shutil.which("docker") and not shutil.which("docker-compose"):
        raise AssetDependencyError("deployment", "docker", CASE_ID, detail="Docker Compose is required")

    with TemporaryDirectory(dir=tmp_path) as directory:
        root = Path(directory)
        deploy = root / "deploy"
        compose_file = deploy / "docker/compose/docker-compose-monitoring.yml"
        compose_file.parent.mkdir(parents=True)
        (deploy / "env").mkdir()
        (deploy / "common").mkdir()
        script = deploy / "docker/uninstall.sh"
        shutil.copyfile(repo_root() / "deploy/docker/uninstall.sh", script)
        shutil.copyfile(repo_root() / "deploy/common/common.sh", deploy / "common/common.sh")
        compose_file.write_text("services: [\n", encoding="utf-8")

        data_dir = root / "host data"
        home = root / "home"
        (deploy / "env/.env").write_text(f"ROOT_DIR={shlex.quote(str(data_dir))}\n", encoding="utf-8")
        sentinels = {
            data_dir / "agent-workspace/run/output.txt": b"workspace output\n",
            data_dir / "postgresql/data/fixture.txt": b"database data\n",
            home / "nexent/user.txt": b"user data\n",
        }
        for path, contents in sentinels.items():
            path.parent.mkdir(parents=True)
            path.write_bytes(contents)

        docker_socket = root / "unused.sock"
        env = os.environ.copy()
        env.pop("DOCKER_CONTEXT", None)
        env.setdefault("DOCKER_CONFIG", str(Path.home() / ".docker"))
        env.update(HOME=str(home), DEPLOYMENT_LANG="en", DOCKER_HOST=f"unix://{docker_socket}")
        result = subprocess.run(
            ["bash", str(script), "--delete-volumes", "true"],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=25,
        )

        diagnostic = result.stdout + result.stderr
        assert "yaml" in diagnostic.lower(), diagnostic
        assert result.returncode != 0, diagnostic
        assert "Host data directories were preserved." in diagnostic, diagnostic
        assert "Docker deployment removed." not in diagnostic, diagnostic
        for path, contents in sentinels.items():
            assert path.read_bytes() == contents
        assert not docker_socket.exists()

    assert not Path(directory).exists()
    write_case_evidence("docker-uninstall-preserve-data", {
        "compose_configuration_error": True, "exit_status": result.returncode,
        "preserved_files": len(sentinels), "cleanup_verified": True,
    })
