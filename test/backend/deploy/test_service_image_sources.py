# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent service targets retain executable tool plugins without peer sources."""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_backend_dockerfile_does_not_declare_exposed_ports():
    for service in ("main", "ops"):
        dockerfile = (ROOT / f"deploy/images/dockerfiles/{service}/Dockerfile").read_text(encoding="utf-8")
        instructions = [line.strip().split(maxsplit=1) for line in dockerfile.splitlines()]
        assert all(not parts or parts[0].upper() != "EXPOSE" for parts in instructions)


@pytest.mark.parametrize("service,peer", [("management", "runtime"), ("runtime", "management")])
def test_independent_target_installs_deployment_plugins_without_peer_sources(service, peer):
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    section = dockerfile.split(f" AS {service}\n", 1)[1].split("\nFROM ", 1)[0]
    copies = [line.split() for line in section.splitlines() if line.startswith("COPY ")]
    assert any(parts[1:] == ["backend/tool_collection/langchain", "/opt/backend/tool_collection/langchain"]
               for parts in copies)
    assert any(parts[1] == "backend/" + service for parts in copies)
    assert all(parts[1] not in {"backend", "backend/" + peer} for parts in copies)
    assert (ROOT / "backend/tool_collection/langchain").is_dir()


def test_independent_images_do_not_package_other_service_implementations():
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    common_and_services = dockerfile.split(" AS final\n", 1)[0]
    copies = [line.split() for line in common_and_services.splitlines() if line.startswith("COPY ")]
    for parts in copies:
        assert all(
            not source.startswith(("backend/ops", "backend/data_process", "backend/services/"))
            for source in parts[1:-1]
        )
    runtime = dockerfile.split("FROM backend-common AS runtime\n", 1)[1].split("\nFROM ", 1)[0]
    common = dockerfile.split("FROM base AS backend-common\n", 1)[1].split("\nFROM ", 1)[0]
    assert "COPY deploy/sql/" not in runtime + common


def test_runtime_packages_aidp_search_without_management_extensions():
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split(" AS runtime\n", 1)[1].split("\nFROM ", 1)[0]
    copies = [line.split() for line in runtime.replace("\\\n", " ").splitlines() if line.startswith("COPY ")]
    sources = {source.rstrip("/") for parts in copies for source in parts[1:-1]}
    aidp = "backend/ext_components/aidp"

    assert {
        f"{aidp}/consts",
        f"{aidp}/database",
        f"{aidp}/services/aidp_access_service.py",
        f"{aidp}/services/aidp_permission_service.py",
        f"{aidp}/services/aidp_service.py",
    } <= sources
    assert sources.isdisjoint({
        "backend/adapters",
        "backend/ext_components",
        aidp,
        f"{aidp}/apps",
        f"{aidp}/apps/aidp_mgmt_app.py",
        f"{aidp}/services",
        f"{aidp}/services/aidp_kb_update_service.py",
    })


@pytest.mark.parametrize("service", ["management", "runtime", "ops"])
@pytest.mark.parametrize("syntax", ["list", "flag"])
def test_service_build_selection_uses_independent_target_and_latest(service, syntax):
    from test.backend.deploy.test_gateway_image import bash_run
    selection = f"--images {service}" if syntax == "list" else f"--{service}"
    result = bash_run(f"bash deploy/images/build.sh {selection} --version latest --load --dry-run")
    assert f"nexent/nexent-{service}:latest" in result
    if service == "ops":
        assert f"dockerfiles/{service}/Dockerfile" in result
        assert "--target" not in result
    else:
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
    assert services["nexent-mcp"]["image"] == services["nexent-config"]["image"]
    assert services["nexent-mcp"]["entrypoint"][1:] == ["python", "-m", "backend.http.mcp_service"]
    assert services["nexent-mcp"]["environment"]["NEXENT_SQL_STARTUP_MODE"] == "off"
    assert services["nexent-ops"]["extends"]["service"] == "nexent-ops"
    ops = ROOT / "deploy/docker/compose/docker-compose-ops.yml"
    assert yaml.safe_load(ops.read_text(encoding="utf-8"))["services"]["nexent-ops"]["image"] == (
        "${NEXENT_OPS_IMAGE:-nexent/nexent-ops:latest}"
    )


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_helm_management_launcher_matches_compose_module_entrypoint(filename):
    compose = ROOT / "deploy/docker/compose" / filename
    management = yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]["nexent-config"]
    helm = ROOT / "deploy/k8s/helm/nexent/charts/nexent-config/templates/_pod-spec.tpl"
    command = helm.read_text(encoding="utf-8").split("    command:\n", 1)[1].split("    envFrom:", 1)[0]

    assert yaml.safe_load(command) == management["entrypoint"]
    assert management["entrypoint"][1:] == ["python", "-m", "backend.http.config_service"]


@pytest.mark.parametrize("mode,tag,prefix", [
    ("general", "fixture", ""),
    ("local-latest", "latest", ""),
    ("local-latest", "latest", "registry.local/nexent/"),
])
def test_generated_helm_values_use_independent_service_images(mode, tag, prefix):
    from test.backend.deploy.test_gateway_image import bash_run
    result = bash_run(f'''source deploy/common/common.sh
unset NEXENT_MANAGEMENT_IMAGE NEXENT_RUNTIME_IMAGE NEXENT_OPS_IMAGE
DEPLOYMENT_APP_VERSION=fixture
DEPLOYMENT_IMAGE_SOURCE={mode}
DEPLOYMENT_IMAGE_REGISTRY_PREFIX={prefix}
DEPLOYMENT_SANDBOX_MODE=disabled
deployment_apply_image_source
deployment_render_image_values
''')
    values = yaml.safe_load(result)
    for name, service, checksum in (
        ("nexent-config", "management", "managementImage"),
        ("nexent-runtime", "runtime", "runtimeImage"),
        ("nexent-mcp", "management", "managementImage"),
        ("nexent-ops", "ops", "opsImage"),
    ):
        image = values[name]["images"]["backend"]
        assert image["repository"] == f"{prefix}nexent/nexent-{service}"
        assert image["tag"] == tag
        chart = ROOT / "deploy/k8s/helm/nexent/charts" / name
        defaults = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))
        assert defaults["images"]["backend"]["repository"] == f"nexent/nexent-{service}"
        assert f'"{checksum}"' in (chart / "templates/deployment.yaml").read_text(encoding="utf-8")


def test_offline_application_collects_independent_service_images_and_mcp_proxy():
    from test.backend.deploy.test_gateway_image import bash_run
    result = bash_run("bash deploy/offline/build_offline_package.sh --defaults --target docker "
                      "--version latest --components application --image-source general "
                      "--include-sandbox false --dry-run")
    assert "nexent/nexent-management:latest" in result
    assert "nexent/nexent-runtime:latest" in result
    assert "nexent/nexent-mcp-service:latest" not in result
    assert "nexent/nexent-ops:latest" in result
    assert "nexent/nexent-mcp:latest" in result


def test_ops_dockerfile_includes_dependencies_without_other_launchers():
    dockerfile = ROOT / "deploy/images/dockerfiles/ops/Dockerfile"
    instructions = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ").splitlines()
    for directory in ("backend/management/api/permission", "backend/management/db/trajectory", "infrastructure/trace"):
        assert f"COPY {directory} /opt/{directory}" in instructions
    sources = [
        ROOT / path
        for line in instructions if line.startswith("COPY ")
        for path in line.split()[1:-1] if not path.startswith("--")
    ]
    assert all(source.exists() for source in sources)
    assert len(set(sources)) == len(sources)
    files = set()
    for source in sources:
        paths = source.rglob("*.py") if source.is_dir() else (source,)
        files.update(path.relative_to(ROOT).as_posix() for path in paths)
    assert "backend/contracts/constants/environment.py" in files
    assert "infrastructure/rdb/client.py" in files
    assert "backend/http/config_service.py" not in files
    assert "backend/http/runtime_service.py" not in files
    assert not any(path.startswith("backend/data_process/") for path in files)
    assert "backend/http/ops_service.py" in files
    assert "backend/ops/scripts/backfill_trajectory_summaries.py" in files
    assert "backend/ops/services/trajectory/lifecycle.py" in files
    assert "backend/http/mcp_service.py" not in files
    assert "backend/management/db/models/__init__.py" not in files


def test_management_image_packages_mcp_sources_without_runtime():
    source = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    management, runtime = source.split("FROM management-base AS management\n", 1)[1].split(
        "FROM backend-common AS runtime\n", 1,
    )
    runtime = runtime.split("\nFROM ", 1)[0]
    for path in ("backend/http/mcp_service.py", "backend/mcp", "backend/tool_collection/mcp"):
        assert path in management
        assert path not in runtime


def test_downstream_images_copy_one_shared_gateway_identity_package():
    dockerfiles = ROOT / "deploy/images/dockerfiles"
    main = (dockerfiles / "main/Dockerfile").read_text(encoding="utf-8")
    ops = (dockerfiles / "ops/Dockerfile").read_text(encoding="utf-8")
    shared_identity = "COPY backend/gateway/identity /opt/backend/gateway/identity"
    for service in ("management", "runtime"):
        stage = main.split(f" AS {service}\n", 1)[1].split("\nFROM ", 1)[0]
        assert stage.count(shared_identity) == 1
        assert "COPY backend/gateway/security" not in stage
    assert ops.count(shared_identity) == 1
    assert "backend/gateway/security" not in ops
