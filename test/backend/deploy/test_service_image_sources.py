# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent service targets retain executable tool plugins without peer sources."""

from pathlib import Path
from runpy import run_path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
MONITORING_PRODUCER_SOURCES = {
    "backend/ops/__init__.py",
    *("backend/ops/monitoring/" + name + ".py" for name in
      ("__init__", "runtime", "contracts", "model", "agent", "search", "service", "store")),
}


def test_backend_dockerfile_does_not_declare_exposed_ports():
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
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
    copies = [line.split() for line in common_and_services.replace("\\\n", " ").splitlines() if line.startswith("COPY ")]
    for parts in copies:
        assert all(
            source in MONITORING_PRODUCER_SOURCES
            or not source.startswith(("backend/ops", "backend/data_process", "backend/services/"))
            for source in parts[1:-1]
        )
    runtime = dockerfile.split("FROM backend-common AS runtime\n", 1)[1].split("\nFROM ", 1)[0]
    common = dockerfile.split("FROM base AS backend-common\n", 1)[1].split("\nFROM ", 1)[0]
    sql_sources = [source for line in (runtime + common).splitlines() if line.startswith("COPY deploy/sql/")
                   for source in line.split()[1:-1]]
    assert set(sql_sources) <= {"deploy/sql/ops-init.sql", "deploy/sql/migrations/ops/"}


def test_independent_services_package_the_shared_monitoring_producer_and_ops_migrations():
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    common = dockerfile.split("FROM base AS backend-common\n", 1)[1].split("\nFROM ", 1)[0]
    sources = {source for line in common.replace("\\\n", " ").splitlines() if line.startswith("COPY ")
               for source in line.split()[1:-1]}
    assert MONITORING_PRODUCER_SOURCES <= sources
    for target in (common, dockerfile.split(" AS standalone-service\n", 1)[1].split("\nFROM ", 1)[0]):
        assert "postgresql-client" in target
        assert "deploy/common/run-ops-sql-migrations.sh" in target
        assert "deploy/common/run-sql-migrations.sh" in target
        assert "deploy/sql/ops-init.sql" in target and "deploy/sql/migrations/ops/" in target
    packaging = run_path(str(ROOT / "deploy/images/dockerfiles/main/copy_service_sources.py"))
    closure = packaging["collect_sources"](ROOT, ("ops.monitoring.runtime",))
    assert not any(path.as_posix().startswith("backend/management/") for path in closure)


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


@pytest.mark.parametrize("service", ["management", "runtime", "mcp-service", "ops"])
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
    assert services["nexent-mcp"]["image"] == "${NEXENT_MCP_SERVICE_IMAGE:-nexent/nexent-mcp-service:latest}"
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


@pytest.mark.parametrize("mode,tag", [("general", "fixture"), ("local-latest", "latest")])
def test_generated_helm_values_use_independent_service_images(mode, tag):
    from test.backend.deploy.test_gateway_image import bash_run
    result = bash_run(f'''source deploy/common/common.sh
unset NEXENT_MANAGEMENT_IMAGE NEXENT_RUNTIME_IMAGE NEXENT_MCP_SERVICE_IMAGE NEXENT_OPS_IMAGE
DEPLOYMENT_APP_VERSION=fixture
DEPLOYMENT_IMAGE_SOURCE={mode}
DEPLOYMENT_IMAGE_REGISTRY_PREFIX=
DEPLOYMENT_SANDBOX_MODE=disabled
deployment_apply_image_source
deployment_render_image_values
''')
    values = yaml.safe_load(result)
    for name, service, checksum in (
        ("nexent-config", "management", "managementImage"),
        ("nexent-runtime", "runtime", "runtimeImage"),
        ("nexent-mcp", "mcp-service", "mcpServiceImage"),
        ("nexent-ops", "ops", "opsImage"),
    ):
        image = values[name]["images"]["backend"]
        assert image["repository"] == f"nexent/nexent-{service}"
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
    assert "nexent/nexent-mcp-service:latest" in result
    assert "nexent/nexent-ops:latest" in result
    assert "nexent/nexent-mcp:latest" in result


@pytest.mark.parametrize("service", ["mcp-service", "ops"])
def test_source_collection_includes_dependencies_without_other_launchers(service):
    packaging = run_path(str(ROOT / "deploy/images/dockerfiles/main/copy_service_sources.py"))
    files = {
        path.as_posix()
        for path in packaging["collect_sources"](ROOT, packaging["SERVICE_MODULES"][service])
    }
    assert "backend/contracts/constants/environment.py" in files
    assert "infrastructure/rdb/client.py" in files
    assert "backend/http/config_service.py" not in files
    assert "backend/http/runtime_service.py" not in files
    assert not any(path.startswith("backend/data_process/") for path in files)
    if service == "ops":
        assert "backend/ops/services/trajectory/lifecycle.py" in files
        assert "backend/http/mcp_service.py" not in files
        assert "backend/management/db/models/__init__.py" not in files
    else:
        assert "backend/management/services/agent/nl2agent.py" in files
        assert not any(path.startswith("backend/ops/") for path in files)


def test_source_collection_resolves_relative_and_literal_dynamic_imports(tmp_path):
    package = tmp_path / "backend" / "service"
    package.mkdir(parents=True)
    for name, code in {
        "__init__.py": "",
        "app.py": "from . import helpers\nimport importlib\nimportlib.import_module('service.plugin')",
        "helpers.py": "",
        "plugin.py": "",
        "unused.py": "",
    }.items():
        (package / name).write_text(code, encoding="utf-8")
    packaging = run_path(str(ROOT / "deploy/images/dockerfiles/main/copy_service_sources.py"))
    paths = packaging["collect_sources"](tmp_path, ("service.app",))
    assert {p.name for p in paths} == {"__init__.py", "app.py", "helpers.py", "plugin.py"}
