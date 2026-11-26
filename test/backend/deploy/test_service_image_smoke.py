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
            "infrastructure/monitoring/runtime.py",
            "nexent/scripts/run-sql-migrations.sh",
        ):
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("#!/usr/bin/env bash\n" if target.suffix == ".sh" else "",
                              encoding="utf-8", newline="\n")
            target.chmod(0o755)
    for relative in (
        "backend/configs/model_catalog.json", "backend/configs/models_dev_catalog.json",
        "nexent/litellm_models.json", "backend/tool_collection/langchain/compute_tool.py",
    ):
        target = images / "mcp/opt" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture", encoding="utf-8")
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
      if [ "$role" = mcp ]; then
        python() { :; }
        export -f python
      fi
      bash -ec "$code"
    elif [ "$role" = "${SMOKE_UNREADY:-none}" ]; then
      exit 1
    elif [[ "$*" == *store.verify_schema* ]]; then
      if [ ! -f "$SMOKE_LOG.ops-ready" ]; then
        echo "Ops schema checked before Ops was ready" >&2
        exit 1
      fi
    elif [[ "$role" == ops && "$*" == *build_opener* ]]; then
      touch "$SMOKE_LOG.ops-ready"
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
        arguments = ["management-image", "runtime-image"] + (["ops-image"] if full else [])
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
    mcp, = [call for call in runs if "backend.http.mcp_service" in call]
    assert "management-image" in mcp and "OPS_MONITORING_ENABLED=false" in mcp
    assert all("OPS_MONITORING_ENABLED=false" not in call for call in runs if call != mcp)
    capture, read_only = [call for call in runs if "backend.http.runtime_service" in call]
    assert {
        "MONITORING_PROVIDER=otlp", "ENABLE_TELEMETRY=false",
        "LOCAL_FILE_MONITORING_ENABLED=true", "TRAJECTORY_READ_ENABLED=false",
    } <= set(capture)
    assert {
        "MONITORING_PROVIDER=otlp", "ENABLE_TELEMETRY=false",
        "LOCAL_FILE_MONITORING_ENABLED=false", "TRAJECTORY_READ_ENABLED=true",
    } <= set(read_only)
    schema_checks = [call for call in calls if any("store.verify_schema()" in part for part in call)]
    assert len(schema_checks) == (1 if full else 0)
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


@pytest.mark.parametrize("extra", [
    "nexent/scripts/start-ops.sh", "nexent/scripts/run-ops-sql-migrations.sh", "nexent/ops-sql/ops-init.sql",
])
def test_smoke_rejects_ops_initializers_in_producer_images(smoke, extra):
    images, run = smoke
    source = images / "runtime/opt" / extra
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("unexpected Ops dependency", encoding="utf-8")
    result, calls = run(full=False)
    assert result.returncode != 0
    assert "Unexpected Ops SQL initializer" in result.stderr
    assert any(call[:2] == ["network", "rm"] for call in calls)


def test_smoke_cleans_up_when_ops_is_not_ready(smoke):
    _, run = smoke
    result, calls = run(unready="ops")
    assert result.returncode != 0
    assert "ops did not become ready" in result.stderr
    assert not any("store.verify_schema()" in part for call in calls for part in call)
    removed, = [call for call in calls if call[:2] == ["rm", "-fv"]]
    assert any(name.endswith("-elasticsearch") for name in removed)
    assert any(name.endswith("-ops") for name in removed)
