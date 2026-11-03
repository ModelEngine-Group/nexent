# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression contracts for platform selection when exporting offline images."""

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
    """Run the real export functions with Docker isolated at the executable boundary."""
    functions = "\n".join(re.findall(
        r"^(?:docker_supports_save_platform|save_image_to_tar)\(\) \{.*?^\}",
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
if arguments[0] == "version":
    print(os.environ["FAKE_CLIENT_API"], os.environ["FAKE_SERVER_API"])
    sys.exit(int(os.environ["FAKE_VERSION_STATUS"]))
if arguments[0] == "save":
    if os.environ["FAKE_REQUIRE_PLATFORM"] == "true" and "--platform" not in arguments:
        print("unable to create manifests file: amd64 content digest not found", file=sys.stderr)
        sys.exit(1)
    if os.environ["FAKE_PLATFORM_SAVE_FAILS"] == "true" and "--platform" in arguments:
        print("no suitable export target found: image was found but does not provide the specified platform", file=sys.stderr)
        sys.exit(1)
    if int(os.environ["FAKE_SAVE_STATUS"]):
        print("synthetic image export failure", file=sys.stderr)
        sys.exit(int(os.environ["FAKE_SAVE_STATUS"]))
    Path(arguments[arguments.index("-o") + 1]).write_bytes(b"synthetic image tar")
    sys.exit(0)
sys.exit(2)
''', encoding="utf-8")
    docker.chmod(0o755)

    def run(platform="arm64", client_api="1.54", server_api="1.54", *,
            version_status=0, save_status=0, require_platform=False,
            platform_save_fails=False):
        log_path = tmp_path / "docker.jsonl"
        output = tmp_path / "offline images.tar"
        environment = os.environ.copy()
        environment.update(
            PATH=f"{tmp_path}{os.pathsep}{environment['PATH']}",
            FAKE_DOCKER_LOG=str(log_path),
            FAKE_CLIENT_API=client_api,
            FAKE_SERVER_API=server_api,
            FAKE_VERSION_STATUS=str(version_status),
            FAKE_SAVE_STATUS=str(save_status),
            FAKE_REQUIRE_PLATFORM=str(require_platform).lower(),
            FAKE_PLATFORM_SAVE_FAILS=str(platform_save_fails).lower(),
        )
        result = subprocess.run(
            ["bash", "-c", functions + '\nPLATFORM="$1"\nsave_image_to_tar "$2" "$3"',
             "offline-export-test", platform, "nexent/nexent:v2.8.3", str(output)],
            env=environment, capture_output=True, text=True, check=False,
        )
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        return result, calls, output

    return run


@pytest.mark.parametrize("platform", ["arm64", "amd64"])
@pytest.mark.parametrize("api_version", ["1.48", "1.54", "1.100", "2.0"])
def test_exports_only_requested_platform_on_supported_docker(export_image, platform, api_version):
    result, calls, output = export_image(
        platform, api_version, api_version, require_platform=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    saves = [call for call in calls if call[0] == "save"]
    assert len(saves) == 1
    assert saves[0][saves[0].index("--platform") + 1] == f"linux/{platform}"
    assert saves[0][saves[0].index("-o") + 1] == str(output)
    assert saves[0][-1] == "nexent/nexent:v2.8.3"
    assert output.read_bytes() == b"synthetic image tar"


@pytest.mark.parametrize("client_api,server_api", [
    ("1.39", "1.39"),
    ("1.47", "1.47"),
    ("1.54", "1.39"),
    ("1.39", "1.54"),
    ("1.47", "1.48"),
    ("1.48", "1.47"),
])
def test_preserves_legacy_export_when_either_api_is_older(export_image, client_api, server_api):
    result, calls, output = export_image(client_api=client_api, server_api=server_api)

    assert result.returncode == 0, result.stdout + result.stderr
    assert [call for call in calls if call[0] == "save"] == [
        ["save", "-o", str(output), "nexent/nexent:v2.8.3"],
    ]
    assert output.is_file()


@pytest.mark.parametrize("client_api,server_api,version_status", [
    ("", "", 0),
    ("1.54", "unknown", 0),
    ("unknown", "1.54", 0),
    ("1", "1.54", 0),
    ("1.54", "1.54", 1),
])
def test_uses_legacy_export_when_api_support_cannot_be_determined(
    export_image, client_api, server_api, version_status,
):
    result, calls, output = export_image(
        client_api=client_api, server_api=server_api, version_status=version_status,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert [call for call in calls if call[0] == "save"] == [
        ["save", "-o", str(output), "nexent/nexent:v2.8.3"],
    ]


@pytest.mark.parametrize("api_version,has_platform", [("1.54", True), ("1.39", False)])
def test_export_failure_is_reported_without_an_unrestricted_retry(export_image, api_version, has_platform):
    result, calls, output = export_image(client_api=api_version, server_api=api_version, save_status=1)

    assert result.returncode != 0
    assert "synthetic image export failure" in result.stderr
    assert "Failed to save image: nexent/nexent:v2.8.3" in result.stdout
    assert "Saved:" not in result.stdout
    assert not output.exists()
    saves = [call for call in calls if call[0] == "save"]
    assert len(saves) == 1
    assert ("--platform" in saves[0]) is has_platform


@pytest.mark.parametrize("platform", ["arm64", "amd64"])
def test_platform_export_falls_back_to_unrestricted_save_for_legacy_images(export_image, platform):
    # Legacy single-platform images (e.g. supabase/postgres:15.8.1.060) fail a
    # platform-filtered export even though the pinned pull already landed the
    # only available variant, so the save must fall back to an unfiltered export.
    result, calls, output = export_image(platform, platform_save_fails=True)

    assert result.returncode == 0, result.stdout + result.stderr
    saves = [call for call in calls if call[0] == "save"]
    assert len(saves) == 2
    assert "--platform" in saves[0]
    assert "--platform" not in saves[1]
    assert saves[1][-1] == "nexent/nexent:v2.8.3"
    assert "retrying without --platform" in result.stdout
    assert output.read_bytes() == b"synthetic image tar"


def test_unrestricted_retry_does_not_run_on_unsupported_docker(export_image):
    # On API versions without platform-filtered export there is nothing to
    # fall back from: a failing save must stay a single, failed attempt.
    result, calls, output = export_image(
        client_api="1.39", server_api="1.39", save_status=1,
    )

    assert result.returncode != 0
    saves = [call for call in calls if call[0] == "save"]
    assert len(saves) == 1
    assert "--platform" not in saves[0]
