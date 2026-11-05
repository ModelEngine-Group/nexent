# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway deployment boundaries and the executable image-selection contract."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "deploy/k8s/helm/nexent"


def test_gateway_image_delegates_the_application_command_like_main():
    for image in ("gateway", "main"):
        source = (ROOT / "deploy/images/dockerfiles" / image / "Dockerfile").read_text(encoding="utf-8")
        instructions = [line.strip().split(maxsplit=1)[0].upper() for line in source.splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        assert "ENTRYPOINT" not in instructions
        assert "CMD" not in instructions


def bash_run(script):
    # Windows' system bash may launch WSL; these scripts also support Git Bash.
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    executable = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
    assert executable, "Bash is required for deployment verification"
    result = subprocess.run([executable, "-c", script], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize("selection", ["--gateway", "--images gateway", "--all", "--components application"])
def test_gateway_build_selection(selection):
    result = bash_run(f"bash deploy/images/build.sh {selection} --version gateway-fixture --dry-run")
    assert "nexent/nexent-gateway:gateway-fixture" in result
    assert "gateway/Dockerfile" in result


@pytest.mark.parametrize("source,prefix", [
    ("general", "nexent"),
    ("mainland", "ccr.ccs.tencentyun.com/nexent-hub"),
])
def test_gateway_image_source_files(source, prefix):
    result = bash_run(f'APP_VERSION=fixture; source deploy/env/image-source.{source}.env; printf "%s" "$NEXENT_GATEWAY_IMAGE"')
    assert result == f"{prefix}/nexent-gateway:fixture"


@pytest.mark.parametrize("mode,expected", [
    ("general", "nexent/nexent-gateway:fixture"),
    ("local-latest", "nexent/nexent-gateway:latest"),
])
def test_gateway_image_defaults_and_helm_override(mode, expected):
    result = bash_run(f'''source deploy/common/common.sh
DEPLOYMENT_APP_VERSION=fixture
DEPLOYMENT_IMAGE_SOURCE={mode}
DEPLOYMENT_IMAGE_REGISTRY_PREFIX=
DEPLOYMENT_SANDBOX_MODE=disabled
deployment_apply_image_source
printf '%s\\n' "$NEXENT_GATEWAY_IMAGE"
deployment_render_image_rollout_checksums
deployment_render_image_values
''')
    assert result.splitlines()[0] == expected
    assert "gatewayImage:" in result
    overrides = yaml.safe_load(result[result.index("nexent-config:"):])
    image = overrides["nexent-gateway"]["images"]["backend"]
    assert image["repository"] + ":" + image["tag"] == expected


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_gateway_has_no_business_dependencies(filename):
    compose = yaml.safe_load((ROOT / "deploy/docker/compose" / filename).read_text(encoding="utf-8"))
    gateway = compose["services"]["nexent-gateway"]
    assert "NEXENT_GATEWAY_IMAGE" in gateway["image"]
    assert gateway["entrypoint"] == ["python", "backend/gateway_service.py"]
    assert gateway["environment"]["GATEWAY_PORT"] == "5013"
    assert "nexent-northbound" not in compose["services"]
    assert "GATEWAY_DB_PASSWORD" in gateway["environment"]
    assert gateway["environment"]["GATEWAY_AUTH_ENABLED"] == "true"
    assert "JWT_ISSUER" in gateway["environment"]
    assert "JWT_SECRET" in gateway["environment"]
    assert not {"env_file", "volumes", "user", "command"} & gateway.keys()
    assert set(gateway["depends_on"]) == {"nexent-config", "nexent-runtime"}
    assert gateway["healthcheck"]["test"] == ["CMD", "python", "-m", "gateway.healthcheck"]
    mcp = compose["services"]["nexent-mcp"]
    assert mcp["environment"]["GATEWAY_AUTH_ENABLED"] == "true"
    assert mcp["environment"]["GATEWAY_SERVICE_URL"] == "http://nexent-gateway:5013"


def test_helm_gateway_is_independent_and_scalable(tmp_path):
    helm = shutil.which("helm")
    assert helm, "Helm is required for deployment verification"
    # Build file:// dependencies in a temporary copy, without cluster access.
    chart = tmp_path / "charts/nexent-gateway"
    shutil.copytree(CHART / "charts/nexent-gateway", chart)
    shutil.copytree(CHART / "charts/nexent-common", chart.parent / "nexent-common")
    dependencies = subprocess.run([helm, "dependency", "build", str(chart)],
                                  capture_output=True, text=True, timeout=30)
    assert dependencies.returncode == 0, dependencies.stderr
    values = tmp_path / "global.yaml"
    values.write_text("global:\n  namespace: nexent\n  deploymentVersion: full\n", encoding="utf-8")
    result = subprocess.run([helm, "template", "gateway", str(chart),
                             "-f", str(values), "--set", "replicaCount=2",
                             "--set", "nexent-common.secrets.jwtSecret=deployment-test-fixture"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if item]
    config = next(item for item in documents if item.get("kind") == "ConfigMap" and item["metadata"]["name"] == "nexent-config")
    assert "GATEWAY_AUTH_ENABLED" not in config["metadata"]
    assert config["data"]["GATEWAY_AUTH_ENABLED"] == "true"
    assert config["data"]["GATEWAY_SERVICE_URL"] == "http://nexent-gateway:5013"
    deployment = next(item for item in documents if item.get("kind") == "Deployment")
    assert deployment["spec"]["replicas"] == 2
    assert deployment["spec"]["strategy"]["type"] == "RollingUpdate"
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["image"] == "nexent/nexent-gateway:latest"
    assert container["command"] == ["python", "backend/gateway_service.py"]
    assert container["securityContext"]["runAsNonRoot"] is True
    assert not {"envFrom", "volumeMounts"} & container.keys()
    assert "volumes" not in pod
    env = {item["name"]: item for item in container["env"]}
    assert env["JWT_SECRET"]["valueFrom"]["secretKeyRef"]["key"] == "JWT_SECRET"
    assert env["GATEWAY_SIGNING_SECRET"]["valueFrom"]["secretKeyRef"]["optional"] is True
    assert set(env) == {"TZ", "GATEWAY_DB_HOST", "GATEWAY_DB_PORT", "GATEWAY_DB_NAME", "GATEWAY_DB_USER", "GATEWAY_DB_PASSWORD", "GATEWAY_DB_POOL_SIZE", "GATEWAY_DB_TIMEOUT", "JWT_SECRET", "JWT_ISSUER", "GATEWAY_SIGNING_SECRET", "GATEWAY_AUTH_ENABLED",
                        "GATEWAY_MANAGEMENT_URL", "GATEWAY_NORTHBOUND_URL", "GATEWAY_RUNTIME_URL", "DEPLOYMENT_VERSION", "GATEWAY_PORT"}


def test_offline_application_includes_gateway():
    result = bash_run("bash deploy/offline/build_offline_package.sh --defaults --target docker "
                      "--version gateway-fixture --components application --image-source general "
                      "--include-sandbox false --dry-run")
    assert "nexent/nexent-gateway:gateway-fixture" in result
    assert "nexent/nexent:gateway-fixture" in result


def test_custom_gateway_image_uses_registry_prefix():
    result = bash_run('''source deploy/common/common.sh
DEPLOYMENT_IMAGE_SOURCE=general
DEPLOYMENT_SANDBOX_MODE=disabled
DEPLOYMENT_IMAGE_REGISTRY_PREFIX=mirror.example.test/team
NEXENT_GATEWAY_IMAGE=example/gateway:fixed
deployment_apply_image_source
printf '%s' "$NEXENT_GATEWAY_IMAGE"
''')
    assert result == "mirror.example.test/team/example/gateway:fixed"


@pytest.mark.parametrize("registry", ["overseas", "mainland"])
def test_release_matrix_publishes_gateway(registry):
    workflow = yaml.safe_load((ROOT / f".github/workflows/docker-build-push-{registry}.yml").read_text(encoding="utf-8"))
    assert "gateway" in workflow["jobs"]["build-and-push"]["strategy"]["matrix"]["image"]
