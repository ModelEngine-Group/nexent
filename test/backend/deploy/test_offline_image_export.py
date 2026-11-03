# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression contracts for pulling and saving offline images."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


PACKAGE_SCRIPT = Path(__file__).resolve().parents[3] / "deploy/offline/build_offline_package.sh"


@pytest.fixture
def export_image(tmp_path):
    """Run real image helpers with Docker isolated at the executable boundary."""
    functions = "\n".join(re.findall(
        r"^(?:pull_with_retry|save_image_to_tar)\(\) \{.*?^\}",
        PACKAGE_SCRIPT.read_text(encoding="utf-8"),
        flags=re.MULTILINE | re.DOTALL,
    ))
    docker = tmp_path / "docker"
    docker.write_text(f"#!{sys.executable}\n" + '''\
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(arguments) + "\\n")
if arguments[0] == "pull":
    sys.exit(0)
if arguments[0] == "save":
    if "--platform" in arguments:
        print("unexpected platform-filtered export", file=sys.stderr)
        sys.exit(1)
    if int(os.environ["FAKE_SAVE_STATUS"]):
        print("synthetic image export failure", file=sys.stderr)
        sys.exit(int(os.environ["FAKE_SAVE_STATUS"]))
    Path(arguments[arguments.index("-o") + 1]).write_bytes(b"synthetic image tar")
    sys.exit(0)
sys.exit(2)
''', encoding="utf-8")
    docker.chmod(0o755)

    def run(platform="arm64", *, save_status=0, image="nexent/nexent:v2.8.3", operation="save"):
        log_path = tmp_path / "docker.jsonl"
        output = tmp_path / "offline images.tar"
        environment = os.environ.copy()
        environment.update(
            PATH=f"{tmp_path}{os.pathsep}{environment['PATH']}",
            FAKE_DOCKER_LOG=str(log_path),
            FAKE_SAVE_STATUS=str(save_status),
        )
        command = 'pull_with_retry "$2" "$1"' if operation == "pull" else 'save_image_to_tar "$2" "$3"'
        result = subprocess.run(
            ["bash", "-c", functions + '\nPLATFORM="$1"\n' + command,
             "offline-export-test", platform, image, str(output)],
            env=environment, capture_output=True, text=True, check=False,
        )
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        return result, calls, output

    return run


@pytest.mark.parametrize("platform", ["arm64", "amd64"])
def test_exports_nexent_without_platform_filter_or_version_probe(export_image, platform):
    result, calls, output = export_image(platform)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [["save", "-o", str(output), "nexent/nexent:v2.8.3"]]
    assert output.read_bytes() == b"synthetic image tar"


@pytest.mark.parametrize("platform", ["arm64", "amd64"])
@pytest.mark.parametrize("image", [
    "supabase/postgres:15.8.1.060",
    "docker.io/supabase/postgres:15.8.1.060",
    "docker.m.daocloud.io/supabase/postgres:15.8.1.060",
    "registry.local:5000/team/supabase/postgres:15.8.1.060",
    "supabase/postgres",
    "registry.local:5000/supabase/postgres",
    "supabase/postgres@sha256:" + "a" * 64,
])
def test_exports_supabase_postgres_without_platform_filter(export_image, platform, image):
    result, calls, output = export_image(platform, image=image)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [
        ["save", "-o", str(output), image],
    ]
    assert output.read_bytes() == b"synthetic image tar"


@pytest.mark.parametrize("platform", ["arm64", "amd64"])
@pytest.mark.parametrize("image", [
    "postgres:15-alpine",
    "supabase/postgres-meta:v0.91.0",
    "supabase/postgres-backup:latest",
    "other-supabase/postgres:15.8.1.060",
    "registry.local/supabase/postgres-tools:latest",
    "registry.local/supabase/postgres/child:latest",
])
def test_other_repositories_save_without_platform_filter(export_image, platform, image):
    result, calls, output = export_image(platform, image=image)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [
        ["save", "-o", str(output), image],
    ]
    assert output.is_file()


@pytest.mark.parametrize("platform", ["arm64", "amd64"])
@pytest.mark.parametrize("image", ["nexent/nexent:v2.8.3", "supabase/postgres:15.8.1.060"])
def test_export_failure_is_reported_without_retry(export_image, platform, image):
    result, calls, output = export_image(platform, image=image, save_status=1)

    assert result.returncode != 0
    assert "synthetic image export failure" in result.stderr
    assert f"Failed to save image: {image}" in result.stdout
    assert "Saved:" not in result.stdout
    assert not output.exists()
    assert calls == [
        ["save", "-o", str(output), image],
    ]


@pytest.mark.parametrize("platform", ["arm64", "amd64"])
@pytest.mark.parametrize("image", ["nexent/nexent:v2.8.3", "supabase/postgres:15.8.1.060"])
def test_pulls_requested_platform(export_image, platform, image):
    result, calls, output = export_image(platform, image=image, operation="pull")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [["pull", "--platform", f"linux/{platform}", image]]
    assert not output.exists()
