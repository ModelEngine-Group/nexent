# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the image smoke script with controlled Docker and real file checks."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deploy/tests/smoke-independent-service-images.sh"


@pytest.fixture
def smoke(tmp_path):
    images = tmp_path / "images"
    for role in ("management", "runtime"):
        base = images / role / "opt"
        for relative in (
            "backend/ops/__init__.py", "backend/ops/monitoring/runtime.py",
            "nexent/scripts/run-sql-migrations.sh", "nexent/scripts/run-ops-sql-migrations.sh",
            "nexent/ops-sql/ops-init.sql",
        ):
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
            target.chmod(0o755)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text("""#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
set -eu
printf '%s\\t' "$@" >> "$SMOKE_LOG"
printf '\\n' >> "$SMOKE_LOG"
case "$1" in
  image) printf 'null\\n' ;;
  inspect) printf 'false\\n' ;;
  exec)
    shift
    if [ "$1" = -i ]; then shift; fi
    role="${1##*-}"
    shift
    if [ "$1" = sh ]; then
      shift 2
      code="${1//\/opt\//$SMOKE_IMAGES/$role/opt/}"
      bash -ec "$code"
    elif [ "$role" = "${SMOKE_UNREADY:-none}" ]; then
      exit 1
    fi
    ;;
esac
""", encoding="utf-8")
    docker.chmod(0o755)
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
    assert bash, "Bash is required for the image smoke regression"
    log = tmp_path / "docker.log"

    def run(*, full=True, unready="none"):
        environment = {
            **os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
            "SMOKE_IMAGES": images.as_posix(), "SMOKE_LOG": log.as_posix(), "SMOKE_UNREADY": unready,
        }
        arguments = ["management-image", "runtime-image"] + (["mcp-image", "ops-image"] if full else [])
        result = subprocess.run([bash, str(SCRIPT), *arguments], cwd=ROOT, env=environment,
                                capture_output=True, text=True, timeout=30)
        calls = [line.rstrip("\t").split("\t") for line in log.read_text().splitlines()]
        return result, calls

    return images, run


@pytest.mark.parametrize("full", [False, True])
def test_smoke_retains_monitoring_and_prepares_its_dependencies(smoke, full):
    _, run = smoke
    result, calls = run(full=full)
    assert result.returncode == 0, result.stdout + result.stderr
    runs = [call for call in calls if call[0] == "run"]
    assert not any("OPS_MONITORING_ENABLED=false" in call for call in runs)
    if full:
        es, = [call for call in runs if "--network-alias" in call and "elasticsearch" in call]
        assert "discovery.type=single-node" in es and "xpack.security.enabled=false" in es
        ops, = [call for call in runs if "ops-image" in call]
        assert "ELASTICSEARCH_HOST=http://elasticsearch:9200" in ops
        assert any("/_cluster/health" in part for call in calls for part in call)
    assert any(call[:2] == ["network", "rm"] for call in calls)
    assert any(call[:2] == ["rm", "-fv"] for call in calls)


@pytest.mark.parametrize("extra", ["api/application.py", "services/query.py", "monitoring/undeclared.py"])
def test_smoke_rejects_ops_business_sources_in_runtime(smoke, extra):
    images, run = smoke
    source = images / "runtime/opt/backend/ops" / extra
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("", encoding="utf-8")
    result, calls = run(full=False)
    assert result.returncode != 0
    assert "Unexpected Ops source" in result.stderr
    assert any(call[:2] == ["network", "rm"] for call in calls)


def test_smoke_cleans_up_when_ops_is_not_ready(smoke):
    _, run = smoke
    result, calls = run(unready="ops")
    assert result.returncode != 0
    assert "ops did not become ready" in result.stderr
    removed, = [call for call in calls if call[:2] == ["rm", "-fv"]]
    assert any(name.endswith("-elasticsearch") for name in removed)
    assert any(name.endswith("-ops") for name in removed)
