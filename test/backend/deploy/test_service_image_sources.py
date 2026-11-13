# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent service targets retain executable tool plugins without peer sources."""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("service,peer", [("management", "runtime"), ("runtime", "management")])
def test_independent_target_installs_deployment_plugins_without_peer_sources(service, peer):
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    section = dockerfile.split("FROM backend-common AS " + service + "\n", 1)[1].split("\nFROM ", 1)[0]
    copies = [line.split() for line in section.splitlines() if line.startswith("COPY ")]
    assert any(parts[1:] == ["backend/tool_collection/langchain", "/opt/backend/tool_collection/langchain"]
               for parts in copies)
    assert any(parts[1] == "backend/" + service for parts in copies)
    assert all(parts[1] not in {"backend", "backend/" + peer} for parts in copies)
    assert (ROOT / "backend/tool_collection/langchain").is_dir()

@pytest.mark.parametrize("service", ["management", "runtime"])
@pytest.mark.parametrize("syntax", ["list", "flag"])
def test_service_build_selection_uses_independent_target_and_latest(service, syntax):
    from test.backend.deploy.test_gateway_image import bash_run
    selection = f"--images {service}" if syntax == "list" else f"--{service}"
    result = bash_run(f"bash deploy/images/build.sh {selection} --version latest --load --dry-run")
    assert f"nexent/nexent-{service}:latest" in result
    assert f"--target {service}" in result
    assert "--load" in result


def test_service_flags_combine_and_deduplicate():
    from test.backend.deploy.test_gateway_image import bash_run
    result = bash_run("bash deploy/images/build.sh --management --runtime --management --version latest --load --dry-run")
    assert result.count("-t nexent/nexent-management:latest") == 1
    assert result.count("-t nexent/nexent-runtime:latest") == 1
    assert result.count("+ docker buildx build ") == 2


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_uses_independent_service_images(filename):
    services = yaml.safe_load((ROOT / "deploy/docker/compose" / filename).read_text(encoding="utf-8"))["services"]
    for name, service in (("nexent-config", "management"), ("nexent-runtime", "runtime")):
        assert services[name]["image"] == f"${{NEXENT_{service.upper()}_IMAGE:-nexent/nexent-{service}:latest}}"
        assert "NEXENT_IMAGE}" not in services[name]["image"]


@pytest.mark.parametrize("mode,tag", [("general", "fixture"), ("local-latest", "latest")])
def test_generated_helm_values_keep_management_and_runtime_separate(mode, tag):
    from test.backend.deploy.test_gateway_image import bash_run
    result = bash_run(f'''source deploy/common/common.sh
unset NEXENT_MANAGEMENT_IMAGE NEXENT_RUNTIME_IMAGE
DEPLOYMENT_APP_VERSION=fixture
DEPLOYMENT_IMAGE_SOURCE={mode}
DEPLOYMENT_IMAGE_REGISTRY_PREFIX=
DEPLOYMENT_SANDBOX_MODE=disabled
deployment_apply_image_source
deployment_render_image_values
''')
    values = yaml.safe_load(result)
    for name, service in (("nexent-config", "management"), ("nexent-runtime", "runtime")):
        image = values[name]["images"]["backend"]
        assert image["repository"] == f"nexent/nexent-{service}"
        assert image["tag"] == tag
        chart = ROOT / "deploy/k8s/helm/nexent/charts" / name
        defaults = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))
        assert defaults["images"]["backend"]["repository"] == f"nexent/nexent-{service}"
        assert f'"{service}Image"' in (chart / "templates/deployment.yaml").read_text(encoding="utf-8")


def test_offline_application_collects_both_service_images():
    from test.backend.deploy.test_gateway_image import bash_run
    result = bash_run("bash deploy/offline/build_offline_package.sh --defaults --target docker "
                      "--version latest --components application --image-source general "
                      "--include-sandbox false --dry-run")
    assert "nexent/nexent-management:latest" in result
    assert "nexent/nexent-runtime:latest" in result
